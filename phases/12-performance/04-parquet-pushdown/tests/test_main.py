from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "parquet_pushdown_audit.py"
SPEC = importlib.util.spec_from_file_location("parquet_pushdown_audit", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
PUSHDOWN_AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PUSHDOWN_AUDIT)


class ParquetPushdownAuditTest(unittest.TestCase):
    def test_generation_is_reproducible_and_sorted_by_week(self) -> None:
        first = PUSHDOWN_AUDIT.generate_revenue_rows(rows=80, seed=42)
        second = PUSHDOWN_AUDIT.generate_revenue_rows(rows=80, seed=42)
        self.assertTrue(first.equals(second))
        self.assertEqual(first["week_index"].tolist(), sorted(first["week_index"].tolist()))
        self.assertIn("raw_event_json", first.columns)
        self.assertIn("debug_payload", first.columns)

    def test_layout_writes_hive_partitions_and_row_group_statistics(self) -> None:
        frame = PUSHDOWN_AUDIT.generate_revenue_rows(rows=800, seed=42)
        with tempfile.TemporaryDirectory() as tmp:
            dataset_dir = PUSHDOWN_AUDIT.write_parquet_layout(
                frame,
                Path(tmp),
                row_group_size=64,
            )
            layout = PUSHDOWN_AUDIT.inspect_layout(
                dataset_dir,
                target_week="2026-02-02",
                target_week_index=4,
                required_columns=PUSHDOWN_AUDIT.DEFAULT_REQUIRED_COLUMNS,
                row_group_size=64,
            )
        self.assertEqual(layout["partition_columns"], ["week_start"])
        self.assertEqual(len(layout["partitions"]), 8)
        self.assertEqual(layout["partition_pruning"]["candidate_file_count"], 1)
        self.assertGreater(layout["row_group_count"], 8)
        self.assertTrue(layout["row_group_statistics"]["passed"])

    def test_projection_omits_wide_columns_and_reduces_output_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = PUSHDOWN_AUDIT.build_pushdown_audit(output_dir=tmp, rows=1_600, seed=7)
        projection = report["projection"]
        omitted = set(report["layout"]["omitted_physical_columns"])
        self.assertTrue(projection["passed"])
        self.assertLess(projection["projected_column_count"], projection["full_column_count"])
        self.assertLess(projection["pushed_scan_output_bytes"], projection["full_scan_output_bytes"])
        self.assertTrue(set(PUSHDOWN_AUDIT.WIDE_COLUMNS).issubset(omitted))

    def test_predicate_prunes_files_and_row_groups(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = PUSHDOWN_AUDIT.build_pushdown_audit(output_dir=tmp, rows=1_600, seed=9)
        predicate = report["predicate_pushdown"]
        self.assertTrue(predicate["partition_pruning"]["passed"])
        self.assertTrue(predicate["row_group_statistics"]["passed"])
        self.assertLess(
            predicate["partition_pruning"]["candidate_file_count"],
            report["layout"]["file_count"],
        )
        self.assertLess(
            predicate["row_group_statistics"]["candidate_row_group_count"],
            report["layout"]["row_group_count"],
        )

    def test_duckdb_plan_confirms_parquet_scan_and_result_matches_control(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = PUSHDOWN_AUDIT.build_pushdown_audit(output_dir=tmp, rows=1_600, seed=11)
        checks = report["duckdb_plan"]["checks"]
        self.assertTrue(checks["parquet_scan_present"])
        self.assertTrue(checks["row_group_filter_visible"])
        self.assertTrue(report["result_contract"]["passed"])
        self.assertTrue(report["interpretation"]["safe_to_ship"])

    def test_unknown_target_week_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(PUSHDOWN_AUDIT.PushdownAuditError, "target_week"):
                PUSHDOWN_AUDIT.build_pushdown_audit(
                    output_dir=tmp,
                    rows=800,
                    target_week="2027-01-01",
                )

    def test_required_column_must_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(PUSHDOWN_AUDIT.PushdownAuditError, "required columns"):
                PUSHDOWN_AUDIT.build_pushdown_audit(
                    output_dir=tmp,
                    rows=800,
                    required_columns=["platform", "missing_metric"],
                )

    def test_report_does_not_turn_one_run_into_speedup_claim(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = PUSHDOWN_AUDIT.build_pushdown_audit(output_dir=tmp, rows=1_600, seed=12)
        notes = " ".join(report["interpretation"]["notes"]).lower()
        self.assertIn("not a statistically stable speedup claim", notes)
        self.assertIn("scan shapes", notes)

    def test_cli_writes_reusable_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "audit"
            result = subprocess.run(
                [
                    sys.executable,
                    str(ARTIFACT),
                    "--rows",
                    "1200",
                    "--seed",
                    "42",
                    "--row-group-size",
                    "64",
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
            self.assertEqual(stdout_report["scenario"], file_report["scenario"])
            self.assertTrue((output_dir / "parquet-layout.json").exists())
            self.assertTrue((output_dir / "query-plan.txt").exists())
            self.assertTrue(list((output_dir / "dataset").rglob("*.parquet")))

    def test_cli_invalid_input_has_no_traceback(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ARTIFACT), "--rows", "0"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("pushdown audit error", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
