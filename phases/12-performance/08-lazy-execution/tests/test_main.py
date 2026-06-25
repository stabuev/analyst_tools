from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import polars as pl


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "polars_lazy_plan_audit.py"
SPEC = importlib.util.spec_from_file_location("polars_lazy_plan_audit", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
LAZY_AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LAZY_AUDIT)


class PolarsLazyPlanAuditTest(unittest.TestCase):
    def test_generation_is_reproducible_and_contains_unused_wide_columns(self) -> None:
        first = LAZY_AUDIT.generate_customer_revenue_rows(rows=512, users=64, seed=42)
        second = LAZY_AUDIT.generate_customer_revenue_rows(rows=512, users=64, seed=42)
        self.assertTrue(first.equals(second))
        self.assertIn("debug_payload", first.columns)
        self.assertIn("raw_event_json", first.columns)
        self.assertEqual(len(first), 512)

    def test_invalid_generation_parameters_raise_lesson_error(self) -> None:
        with self.assertRaises(LAZY_AUDIT.PolarsLazyPlanError):
            LAZY_AUDIT.generate_customer_revenue_rows(rows=128, users=64, seed=42)
        with self.assertRaises(LAZY_AUDIT.PolarsLazyPlanError):
            LAZY_AUDIT.generate_customer_revenue_rows(rows=512, users=800, seed=42)

    def test_write_parquet_input_creates_scan_readable_file(self) -> None:
        frame = LAZY_AUDIT.generate_customer_revenue_rows(rows=512, users=64, seed=42)
        with tempfile.TemporaryDirectory() as tmp:
            path = LAZY_AUDIT.write_parquet_input(frame, tmp, row_group_size=128)
            self.assertTrue(path.is_file())
            scanned = pl.scan_parquet(path).select(pl.len()).collect().item()
        self.assertEqual(scanned, 512)

    def test_lazy_pipeline_collects_to_same_result_as_pandas_control(self) -> None:
        frame = LAZY_AUDIT.generate_customer_revenue_rows(rows=960, users=120, seed=2026)
        with tempfile.TemporaryDirectory() as tmp:
            path = LAZY_AUDIT.write_parquet_input(frame, tmp, row_group_size=128)
            lazy_frame = LAZY_AUDIT.build_lazy_scan_pipeline(path)
            self.assertIsInstance(lazy_frame, pl.LazyFrame)
            comparison = LAZY_AUDIT.compare_outputs(
                LAZY_AUDIT.run_pandas_control(frame),
                lazy_frame.collect(),
            )
        self.assertTrue(comparison["matches_pandas"])
        self.assertEqual(comparison["diff_preview"], [])
        self.assertGreater(comparison["polars_rows"], 0)

    def test_unoptimized_and_optimized_plans_show_projection_pushdown(self) -> None:
        frame = LAZY_AUDIT.generate_customer_revenue_rows(rows=960, users=120, seed=42)
        with tempfile.TemporaryDirectory() as tmp:
            path = LAZY_AUDIT.write_parquet_input(frame, tmp, row_group_size=128)
            plans = LAZY_AUDIT.explain_lazy_frame(LAZY_AUDIT.build_lazy_scan_pipeline(path))
        audit = LAZY_AUDIT.audit_plans(plans)
        self.assertTrue(audit["unoptimized_reads_all_columns"])
        self.assertTrue(audit["optimized_projection_pushdown"]["reduced"])
        self.assertLess(
            audit["optimized_projection_pushdown"]["selected_columns"],
            audit["optimized_projection_pushdown"]["total_columns"],
        )
        self.assertIn("PROJECT */", plans["unoptimized"])
        self.assertIn("PROJECT", plans["optimized"])

    def test_optimized_plan_pushes_predicate_to_scan(self) -> None:
        frame = LAZY_AUDIT.generate_customer_revenue_rows(rows=960, users=120, seed=42)
        with tempfile.TemporaryDirectory() as tmp:
            path = LAZY_AUDIT.write_parquet_input(frame, tmp, row_group_size=128)
            plans = LAZY_AUDIT.explain_lazy_frame(LAZY_AUDIT.build_lazy_scan_pipeline(path))
        audit = LAZY_AUDIT.audit_plans(plans)
        self.assertTrue(audit["has_parquet_scan"])
        self.assertTrue(audit["optimized_has_selection_at_scan"])
        self.assertTrue(audit["selection_mentions_expected_filters"])
        self.assertIn("SELECTION:", plans["optimized"])

    def test_plan_audit_keeps_aggregate_rank_and_sort_visible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = LAZY_AUDIT.build_polars_lazy_plan_audit(
                rows=960,
                users=120,
                seed=42,
                output_dir=tmp,
            )
        audit = report["plan_audit"]
        self.assertTrue(audit["has_aggregate"])
        self.assertTrue(audit["has_rank"])
        self.assertTrue(audit["has_final_sort"])

    def test_source_audit_accepts_lazy_scan_pipeline(self) -> None:
        audit = LAZY_AUDIT.audit_lazy_pipeline_source()
        self.assertTrue(audit["safe_lazy_source"])
        self.assertFalse(audit["early_materialization_detected"])
        self.assertFalse(audit["python_udf_detected"])

    def test_source_audit_detects_early_collect_and_udf_patterns(self) -> None:
        bad_source = """
lazy = pl.scan_parquet(path)
frame = lazy.collect()
frame.with_columns(pl.col("x").map_elements(lambda value: value + 1))
"""
        audit = LAZY_AUDIT.audit_source_text(bad_source)
        self.assertFalse(audit["safe_lazy_source"])
        self.assertTrue(audit["early_materialization_detected"])
        self.assertTrue(audit["python_udf_detected"])
        names = {item["name"] for item in audit["forbidden_patterns"]}
        self.assertIn("early_collect", names)
        self.assertIn("map_elements", names)

    def test_report_interpretation_is_safe_when_plan_and_equivalence_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = LAZY_AUDIT.build_polars_lazy_plan_audit(
                rows=960,
                users=120,
                seed=2026,
                output_dir=tmp,
            )
        self.assertTrue(report["equivalence"]["matches_pandas"])
        self.assertTrue(report["interpretation"]["safe_to_ship"])
        self.assertTrue(all(report["interpretation"]["checks"].values()))

    def test_output_grain_is_unique(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = LAZY_AUDIT.build_polars_lazy_plan_audit(
                rows=960,
                users=120,
                seed=42,
                output_dir=tmp,
            )
            output = pl.read_csv(Path(tmp) / "polars-lazy-output.csv")
        self.assertTrue(report["interpretation"]["checks"]["output_grain_unique"])
        self.assertEqual(output.select(["week_start", "platform", "region"]).n_unique(), output.height)

    def test_cli_writes_plans_report_outputs_and_parquet(self) -> None:
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
            self.assertTrue((output_dir / "data" / "orders.parquet").is_file())
            self.assertTrue((output_dir / "optimized-plan.txt").is_file())
            self.assertTrue((output_dir / "unoptimized-plan.txt").is_file())
            self.assertTrue((output_dir / "plan-audit.json").is_file())
            self.assertTrue((output_dir / "polars-lazy-output.csv").is_file())

    def test_cli_invalid_input_has_no_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [
                    sys.executable,
                    str(ARTIFACT),
                    "--rows",
                    "128",
                    "--output-dir",
                    tmp,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 2)
        self.assertIn("polars lazy plan error", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
