from __future__ import annotations

import copy
import csv
import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
PHASE_ROOT = ROOT.parent
DATA = PHASE_ROOT / "data" / "tiny"
ARTIFACT = ROOT / "outputs" / "randomization_health.py"
HEALTH_SPEC = ROOT / "outputs" / "randomization_health_spec.json"
REPORT = ROOT / "outputs" / "randomization_health_report.json"
PROTOCOL = PHASE_ROOT / "01-hypothesis-and-metric" / "outputs" / "experiment_protocol.json"
CODE = ROOT / "code" / "main.py"

MODULE_SPEC = importlib.util.spec_from_file_location("randomization_health", ARTIFACT)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
DIAGNOSTIC = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(DIAGNOSTIC)


def check(report: dict, check_id: str) -> dict:
    return next(item for item in report["checks"] if item["id"] == check_id)


def load_examples() -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]], dict, dict]:
    assignments = DIAGNOSTIC.read_csv(DATA / "assignments.csv")
    exposures = DIAGNOSTIC.read_csv(DATA / "exposures.csv")
    pre_metrics = DIAGNOSTIC.read_csv(DATA / "pre_experiment_metrics.csv")
    protocol = DIAGNOSTIC.read_json(PROTOCOL)
    health_spec = DIAGNOSTIC.read_json(HEALTH_SPEC)
    return assignments, exposures, pre_metrics, protocol, health_spec


def write_rows(path: Path, rows: list[dict[str, str]], fieldnames: list[str] | None = None) -> None:
    fieldnames = fieldnames or list(rows[0])
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


