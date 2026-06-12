from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "dataframe_inspector.py"
DATA = ROOT.parent / "data" / "tiny" / "orders.csv"
SPEC = importlib.util.spec_from_file_location("dataframe_inspector", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
INSPECTOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INSPECTOR)


class DataFrameInspectorTest(unittest.TestCase):
    def test_report_exposes_axes_shape_and_index(self) -> None:
        frame = pd.DataFrame({"order_id": ["A", "B"], "amount": [10, 20]})
        report = INSPECTOR.inspect_dataframe(frame, ["order_id"])

        self.assertEqual(report["shape"], [2, 2])
        self.assertEqual(report["axes"]["columns"], ["order_id", "amount"])
        self.assertEqual(report["index"]["type"], "RangeIndex")

    def test_unique_business_key_passes_grain_contract(self) -> None:
        frame = pd.DataFrame({"order_id": ["A", "B"]})
        report = INSPECTOR.inspect_dataframe(frame, ["order_id"])
        self.assertTrue(report["grain"]["valid"])

    def test_duplicate_business_key_is_visible(self) -> None:
        frame = pd.DataFrame({"order_id": ["A", "A"]})
        report = INSPECTOR.inspect_dataframe(frame, ["order_id"])
        self.assertFalse(report["grain"]["valid"])
        self.assertEqual(report["grain"]["duplicate_key_rows"], 2)

    def test_null_business_key_is_invalid(self) -> None:
        frame = pd.DataFrame({"order_id": ["A", None]})
        report = INSPECTOR.inspect_dataframe(frame, ["order_id"])
        self.assertFalse(report["grain"]["valid"])
        self.assertEqual(report["grain"]["null_key_rows"], 1)

    def test_missing_key_column_is_rejected(self) -> None:
        with self.assertRaisesRegex(INSPECTOR.TableContractError, "missing key"):
            INSPECTOR.inspect_dataframe(pd.DataFrame({"id": [1]}), ["order_id"])

    def test_series_alignment_uses_labels(self) -> None:
        example = INSPECTOR.alignment_example()
        self.assertEqual(example["index"], ["order-a", "order-b", "order-c"])
        self.assertEqual(example["values"], [None, 190.0, None])

    def test_copy_on_write_keeps_source_unchanged(self) -> None:
        frame = pd.DataFrame({"amount": [10, 20]})
        subset = frame[["amount"]]
        subset.loc[0, "amount"] = 999
        self.assertEqual(frame.loc[0, "amount"], 10)

    def test_cli_prints_json_report(self) -> None:
        result = subprocess.run(
            [sys.executable, ARTIFACT, DATA, "--keys", "order_id"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["shape"], [7, 6])
        self.assertTrue(report["grain"]["valid"])


if __name__ == "__main__":
    unittest.main()
