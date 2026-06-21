from __future__ import annotations

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
ARTIFACT = ROOT / "outputs" / "peeking_audit.py"
POLICY = ROOT / "outputs" / "peeking_policy.json"
REPORT = ROOT / "outputs" / "sequential_monitoring_report.json"
SCHEDULE = ROOT / "outputs" / "monitoring_schedule.csv"
SIMULATION = ROOT / "outputs" / "peeking_simulation.csv"
MANIFEST = ROOT / "outputs" / "peeking_manifest.json"
PROTOCOL = PHASE_ROOT / "01-hypothesis-and-metric" / "outputs" / "experiment_protocol.json"
POWER_PLAN = PHASE_ROOT / "04-mde-and-power" / "outputs" / "power_plan.json"
MULTIPLE_TESTING = PHASE_ROOT / "08-multiple-testing" / "outputs" / "multiple_testing_report.json"
CODE = ROOT / "code" / "main.py"

MODULE_SPEC = importlib.util.spec_from_file_location("peeking_audit", ARTIFACT)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
AUDITOR = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(AUDITOR)


def load_examples() -> tuple[dict, dict, dict, dict]:
    return (
        AUDITOR.read_json(PROTOCOL),
        AUDITOR.read_json(POLICY),
        AUDITOR.read_json(POWER_PLAN),
        AUDITOR.read_json(MULTIPLE_TESTING),
    )


def row_by_id(rows: list[dict], look_id: str, status: str | None = None) -> dict:
    for row in rows:
        if row["look_id"] == look_id and (status is None or row["status"] == status):
            return row
    raise AssertionError(f"row not found: {look_id} {status}")


