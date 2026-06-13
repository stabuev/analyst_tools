from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "null_semantics.py"
DATA = ROOT.parent / "data" / "tiny" / "orders.csv"
SPEC = importlib.util.spec_from_file_location("null_semantics", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
NULLS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(NULLS)


class NullSemanticsTest(unittest.TestCase):
    def test_truth_table_has_nine_pairs(self) -> None:
        self.assertEqual(len(NULLS.truth_table()), 9)

    def test_false_and_unknown_is_false(self) -> None:
        row = next(
            item
            for item in NULLS.truth_table()
            if item["left_value"] == "FALSE" and item["right_value"] == "UNKNOWN"
        )
        self.assertEqual(row["and_result"], "FALSE")

    def test_true_or_unknown_is_true(self) -> None:
        row = next(
            item
            for item in NULLS.truth_table()
            if item["left_value"] == "TRUE" and item["right_value"] == "UNKNOWN"
        )
        self.assertEqual(row["or_result"], "TRUE")

    def test_null_equality_is_unknown(self) -> None:
        self.assertIsNone(duckdb.sql("SELECT NULL = NULL").fetchone()[0])

    def test_filter_partition_exposes_unknown_rows(self) -> None:
        counts = NULLS.audit_null_filter(DATA)["counts"]
        self.assertEqual(
            (counts["true_rows"], counts["false_rows"], counts["unknown_rows"]),
            (6, 4, 2),
        )
        self.assertTrue(counts["partition_is_complete"])

    def test_count_column_ignores_null(self) -> None:
        counts = NULLS.audit_null_filter(DATA)["counts"]
        self.assertEqual(counts["total_rows"], 12)
        self.assertEqual(counts["non_null_amount_rows"], 10)

    def test_coalesce_changes_policy_explicitly(self) -> None:
        counts = NULLS.audit_null_filter(DATA)["counts"]
        self.assertEqual(counts["coalesced_count"], 12)

    def test_cli_prints_json(self) -> None:
        result = subprocess.run(
            [sys.executable, ARTIFACT, "--orders", DATA],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["counts"]["unknown_rows"], 2)


if __name__ == "__main__":
    unittest.main()
