from __future__ import annotations

import csv
import json
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase


LESSON_ROOT = Path(__file__).resolve().parents[1]
PHASE_ROOT = LESSON_ROOT.parent
DATA_ROOT = PHASE_ROOT / "data" / "tiny"
SOURCE_SERIES = PHASE_ROOT / "02-resampling" / "outputs" / "daily_resampled.csv"
CUTOFF_CONTRACT = PHASE_ROOT / "05-temporal-leakage" / "outputs" / "cutoff_contract.json"
BASELINE_REPORT = PHASE_ROOT / "06-forecast-baselines" / "outputs" / "baseline_report.json"
sys.path.insert(0, str(LESSON_ROOT / "outputs"))

from decomposition_reporter import build_decomposition_package  # noqa: E402


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    fieldnames = list(rows[0]) if rows else []
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def row_for(rows: list[dict[str, str]], **criteria: str) -> dict[str, str]:
    return next(row for row in rows if all(row[key] == value for key, value in criteria.items()))


class DecompositionReporterTest(TestCase):
    def build(
        self,
        *,
        root: Path = DATA_ROOT,
        series_path: Path = SOURCE_SERIES,
        cutoff_contract_path: Path = CUTOFF_CONTRACT,
        baseline_report_path: Path = BASELINE_REPORT,
    ) -> dict:
        return build_decomposition_package(
            series_path=series_path,
            scenario_path=root / "forecast_scenario.json",
            cutoff_contract_path=cutoff_contract_path,
            baseline_report_path=baseline_report_path,
            spec_path=root / "decomposition_spec.json",
        )

    def test_tiny_profile_builds_stl_components_with_expected_warning(self) -> None:
        package = self.build()
        report = package["report"]

        self.assertTrue(report["valid"])
        self.assertEqual(report["error_count"], 0)
        self.assertEqual(report["summary"]["warnings"], ["short_history_blocks_accuracy_claim"])
        self.assertEqual(report["outputs"]["component_rows"], 30)
        self.assertEqual(report["outputs"]["diagnostics_rows"], 2)
        self.assertEqual(report["outputs"]["method_id"], "stl_additive")
        self.assertEqual(report["outputs"]["training_end"], "2026-03-16")

    def test_data_generator_check_rebuilds_committed_decomposition_spec(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(PHASE_ROOT / "data" / "generate_data.py"),
                "--check",
                "--output",
                str(DATA_ROOT),
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertIn("reproducible", result.stdout)

    def test_stl_components_match_reviewed_tiny_values(self) -> None:
        rows = self.build()["component_rows"]
        first_all = row_for(rows, segment_id="all", observed_date="2026-03-02")
        weekend_all = row_for(rows, segment_id="all", observed_date="2026-03-07")
        first_android = row_for(rows, segment_id="android", observed_date="2026-03-02")
        last_android = row_for(rows, segment_id="android", observed_date="2026-03-16")

        self.assertEqual(first_all["trend"], "984.060186")
        self.assertEqual(first_all["seasonal"], "14.836851")
        self.assertEqual(first_all["residual"], "-0.897037")
        self.assertEqual(weekend_all["seasonal"], "-32.358018")
        self.assertEqual(first_android["trend"], "313.142857")
        self.assertEqual(first_android["seasonal"], "4.857143")
        self.assertEqual(first_android["residual"], "0")
        self.assertEqual(last_android["trend"], "369.142857")

    def test_component_rows_reconstruct_observed_and_stop_at_cutoff(self) -> None:
        rows = self.build()["component_rows"]
        dates = {row["observed_date"] for row in rows}

        self.assertNotIn("2026-03-17", dates)
        self.assertEqual(sum(1 for row in rows if row["segment_id"] == "all"), 15)
        for row in rows:
            reconstructed = float(row["trend"]) + float(row["seasonal"]) + float(row["residual"])
            self.assertAlmostEqual(float(row["observed_value"]), reconstructed, places=5)
            self.assertEqual(row["reconstruction_error"], "0")

    def test_residual_diagnostics_keep_decomposition_diagnostic_only(self) -> None:
        diagnostics = self.build()["diagnostics_rows"]
        all_row = row_for(diagnostics, segment_id="all")
        android_row = row_for(diagnostics, segment_id="android")

        self.assertEqual(all_row["training_cycles"], "2.142857")
        self.assertEqual(all_row["residual_max_abs"], "0.897037")
        self.assertEqual(all_row["lag1_autocorrelation"], "0.736152")
        self.assertEqual(all_row["decision_status"], "diagnostic_only_short_history")
        self.assertEqual(all_row["warnings"], "short_history_blocks_accuracy_claim")
        self.assertEqual(android_row["seasonal_amplitude"], "17")
        self.assertEqual(android_row["residual_max_abs"], "0")

    def test_invalid_baseline_report_blocks_decomposition_handoff(self) -> None:
        with TemporaryDirectory() as directory:
            baseline_path = Path(directory) / "baseline_report.json"
            report = read_json(BASELINE_REPORT)
            report["valid"] = False
            write_json(baseline_path, report)

            result = self.build(baseline_report_path=baseline_path)["report"]

        self.assertFalse(result["valid"])
        self.assertIn("baseline_report_is_valid", result["summary"]["blocking_errors"])

    def test_seasonal_period_must_stay_precommitted_to_weekly_cycle(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(DATA_ROOT, root, dirs_exist_ok=True)
            spec = read_json(root / "decomposition_spec.json")
            spec["seasonal_period_days"] = 14
            write_json(root / "decomposition_spec.json", spec)

            result = self.build(root=root)["report"]

        self.assertFalse(result["valid"])
        self.assertIn("seasonal_period_is_precommitted", result["summary"]["blocking_errors"])

    def test_multiplicative_component_model_is_not_silently_accepted(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(DATA_ROOT, root, dirs_exist_ok=True)
            spec = read_json(root / "decomposition_spec.json")
            spec["component_model"] = "multiplicative"
            write_json(root / "decomposition_spec.json", spec)

            result = self.build(root=root)["report"]

        self.assertFalse(result["valid"])
        self.assertIn("decomposition_method_supported", result["summary"]["blocking_errors"])

    def test_interpretation_policy_must_block_forecast_claim(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(DATA_ROOT, root, dirs_exist_ok=True)
            spec = read_json(root / "decomposition_spec.json")
            spec["interpretation_policy"]["decomposition_is_diagnostic_not_forecast_evidence"] = False
            write_json(root / "decomposition_spec.json", spec)

            result = self.build(root=root)["report"]

        self.assertFalse(result["valid"])
        self.assertIn("interpretation_policy_blocks_forecast_claim", result["summary"]["blocking_errors"])

    def test_training_rows_after_cutoff_block_decomposition(self) -> None:
        with TemporaryDirectory() as directory:
            series_path = Path(directory) / "daily_resampled.csv"
            rows = read_csv(SOURCE_SERIES)
            for row in rows:
                if row["observed_date"] == "2026-03-17":
                    row["include_in_training"] = "true"
            write_csv(series_path, rows)

            result = self.build(series_path=series_path)["report"]

        self.assertFalse(result["valid"])
        self.assertIn("decomposition_uses_training_window_only", result["summary"]["blocking_errors"])

    def test_duplicate_source_segment_date_blocks_report(self) -> None:
        with TemporaryDirectory() as directory:
            series_path = Path(directory) / "daily_resampled.csv"
            rows = read_csv(SOURCE_SERIES)
            rows.append(rows[0].copy())
            write_csv(series_path, rows)

            result = self.build(series_path=series_path)["report"]

        self.assertFalse(result["valid"])
        self.assertIn("source_segment_date_unique", result["summary"]["blocking_errors"])

    def test_missing_training_date_blocks_report(self) -> None:
        with TemporaryDirectory() as directory:
            series_path = Path(directory) / "daily_resampled.csv"
            rows = [
                row
                for row in read_csv(SOURCE_SERIES)
                if not (row["segment_id"] == "all" and row["observed_date"] == "2026-03-09")
            ]
            write_csv(series_path, rows)

            result = self.build(series_path=series_path)["report"]

        self.assertFalse(result["valid"])
        self.assertIn("training_rows_match_cutoff", result["summary"]["blocking_errors"])

    def test_minimum_history_policy_blocks_overdemanding_stl(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(DATA_ROOT, root, dirs_exist_ok=True)
            spec = read_json(root / "decomposition_spec.json")
            spec["minimum_training_points"] = 16
            write_json(root / "decomposition_spec.json", spec)

            result = self.build(root=root)["report"]

        self.assertFalse(result["valid"])
        self.assertIn("enough_history_for_stl", result["summary"]["blocking_errors"])

    def test_cutoff_contract_must_align_with_decomposition_spec(self) -> None:
        with TemporaryDirectory() as directory:
            cutoff_path = Path(directory) / "cutoff_contract.json"
            cutoff = read_json(CUTOFF_CONTRACT)
            cutoff["training_end"] = "2026-03-15"
            write_json(cutoff_path, cutoff)

            result = self.build(cutoff_contract_path=cutoff_path)["report"]

        self.assertFalse(result["valid"])
        self.assertIn(
            "scenario_cutoff_baseline_and_decomposition_spec_align",
            result["summary"]["blocking_errors"],
        )

    def test_cli_writes_package_and_can_fail_on_warning(self) -> None:
        with TemporaryDirectory() as directory:
            output_dir = Path(directory) / "package"
            command = [
                sys.executable,
                str(LESSON_ROOT / "outputs" / "decomposition_reporter.py"),
                "--series",
                str(SOURCE_SERIES),
                "--scenario",
                str(DATA_ROOT / "forecast_scenario.json"),
                "--cutoff-contract",
                str(CUTOFF_CONTRACT),
                "--baseline-report",
                str(BASELINE_REPORT),
                "--spec",
                str(DATA_ROOT / "decomposition_spec.json"),
                "--output-dir",
                str(output_dir),
            ]
            ok = subprocess.run(command, check=True, capture_output=True, text=True)
            strict = subprocess.run([*command, "--fail-on-warning"], check=False, capture_output=True, text=True)
            written_files = sorted(path.name for path in output_dir.iterdir())

        self.assertTrue(json.loads(ok.stdout)["valid"])
        self.assertEqual(strict.returncode, 1)
        self.assertEqual(
            written_files,
            ["decomposition_components.csv", "decomposition_report.json", "residual_diagnostics.csv"],
        )
