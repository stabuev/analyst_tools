from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "arrow_memory_inspector.py"
SPEC = importlib.util.spec_from_file_location("arrow_memory_inspector", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
ARROW_MEMORY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ARROW_MEMORY)


class ArrowMemoryInspectorTest(unittest.TestCase):
    def test_table_generation_is_reproducible_and_chunked(self) -> None:
        first = ARROW_MEMORY.build_customer_revenue_arrow_table(rows=32, chunk_size=8, seed=42)
        second = ARROW_MEMORY.build_customer_revenue_arrow_table(rows=32, chunk_size=8, seed=42)
        self.assertTrue(first.equals(second))
        self.assertEqual(first.num_rows, 32)
        self.assertEqual(first["net_revenue_cents"].num_chunks, 4)
        self.assertIn("platform", first.column_names)

    def test_numeric_without_nulls_has_values_buffer_but_no_validity_bitmap(self) -> None:
        table = ARROW_MEMORY.build_customer_revenue_arrow_table(rows=32, chunk_size=8, seed=42)
        detail = ARROW_MEMORY.inspect_chunked_array("net_revenue_cents", table["net_revenue_cents"])
        first_chunk = detail["chunks"][0]
        self.assertFalse(first_chunk["buffers"][0]["present"])
        self.assertEqual(first_chunk["buffers"][1]["role"], "values")
        self.assertGreater(first_chunk["buffers"][1]["size_bytes"], 0)

    def test_nullable_numeric_exposes_validity_bitmap(self) -> None:
        table = ARROW_MEMORY.build_customer_revenue_arrow_table(rows=32, chunk_size=8, seed=42)
        detail = ARROW_MEMORY.inspect_chunked_array("support_ticket_count", table["support_ticket_count"])
        self.assertGreater(detail["null_count"], 0)
        self.assertTrue(detail["chunks"][0]["buffers"][0]["present"])
        self.assertEqual(detail["chunks"][0]["buffers"][0]["role"], "validity_bitmap")

    def test_string_column_exposes_offsets_and_values_buffers(self) -> None:
        table = ARROW_MEMORY.build_customer_revenue_arrow_table(rows=32, chunk_size=8, seed=42)
        detail = ARROW_MEMORY.inspect_chunked_array("support_notes", table["support_notes"])
        chunk_with_values = next(chunk for chunk in detail["chunks"] if chunk["buffers"][2]["size_bytes"] > 0)
        self.assertEqual([buffer["role"] for buffer in chunk_with_values["buffers"]], ["validity_bitmap", "offsets", "values"])
        self.assertTrue(chunk_with_values["buffers"][1]["present"])
        self.assertTrue(chunk_with_values["buffers"][2]["present"])

    def test_dictionary_column_reports_indices_and_dictionary_values(self) -> None:
        table = ARROW_MEMORY.build_customer_revenue_arrow_table(rows=32, chunk_size=8, seed=42)
        detail = ARROW_MEMORY.inspect_chunked_array("platform", table["platform"])
        self.assertIn("dictionary_values_per_chunk", detail)
        self.assertIn("dictionary", detail["chunks"][0])
        self.assertEqual(detail["chunks"][0]["buffers"][1]["role"], "indices")
        self.assertIn("web", detail["chunks"][0]["dictionary"]["values"])

    def test_slice_reuses_source_buffers_with_nonzero_offset(self) -> None:
        table = ARROW_MEMORY.build_customer_revenue_arrow_table(rows=32, chunk_size=8, seed=42)
        audit = ARROW_MEMORY.build_copy_audit(table)
        self.assertTrue(audit["slice_buffer_reuse"]["shares_buffers"])
        self.assertGreater(audit["slice_buffer_reuse"]["slice_offset"], 0)

    def test_zero_copy_numpy_succeeds_only_for_primitive_no_null_chunk(self) -> None:
        table = ARROW_MEMORY.build_customer_revenue_arrow_table(rows=32, chunk_size=8, seed=42)
        audit = ARROW_MEMORY.build_copy_audit(table)
        self.assertTrue(audit["zero_copy_numpy"]["shares_arrow_values_buffer"])
        self.assertFalse(audit["nullable_numpy_zero_copy"]["succeeded"])
        self.assertFalse(audit["chunked_numpy_zero_copy"]["succeeded"])

    def test_table_to_pandas_needs_split_blocks_for_zero_copy_dataframe_boundary(self) -> None:
        table = ARROW_MEMORY.build_customer_revenue_arrow_table(rows=32, chunk_size=8, seed=42)
        audit = ARROW_MEMORY.build_copy_audit(table)
        self.assertFalse(audit["table_to_pandas_zero_copy"]["succeeded"])
        self.assertFalse(audit["chunked_table_to_pandas_split_blocks"]["succeeded"])
        self.assertTrue(audit["single_chunk_table_to_pandas_split_blocks"]["succeeded"])
        self.assertEqual(audit["single_chunk_table_to_pandas_split_blocks"]["shape"], [32, 2])

    def test_combine_chunks_and_dictionary_unify_are_reported_as_rewrites(self) -> None:
        table = ARROW_MEMORY.build_customer_revenue_arrow_table(rows=32, chunk_size=8, seed=42)
        audit = ARROW_MEMORY.build_copy_audit(table)
        self.assertTrue(audit["combine_chunks"]["requires_copy"])
        self.assertTrue(audit["dictionary_unify"]["requires_some_rewrite"])

    def test_report_interpretation_is_safe_when_all_memory_findings_pass(self) -> None:
        report = ARROW_MEMORY.build_arrow_memory_report(rows=48, chunk_size=16, seed=2026)
        self.assertTrue(all(report["buffer_findings"].values()))
        self.assertTrue(report["interpretation"]["safe_to_ship"])
        notes = " ".join(report["interpretation"]["notes"]).lower()
        self.assertIn("zero-copy is a boundary property", notes)

    def test_cli_writes_json_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "arrow-memory.json"
            result = subprocess.run(
                [
                    sys.executable,
                    str(ARTIFACT),
                    "--rows",
                    "32",
                    "--chunk-size",
                    "8",
                    "--seed",
                    "42",
                    "--output",
                    str(output),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            stdout_report = json.loads(result.stdout)
            file_report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(stdout_report["scenario"], file_report["scenario"])
            self.assertEqual(file_report["scenario"]["scenario_id"], "arrow-memory-copy-audit")

    def test_cli_invalid_input_has_no_traceback(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ARTIFACT), "--rows", "4"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("arrow memory error", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
