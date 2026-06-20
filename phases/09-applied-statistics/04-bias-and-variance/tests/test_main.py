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
PHASE = ROOT.parent
DATA = PHASE / "data" / "tiny"
ARTIFACT = ROOT / "outputs" / "bias_variance_simulator.py"
SPEC_PATH = ROOT / "outputs" / "bias_variance_spec.json"
BASELINE_CSV = ROOT / "outputs" / "bias_variance.csv"
BASELINE_REPORT = ROOT / "outputs" / "bias_variance_report.json"
CODE = ROOT / "code" / "main.py"

MODULE_SPEC = importlib.util.spec_from_file_location("bias_variance_simulator", ARTIFACT)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
SIMULATOR = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(SIMULATOR)


def run_tiny() -> dict:
    return SIMULATOR.simulate(DATA / "population_users.csv", DATA / "sampling_frame.csv", SPEC_PATH)


def row(report: dict, mechanism_id: str, estimator_id: str) -> dict:
    return next(
        item
        for item in report["simulation_rows"]
        if item["mechanism_id"] == mechanism_id and item["estimator_id"] == estimator_id
    )


def check(report: dict, check_id: str) -> dict:
    return next(item for item in report["checks"] if item["id"] == check_id)


class BiasVarianceSimulatorTest(unittest.TestCase):
    def test_true_parameters_use_full_eligible_population_not_frame(self) -> None:
        report = run_tiny()
        self.assertTrue(report["valid"])
        self.assertEqual(report["summary"]["eligible_population_rows"], 8)
        self.assertEqual(report["summary"]["frame_rows"], 7)
        self.assertEqual(report["true_parameters"]["activation_rate"], 0.625)
        self.assertEqual(report["true_parameters"]["first_order_amount_rub_mean"], 490.0)

    def test_report_builds_expected_simulation_rows(self) -> None:
        report = run_tiny()
        self.assertEqual(report["summary"]["simulation_rows"], 8)
        self.assertEqual(report["summary"]["n_simulations"], 4000)
        self.assertEqual(report["summary"]["seed"], 20260620)
        self.assertEqual(row(report, "srs_population", "activation_naive")["iterations_used"], 4000)

    def test_simple_random_sample_has_small_activation_bias(self) -> None:
        srs = row(run_tiny(), "srs_population", "activation_naive")
        self.assertLess(abs(srs["bias"]), 0.02)
        self.assertFalse(srs["bias_flag"])
        self.assertGreater(srs["variance"], 0)

    def test_coverage_biased_frame_is_stable_but_wrong(self) -> None:
        biased = row(run_tiny(), "coverage_biased_frame", "activation_naive")
        srs = row(run_tiny(), "srs_population", "activation_naive")
        self.assertGreater(biased["bias"], 0.05)
        self.assertTrue(biased["bias_flag"])
        self.assertLess(biased["variance"], srs["variance"])

    def test_weighting_does_not_repair_missing_frame_coverage(self) -> None:
        report = run_tiny()
        weighted = row(report, "unequal_frame_with_nonresponse", "activation_weighted")
        naive = row(report, "unequal_frame_with_nonresponse", "activation_naive")
        self.assertTrue(weighted["bias_flag"])
        self.assertGreater(weighted["bias"], 0.05)
        self.assertGreater(weighted["variance"], naive["variance"])

    def test_revenue_bias_is_reported_in_rub_units(self) -> None:
        revenue = row(run_tiny(), "coverage_biased_frame", "revenue_naive")
        self.assertEqual(revenue["true_parameter"], 490.0)
        self.assertGreater(revenue["bias"], 20.0)
        self.assertTrue(revenue["bias_flag"])

    def test_committed_report_matches_runner_output(self) -> None:
        self.assertEqual(json.loads(BASELINE_REPORT.read_text(encoding="utf-8")), run_tiny())

    def test_committed_csv_contains_same_rows(self) -> None:
        report = run_tiny()
        expected_keys = {
            (item["mechanism_id"], item["estimator_id"])
            for item in report["simulation_rows"]
        }
        with BASELINE_CSV.open(encoding="utf-8", newline="") as source:
            rows = {(row["mechanism_id"], row["estimator_id"]): row for row in csv.DictReader(source)}
        self.assertEqual(set(rows), expected_keys)
        self.assertEqual(rows[("coverage_biased_frame", "activation_naive")]["bias_flag"], "True")

    def test_unknown_estimator_reference_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
            spec["mechanisms"][0]["estimators"].append("not_declared")
            spec_path = Path(directory) / "spec.json"
            spec_path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
            report = SIMULATOR.simulate(DATA / "population_users.csv", DATA / "sampling_frame.csv", spec_path)
            self.assertFalse(report["valid"])
            self.assertFalse(check(report, "srs_population_estimators_resolve")["valid"])

    def test_unknown_parameter_column_blocks_simulation(self) -> None:
        with TemporaryDirectory() as directory:
            spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
            spec["parameters"][0]["metric_column"] = "missing_metric"
            spec_path = Path(directory) / "spec.json"
            spec_path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
            report = SIMULATOR.simulate(DATA / "population_users.csv", DATA / "sampling_frame.csv", spec_path)
            self.assertFalse(report["valid"])
            self.assertFalse(check(report, "activation_rate_metric_column_present")["valid"])

    def test_cli_writes_csv_and_json_report(self) -> None:
        with TemporaryDirectory() as directory:
            output_csv = Path(directory) / "bias_variance.csv"
            output_report = Path(directory) / "bias_variance_report.json"
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--population",
                    DATA / "population_users.csv",
                    "--frame",
                    DATA / "sampling_frame.csv",
                    "--spec",
                    SPEC_PATH,
                    "--output-csv",
                    output_csv,
                    "--output-report",
                    output_report,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(output_csv.exists())
            self.assertTrue(output_report.exists())
            self.assertTrue(json.loads(result.stdout)["valid"])

    def test_code_example_prints_bias_summary(self) -> None:
        result = subprocess.run(
            [sys.executable, CODE],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["valid"])
        self.assertIn("coverage_biased_frame::activation_naive", payload["simulation_rows"])


if __name__ == "__main__":
    unittest.main()