class RandomizationHealthTest(unittest.TestCase):
    def setUp(self) -> None:
        self.assignments, self.exposures, self.pre_metrics, self.protocol, self.health_spec = load_examples()

    def report(
        self,
        assignments: list[dict[str, str]] | None = None,
        exposures: list[dict[str, str]] | None = None,
        pre_metrics: list[dict[str, str]] | None = None,
    ) -> dict:
        return DIAGNOSTIC.build_report(
            self.assignments if assignments is None else assignments,
            self.exposures if exposures is None else exposures,
            self.pre_metrics if pre_metrics is None else pre_metrics,
            self.protocol,
            self.health_spec,
        )

    def test_committed_report_matches_calculated_output(self) -> None:
        calculated = self.report()
        committed = json.loads(REPORT.read_text(encoding="utf-8"))
        self.assertEqual(calculated, committed)
        self.assertTrue(calculated["valid"])
        self.assertTrue(calculated["ready_for_ab_analysis"])
        self.assertEqual(calculated["summary"]["assignment_variant_counts"], {"control": 3, "treatment": 2})
        self.assertEqual(check(calculated, "assignment_srm_chi_square")["observed"]["p_value"], 0.654721)

    def test_tiny_covariate_imbalance_is_warning_not_blocker(self) -> None:
        report = self.report()
        balance = check(report, "covariate_balance_standardized_difference")
        self.assertEqual(balance["severity"], "warning")
        self.assertFalse(balance["valid"])
        self.assertEqual(report["summary"]["blocking_failures"], [])
        self.assertEqual(report["summary"]["warning_checks"], ["covariate_balance_standardized_difference"])

    def test_aa_pre_experiment_pseudo_outcomes_use_exact_permutations(self) -> None:
        report = self.report()
        aa_check = check(report, "aa_pre_experiment_pseudo_outcomes")
        self.assertTrue(aa_check["valid"])
        sessions = next(item for item in aa_check["sample"] if item["column"] == "sessions_7d_pre")
        self.assertEqual(sessions["observed_difference"], 2.5)
        self.assertEqual(sessions["p_value"], 0.2)
        self.assertEqual(sessions["permutations"], 10)

    def test_code_example_prints_health_summary(self) -> None:
        result = subprocess.run(
            [sys.executable, CODE],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ready_for_ab_analysis"])
        self.assertEqual(payload["assignment_srm_p_value"], 0.654721)
        self.assertEqual(payload["telemetry_missing_units"], 0)
        self.assertEqual(payload["warning_checks"], ["covariate_balance_standardized_difference"])

    def test_assignment_srm_blocks_extreme_large_split(self) -> None:
        assignments = []
        exposures = []
        pre_metrics = []
        for index in range(100):
            user_id = f"UA{index:03d}"
            assignments.append(
                {
                    "experiment_id": self.protocol["experiment_id"],
                    "assignment_unit_type": "user_id",
                    "assignment_unit_id": user_id,
                    "user_id": user_id,
                    "variant_id": "control",
                    "bucket": str(index),
                    "assigned_at": "2026-06-10T00:00:00+03:00",
                    "allocation_ratio": "0.5",
                    "is_eligible": "true",
                    "assignment_source": "fixture",
                }
            )
            exposures.append(
                {
                    "exposure_id": f"X-{user_id}",
                    "experiment_id": self.protocol["experiment_id"],
                    "assignment_unit_id": user_id,
                    "user_id": user_id,
                    "variant_id": "control",
                    "exposure_event": "paywall_viewed",
                    "exposed_at": "2026-06-10T09:00:00+03:00",
                    "received_at": "2026-06-10T09:01:00+03:00",
                    "platform": "android",
                    "app_version": "5.20.0",
                }
            )
            pre_metrics.append(
                {
                    "experiment_id": self.protocol["experiment_id"],
                    "user_id": user_id,
                    "sessions_7d_pre": "1",
                    "activation_7d_pre": "0",
                    "support_tickets_7d_pre": "0",
                    "realized_revenue_7d_pre": "0.00",
                }
            )
        report = self.report(assignments=assignments, exposures=exposures, pre_metrics=pre_metrics)
        self.assertFalse(report["valid"])
        self.assertIn("assignment_srm_chi_square", report["summary"]["blocking_failures"])
        self.assertLess(check(report, "assignment_srm_chi_square")["observed"]["p_value"], 0.001)

    def test_telemetry_loss_blocks_missing_treatment_exposures(self) -> None:
        exposures = [row for row in copy.deepcopy(self.exposures) if row["variant_id"] != "treatment"]
        report = self.report(exposures=exposures)
        telemetry = check(report, "telemetry_loss_by_variant")
        self.assertFalse(report["valid"])
        self.assertFalse(telemetry["valid"])
        self.assertEqual(telemetry["observed"]["missing_units"], 2)
        self.assertIn("telemetry_loss_by_variant", report["summary"]["blocking_failures"])

    def test_extra_exposure_without_assignment_is_blocking(self) -> None:
        exposures = copy.deepcopy(self.exposures)
        extra = dict(exposures[0])
        extra["exposure_id"] = "X-extra"
        extra["assignment_unit_id"] = "U404"
        extra["user_id"] = "U404"
        exposures.append(extra)
        report = self.report(exposures=exposures)
        telemetry = check(report, "telemetry_loss_by_variant")
        self.assertFalse(telemetry["valid"])
        self.assertEqual(telemetry["observed"]["extra_exposure_units"], 1)

    def test_missing_pre_experiment_metric_row_blocks_report(self) -> None:
        pre_metrics = [row for row in copy.deepcopy(self.pre_metrics) if row["user_id"] != "U005"]
        report = self.report(pre_metrics=pre_metrics)
        metrics_check = check(report, "pre_experiment_metrics_complete")
        self.assertFalse(report["valid"])
        self.assertFalse(metrics_check["valid"])
        self.assertEqual(metrics_check["observed"]["missing_users"], ["U005"])

    def test_missing_pre_experiment_metric_column_blocks_report(self) -> None:
        pre_metrics = copy.deepcopy(self.pre_metrics)
        for row in pre_metrics:
            row.pop("sessions_7d_pre")
        report = self.report(pre_metrics=pre_metrics)
        metrics_check = check(report, "pre_experiment_metrics_complete")
        self.assertFalse(metrics_check["valid"])
        self.assertEqual(metrics_check["observed"]["missing_columns"], ["sessions_7d_pre"])

    def test_aa_check_flags_extreme_preperiod_difference_as_warning(self) -> None:
        assignments = []
        pre_metrics = []
        for index in range(8):
            variant_id = "control" if index < 4 else "treatment"
            user_id = f"UB{index:03d}"
            assignments.append(
                {
                    "experiment_id": self.protocol["experiment_id"],
                    "assignment_unit_type": "user_id",
                    "assignment_unit_id": user_id,
                    "user_id": user_id,
                    "variant_id": variant_id,
                    "bucket": str(index),
                    "assigned_at": "2026-06-10T00:00:00+03:00",
                    "allocation_ratio": "0.5",
                    "is_eligible": "true",
                    "assignment_source": "fixture",
                }
            )
            pre_metrics.append(
                {
                    "experiment_id": self.protocol["experiment_id"],
                    "user_id": user_id,
                    "sessions_7d_pre": "0" if variant_id == "control" else "100",
                    "activation_7d_pre": "0" if variant_id == "control" else "1",
                    "support_tickets_7d_pre": "0",
                    "realized_revenue_7d_pre": "0.00" if variant_id == "control" else "100.00",
                }
            )
        aa_check = DIAGNOSTIC.aa_pseudo_outcome_check(assignments, pre_metrics, self.protocol, self.health_spec)
        self.assertEqual(aa_check["severity"], "warning")
        self.assertFalse(aa_check["valid"])
        sessions = next(item for item in aa_check["sample"] if item["column"] == "sessions_7d_pre")
        self.assertEqual(sessions["p_value"], 0.028571)

    def test_cli_writes_report_and_returns_zero_for_baseline(self) -> None:
        with TemporaryDirectory() as directory:
            report_path = Path(directory) / "health.json"
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--assignments",
                    DATA / "assignments.csv",
                    "--exposures",
                    DATA / "exposures.csv",
                    "--pre-metrics",
                    DATA / "pre_experiment_metrics.csv",
                    "--protocol",
                    PROTOCOL,
                    "--health-spec",
                    HEALTH_SPEC,
                    "--output",
                    report_path,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), json.loads(report_path.read_text(encoding="utf-8")))

    def test_cli_returns_nonzero_for_blocking_telemetry_loss(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            exposure_path = root / "exposures.csv"
            exposures = [row for row in copy.deepcopy(self.exposures) if row["variant_id"] != "treatment"]
            write_rows(exposure_path, exposures, fieldnames=list(self.exposures[0]))
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--assignments",
                    DATA / "assignments.csv",
                    "--exposures",
                    exposure_path,
                    "--pre-metrics",
                    DATA / "pre_experiment_metrics.csv",
                    "--protocol",
                    PROTOCOL,
                    "--health-spec",
                    HEALTH_SPEC,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertFalse(json.loads(result.stdout)["valid"])


if __name__ == "__main__":
    unittest.main()