class PeekingAuditTest(unittest.TestCase):
    def setUp(self) -> None:
        self.protocol, self.policy, self.power_plan, self.multiple_testing = load_examples()

    def build(
        self,
        policy: dict | None = None,
        protocol: dict | None = None,
        multiple_testing: dict | None = None,
    ) -> tuple[dict, list[dict], list[dict], dict]:
        return AUDITOR.build_report(
            self.protocol if protocol is None else protocol,
            self.policy if policy is None else policy,
            self.power_plan,
            self.multiple_testing if multiple_testing is None else multiple_testing,
        )

    def test_committed_outputs_match_calculated_report(self) -> None:
        report, schedule_rows, simulation_rows, manifest = self.build()
        self.assertEqual(report, json.loads(REPORT.read_text(encoding="utf-8")))
        self.assertEqual(manifest, json.loads(MANIFEST.read_text(encoding="utf-8")))
        with TemporaryDirectory() as directory:
            root = Path(directory)
            schedule_path = root / "monitoring_schedule.csv"
            simulation_path = root / "peeking_simulation.csv"
            AUDITOR.write_csv(schedule_path, schedule_rows, AUDITOR.SCHEDULE_FIELDS)
            AUDITOR.write_csv(simulation_path, simulation_rows, AUDITOR.SIMULATION_FIELDS)
            self.assertEqual(schedule_path.read_text(encoding="utf-8"), SCHEDULE.read_text(encoding="utf-8"))
            self.assertEqual(simulation_path.read_text(encoding="utf-8"), SIMULATION.read_text(encoding="utf-8"))
        self.assertTrue(report["valid"])
        self.assertFalse(report["ready_for_decision"])
        self.assertEqual(report["summary"]["planned_decision_looks"], ["interim_50", "final"])

    def test_naive_peeking_inflates_false_positive_rate(self) -> None:
        report, _, simulation_rows, _ = self.build()
        one_look = next(row for row in simulation_rows if row["look_count"] == 1)
        five_looks = next(row for row in simulation_rows if row["look_count"] == 5)
        self.assertAlmostEqual(one_look["naive_false_positive_rate"], 0.05, delta=0.01)
        self.assertEqual(five_looks["naive_false_positive_rate"], 0.14155)
        self.assertGreater(five_looks["naive_false_positive_rate"], 0.12)
        self.assertLessEqual(five_looks["obrien_fleming_false_positive_rate"], 0.065)
        self.assertEqual(report["summary"]["naive_fpr_at_five_looks"], 0.14155)

    def test_planned_interim_uses_obrien_fleming_boundary(self) -> None:
        _, schedule_rows, _, _ = self.build()
        interim = row_by_id(schedule_rows, "interim_50", "continue_collecting")
        self.assertEqual(interim["observed_p_value"], 0.031)
        self.assertEqual(round(interim["nominal_p_boundary"], 6), 0.005575)
        self.assertTrue(interim["crosses_naive_alpha"])
        self.assertFalse(interim["crosses_spending_boundary"])
        self.assertEqual(interim["status"], "continue_collecting")

    def test_unplanned_decision_looks_block_decision(self) -> None:
        report, schedule_rows, _, _ = self.build()
        self.assertEqual(
            report["summary"]["unplanned_decision_looks"],
            ["day_05_slack_peek", "day_10_dashboard_refresh"],
        )
        self.assertIn("unplanned_decision_look:day_05_slack_peek", report["summary"]["decision_blockers"])
        self.assertIn("multiple_testing_does_not_allow_launch", report["summary"]["decision_blockers"])
        dashboard = row_by_id(schedule_rows, "day_10_dashboard_refresh")
        self.assertEqual(dashboard["status"], "unplanned_decision_peek")
        self.assertTrue(dashboard["crosses_naive_alpha"])
        self.assertTrue(dashboard["crosses_spending_boundary"])
        self.assertFalse(report["ready_for_decision"])

    def test_quality_monitoring_does_not_spend_alpha(self) -> None:
        report, schedule_rows, _, _ = self.build()
        quality = row_by_id(schedule_rows, "day_03_quality")
        self.assertEqual(quality["status"], "quality_only")
        self.assertEqual(quality["alpha_spent_cumulative"], 0.0)
        self.assertIsNone(quality["observed_p_value"])
        self.assertEqual(report["summary"]["quality_monitoring_checks"], ["daily_sample_size", "daily_srm", "telemetry_loss"])

    def test_contaminated_quality_monitoring_invalidates_audit(self) -> None:
        policy = json.loads(json.dumps(self.policy))
        policy["observed_looks"][0]["metrics_seen"].append("activation_rate_7d")
        policy["observed_looks"][0]["decision_metric_p_value"] = 0.04
        report, _, _, manifest = self.build(policy=policy)
        self.assertFalse(report["valid"])
        self.assertIn("quality_monitoring_excludes_decision_metrics", report["summary"]["blocking_failures"])
        self.assertFalse(manifest["valid"])

    def test_invalid_upstream_multiple_testing_blocks_validity(self) -> None:
        multiple_testing = json.loads(json.dumps(self.multiple_testing))
        multiple_testing["valid"] = False
        report, _, _, _ = self.build(multiple_testing=multiple_testing)
        self.assertFalse(report["valid"])
        self.assertIn("upstream_multiple_testing_valid", report["summary"]["blocking_failures"])

    def test_policy_must_include_final_look_and_match_alpha(self) -> None:
        policy = json.loads(json.dumps(self.policy))
        policy["alpha"] = 0.1
        policy["planned_decision_looks"] = [policy["planned_decision_looks"][0]]
        report, _, _, _ = self.build(policy=policy)
        self.assertFalse(report["valid"])
        self.assertIn("policy_alpha_matches_protocol", report["summary"]["blocking_failures"])
        self.assertIn("final_decision_look_is_planned", report["summary"]["blocking_failures"])

    def test_protocol_must_disallow_unplanned_decision_looks(self) -> None:
        protocol = json.loads(json.dumps(self.protocol))
        protocol["peeking_policy"]["unplanned_decision_looks_allowed"] = True
        report, _, _, _ = self.build(protocol=protocol)
        self.assertFalse(report["valid"])
        self.assertIn("protocol_disallows_unplanned_decision_looks", report["summary"]["blocking_failures"])

    def test_code_example_prints_peeking_summary(self) -> None:
        result = subprocess.run(
            [sys.executable, CODE],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(result.stdout)
        self.assertTrue(payload["valid"])
        self.assertFalse(payload["ready_for_decision"])
        self.assertEqual(payload["planned_decision_looks"], ["interim_50", "final"])
        self.assertEqual(payload["unplanned_decision_looks"], ["day_05_slack_peek", "day_10_dashboard_refresh"])
        self.assertEqual(payload["interim_50_nominal_p_boundary"], 0.005575)
        self.assertEqual(payload["interim_50_observed_p_value"], 0.031)
        self.assertFalse(payload["interim_50_crosses_spending_boundary"])
        self.assertEqual(payload["naive_fpr_at_five_looks"], 0.14155)
        self.assertEqual(payload["manifest_alpha_spending"], "lan_demets_obrien_fleming")

    def test_cli_writes_report_schedule_simulation_and_manifest(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            report_path = root / "report.json"
            schedule_path = root / "schedule.csv"
            simulation_path = root / "simulation.csv"
            manifest_path = root / "manifest.json"
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--protocol",
                    PROTOCOL,
                    "--peeking-policy",
                    POLICY,
                    "--power-plan",
                    POWER_PLAN,
                    "--multiple-testing-report",
                    MULTIPLE_TESTING,
                    "--output-report",
                    report_path,
                    "--output-schedule",
                    schedule_path,
                    "--output-simulation",
                    simulation_path,
                    "--output-manifest",
                    manifest_path,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), json.loads(report_path.read_text(encoding="utf-8")))
            self.assertEqual(schedule_path.read_text(encoding="utf-8"), SCHEDULE.read_text(encoding="utf-8"))
            self.assertEqual(simulation_path.read_text(encoding="utf-8"), SIMULATION.read_text(encoding="utf-8"))
            with schedule_path.open(encoding="utf-8", newline="") as source:
                self.assertEqual(len(list(csv.DictReader(source))), 7)
            self.assertEqual(json.loads(manifest_path.read_text(encoding="utf-8"))["scipy_version"], "1.17.1")


if __name__ == "__main__":
    unittest.main()
