from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "streaming_batch_processor.py"
SPEC = importlib.util.spec_from_file_location("streaming_batch_processor", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
PROCESSOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROCESSOR)


class StreamingBatchProcessorTest(unittest.TestCase):
    def test_generation_is_reproducible_and_bounded_by_batch_size(self) -> None:
        with (
            tempfile.TemporaryDirectory() as first_tmp,
            tempfile.TemporaryDirectory() as second_tmp,
        ):
            first = PROCESSOR.generate_order_batches(
                first_tmp, rows=480, batch_size=100, users=64, seed=42
            )
            second = PROCESSOR.generate_order_batches(
                second_tmp, rows=480, batch_size=100, users=64, seed=42
            )
            first_rows = pd.concat([pq.read_table(path).to_pandas() for path in first])
            second_rows = pd.concat([pq.read_table(path).to_pandas() for path in second])
            largest_batch = max(len(pq.read_table(path)) for path in first)
        self.assertTrue(
            first_rows.reset_index(drop=True).equals(second_rows.reset_index(drop=True))
        )
        self.assertEqual(len(first), 5)
        self.assertLessEqual(largest_batch, 100)

    def test_invalid_generation_parameters_raise_lesson_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(PROCESSOR.StreamingBatchError):
                PROCESSOR.generate_order_batches(tmp, rows=100, batch_size=20)
            with self.assertRaises(PROCESSOR.StreamingBatchError):
                PROCESSOR.generate_order_batches(tmp, rows=480, batch_size=10)

    def test_manifest_contains_rows_sizes_and_stable_checksums(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            PROCESSOR.generate_order_batches(tmp, rows=480, batch_size=120, users=64, seed=42)
            first = PROCESSOR.build_input_manifest(tmp)
            second = PROCESSOR.build_input_manifest(tmp)
        self.assertEqual(first, second)
        self.assertEqual(first["total_rows"], 480)
        self.assertTrue(all(len(item["sha256"]) == 64 for item in first["files"]))

    def test_partial_batch_merge_matches_full_pandas_control(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            PROCESSOR.generate_order_batches(data_dir, rows=720, batch_size=120, users=96, seed=42)
            run = PROCESSOR.process_batches(
                data_dir,
                Path(tmp) / "checkpoint.json",
                Path(tmp) / "output.csv",
            )
            observed = run["output"]
            expected = PROCESSOR.run_pandas_control(data_dir)
        self.assertTrue(PROCESSOR.compare_outputs(expected, observed)["matches"])

    def test_resume_skips_completed_files_without_double_counting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            checkpoint = Path(tmp) / "checkpoint.json"
            output = Path(tmp) / "output.csv"
            PROCESSOR.generate_order_batches(data_dir, rows=720, batch_size=120, users=96, seed=42)
            with self.assertRaises(PROCESSOR.SimulatedBatchInterruption):
                PROCESSOR.process_batches(
                    data_dir,
                    checkpoint,
                    output,
                    stop_after_files=2,
                )
            durable = json.loads(checkpoint.read_text(encoding="utf-8"))
            resumed = PROCESSOR.process_batches(data_dir, checkpoint, output)
            expected = PROCESSOR.run_pandas_control(data_dir)
        self.assertEqual(len(durable["completed_files"]), 2)
        self.assertEqual(resumed["skipped_files"], 2)
        self.assertEqual(resumed["rows_processed"], 720)
        self.assertTrue(PROCESSOR.compare_outputs(expected, resumed["output"])["matches"])

    def test_changed_input_is_rejected_after_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            checkpoint = Path(tmp) / "checkpoint.json"
            PROCESSOR.generate_order_batches(data_dir, rows=480, batch_size=120, users=64, seed=42)
            with self.assertRaises(PROCESSOR.SimulatedBatchInterruption):
                PROCESSOR.process_batches(
                    data_dir,
                    checkpoint,
                    Path(tmp) / "output.csv",
                    stop_after_files=1,
                )
            changed_path = sorted(data_dir.glob("batch-*.parquet"))[-1]
            changed = pq.read_table(changed_path).to_pandas()
            changed.loc[0, "gross_revenue_cents"] += 1
            changed.to_parquet(changed_path, index=False)
            with self.assertRaises(PROCESSOR.StreamingBatchError):
                PROCESSOR.process_batches(
                    data_dir,
                    checkpoint,
                    Path(tmp) / "output.csv",
                )

    def test_non_associative_median_counterexample_is_real(self) -> None:
        audit = PROCESSOR.non_associative_counterexample()
        self.assertEqual(audit["median_of_medians"], 2.75)
        self.assertEqual(audit["exact_median"], 3.0)
        self.assertFalse(audit["naive_merge_matches"])

    def test_operation_catalog_distinguishes_bounded_and_global_state(self) -> None:
        catalog = {item["operation"]: item for item in PROCESSOR.operation_classification()}
        self.assertTrue(catalog["sum/count/min/max"]["bounded_state"])
        self.assertTrue(catalog["mean"]["safe_for_chunk_merge"])
        self.assertFalse(catalog["exact median/quantile"]["safe_for_chunk_merge"])
        self.assertFalse(catalog["exact distinct count"]["bounded_state"])

    def test_polars_streaming_matches_pandas_control(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            PROCESSOR.generate_order_batches(
                data_dir, rows=720, batch_size=120, users=96, seed=2026
            )
            expected = PROCESSOR.run_pandas_control(data_dir)
            observed, plan = PROCESSOR.run_polars_streaming(data_dir)
        self.assertTrue(PROCESSOR.compare_outputs(expected, observed)["matches"])
        self.assertIn("PARQUET SCAN", plan.upper())
        self.assertIn("AGGREGATE", plan.upper())

    def test_report_proves_checkpoint_resume_and_correctness(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = PROCESSOR.build_streaming_batch_report(
                rows=720,
                batch_size=120,
                users=96,
                seed=42,
                interrupt_after=2,
                output_dir=tmp,
            )
        self.assertTrue(report["interruption"]["observed"])
        self.assertEqual(report["resume"]["skipped_files"], 2)
        self.assertTrue(report["interpretation"]["safe_to_ship"])
        self.assertTrue(all(report["interpretation"]["checks"].values()))

    def test_checkpoint_is_complete_and_atomic_temp_is_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = PROCESSOR.build_streaming_batch_report(
                rows=480,
                batch_size=120,
                users=64,
                output_dir=tmp,
            )
            checkpoint = json.loads((Path(tmp) / "checkpoint.json").read_text(encoding="utf-8"))
            temporary = Path(tmp) / "checkpoint.json.tmp"
        self.assertEqual(
            set(checkpoint["completed_files"]),
            {item["name"] for item in report["manifest"]["files"]},
        )
        self.assertFalse(temporary.exists())

    def test_output_grain_is_unique(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            PROCESSOR.build_streaming_batch_report(
                rows=480,
                batch_size=120,
                users=64,
                output_dir=tmp,
            )
            output = pd.read_csv(Path(tmp) / "batch-output.csv")
        self.assertFalse(output[PROCESSOR.GROUP_COLUMNS].duplicated().any())

    def test_cli_writes_checkpoint_plan_manifest_and_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "package"
            result = subprocess.run(
                [
                    sys.executable,
                    str(ARTIFACT),
                    "--rows",
                    "480",
                    "--batch-size",
                    "120",
                    "--users",
                    "64",
                    "--interrupt-after",
                    "2",
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
            self.assertEqual(
                stdout_report["scenario"]["scenario_id"],
                file_report["scenario"]["scenario_id"],
            )
            for relative in [
                "checkpoint.json",
                "input-manifest.json",
                "batch-output.csv",
                "pandas-control.csv",
                "polars-streaming-output.csv",
                "streaming-plan.txt",
                "correctness-report.json",
            ]:
                self.assertTrue((output_dir / relative).is_file(), relative)

    def test_cli_invalid_input_has_no_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [
                    sys.executable,
                    str(ARTIFACT),
                    "--rows",
                    "100",
                    "--output-dir",
                    tmp,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 2)
        self.assertIn("streaming batch error", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
