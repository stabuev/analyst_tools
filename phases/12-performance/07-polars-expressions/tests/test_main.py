from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "polars_expression_pipeline.py"
SPEC = importlib.util.spec_from_file_location("polars_expression_pipeline", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
POLARS_PIPELINE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(POLARS_PIPELINE)


class PolarsExpressionPipelineTest(unittest.TestCase):
    def test_generation_is_reproducible_and_has_expected_columns(self) -> None:
        first = POLARS_PIPELINE.generate_customer_revenue_rows(rows=512, users=64, seed=42)
        second = POLARS_PIPELINE.generate_customer_revenue_rows(rows=512, users=64, seed=42)
        self.assertTrue(first.equals(second))
        self.assertEqual(len(first), 512)
        self.assertTrue(set(POLARS_PIPELINE.REQUIRED_COLUMNS).issubset(first.columns))
        self.assertGreater(first["gross_revenue_cents"].sum(), 0)

    def test_invalid_generation_parameters_raise_lesson_error(self) -> None:
        with self.assertRaises(POLARS_PIPELINE.PolarsExpressionError):
            POLARS_PIPELINE.generate_customer_revenue_rows(rows=64, users=16, seed=42)
        with self.assertRaises(POLARS_PIPELINE.PolarsExpressionError):
            POLARS_PIPELINE.generate_customer_revenue_rows(rows=256, users=300, seed=42)

    def test_input_contract_rejects_missing_columns_negative_money_and_unknown_status(self) -> None:
        frame = POLARS_PIPELINE.generate_customer_revenue_rows(rows=512, users=64, seed=42)
        with self.assertRaises(POLARS_PIPELINE.PolarsExpressionError):
            POLARS_PIPELINE.validate_input_frame(frame.drop(columns=["status"]))
        bad_money = frame.copy()
        bad_money.loc[bad_money.index[0], "gross_revenue_cents"] = -1
        with self.assertRaises(POLARS_PIPELINE.PolarsExpressionError):
            POLARS_PIPELINE.validate_input_frame(bad_money)
        bad_status = frame.copy()
        bad_status.loc[bad_status.index[0], "status"] = "chargeback"
        with self.assertRaises(POLARS_PIPELINE.PolarsExpressionError):
            POLARS_PIPELINE.validate_input_frame(bad_status)

    def test_pandas_pipeline_has_unique_output_grain(self) -> None:
        frame = POLARS_PIPELINE.generate_customer_revenue_rows(rows=960, users=120, seed=2026)
        result = POLARS_PIPELINE.run_pandas_pipeline(frame)
        self.assertFalse(result[["week_start", "platform", "region"]].duplicated().any())
        self.assertEqual(list(result.columns), POLARS_PIPELINE.OUTPUT_COLUMNS)
        self.assertTrue((result["week_revenue_rank"] <= 3).all())

    def test_polars_expression_pipeline_matches_pandas_control(self) -> None:
        frame = POLARS_PIPELINE.generate_customer_revenue_rows(rows=960, users=120, seed=2026)
        pandas_result = POLARS_PIPELINE.run_pandas_pipeline(frame)
        polars_result = POLARS_PIPELINE.run_polars_expression_pipeline(frame)
        comparison = POLARS_PIPELINE.compare_outputs(pandas_result, polars_result)
        self.assertTrue(comparison["matches_pandas"])
        self.assertEqual(comparison["diff_preview"], [])
        self.assertGreater(comparison["polars_rows"], 0)

    def test_polars_pipeline_uses_required_expression_contexts(self) -> None:
        audit = POLARS_PIPELINE.audit_artifact_expression_pipeline()
        self.assertTrue(audit["required_contexts_present"])
        self.assertGreaterEqual(audit["contexts"]["select"], 1)
        self.assertGreaterEqual(audit["contexts"]["with_columns"], 3)
        self.assertGreaterEqual(audit["contexts"]["filter"], 2)
        self.assertGreaterEqual(audit["contexts"]["group_by"], 1)
        self.assertFalse(audit["row_wise_python_detected"])

    def test_expression_audit_detects_row_wise_python_patterns(self) -> None:
        bad_source = """
df.with_columns(pl.col("x").map_elements(lambda value: value + 1))
for row in df.iter_rows():
    pass
"""
        audit = POLARS_PIPELINE.audit_expression_source(bad_source)
        self.assertTrue(audit["row_wise_python_detected"])
        names = {item["name"] for item in audit["forbidden_python_udf_usages"]}
        self.assertIn("map_elements", names)
        self.assertIn("iter_rows", names)

    def test_report_interpretation_is_safe_when_equivalence_and_audit_pass(self) -> None:
        report = POLARS_PIPELINE.build_polars_expression_report(
            rows=960,
            users=120,
            seed=42,
        )
        self.assertTrue(report["equivalence"]["matches_pandas"])
        self.assertTrue(report["expression_audit"]["uses_polars_expressions"])
        self.assertTrue(report["interpretation"]["safe_to_ship"])
        self.assertIn("polars_version", report["scenario"])

    def test_schema_report_exposes_input_and_output_types(self) -> None:
        report = POLARS_PIPELINE.build_polars_expression_report(rows=512, users=64, seed=42)
        self.assertIn("gross_revenue_cents", report["schema"]["input"])
        self.assertEqual(report["schema"]["output_columns"], POLARS_PIPELINE.OUTPUT_COLUMNS)
        self.assertIn("net_revenue_cents", report["schema"]["polars_output"])

    def test_health_band_is_expression_derived_not_missing(self) -> None:
        frame = POLARS_PIPELINE.generate_customer_revenue_rows(rows=960, users=120, seed=42)
        result = POLARS_PIPELINE.normalize_output(
            POLARS_PIPELINE.run_polars_expression_pipeline(frame)
        )
        self.assertFalse(result["health_band"].isna().any())
        self.assertTrue(set(result["health_band"]).issubset({"healthy", "watch", "weak"}))

    def test_cli_writes_report_control_output_and_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "package"
            result = subprocess.run(
                [
                    sys.executable,
                    str(ARTIFACT),
                    "--rows",
                    "512",
                    "--users",
                    "64",
                    "--seed",
                    "42",
                    "--output-dir",
                    str(output_dir),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            stdout_report = json.loads(result.stdout)
            file_report = json.loads((output_dir / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(stdout_report["scenario"]["scenario_id"], file_report["scenario"]["scenario_id"])
            self.assertTrue((output_dir / "polars-output.csv").is_file())
            self.assertTrue((output_dir / "pandas-control.csv").is_file())
            self.assertTrue((output_dir / "expression-audit.json").is_file())
            output = pd.read_csv(output_dir / "polars-output.csv")
            control = pd.read_csv(output_dir / "pandas-control.csv")
            self.assertEqual(len(output), len(control))

    def test_cli_invalid_input_has_no_traceback(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ARTIFACT), "--rows", "64"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("polars expression error", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
