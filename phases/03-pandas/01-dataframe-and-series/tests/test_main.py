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
ARTIFACT = ROOT / "outputs" / "dataframe_inspector.py"
EXAMPLE = ROOT / "code" / "main.py"
DATA = ROOT.parent / "data" / "tiny" / "orders.csv"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


INSPECTOR = load_module("dataframe_inspector", ARTIFACT)
LESSON = load_module("dataframe_series_lesson", EXAMPLE)


class DataFrameInspectorTest(unittest.TestCase):
    def test_report_exposes_table_axes_and_limited_index_preview(self) -> None:
        frame = pd.DataFrame(
            {
                "order_id": [f"O{index}" for index in range(7)],
                "amount": list(range(7)),
            }
        )
        report = INSPECTOR.inspect_dataframe(frame, ["order_id"])

        self.assertEqual(report["table"]["shape"], [7, 2])
        self.assertEqual(report["table"]["columns"], ["order_id", "amount"])
        self.assertEqual(report["table"]["index"]["type"], "RangeIndex")
        self.assertEqual(report["table"]["index"]["preview"], [0, 1, 2, 3, 4])
        self.assertNotIn("alignment_example", report)
        self.assertNotIn("copy_on_write", report)

    def test_selected_column_is_series_with_dataframe_index(self) -> None:
        frame = pd.DataFrame({"order_id": ["A", "B"], "amount": [10, 20]})
        relationship = LESSON.dataframe_series_relationship(frame, "amount")

        self.assertEqual(relationship["frame_type"], "DataFrame")
        self.assertEqual(relationship["series_type"], "Series")
        self.assertEqual(relationship["series_name"], "amount")
        self.assertTrue(relationship["same_row_index"])

    def test_series_alignment_preserves_union_of_labels(self) -> None:
        result = LESSON.build_alignment_example()

        self.assertEqual(result.index.tolist(), ["order-a", "order-b", "order-c"])
        values = result.tolist()
        self.assertTrue(pd.isna(values[0]))
        self.assertEqual(values[1], 190)
        self.assertTrue(pd.isna(values[2]))

    def test_unique_business_key_passes_declared_grain_contract(self) -> None:
        frame = pd.DataFrame({"order_id": ["A", "B"]})
        report = INSPECTOR.inspect_dataframe(frame, ["order_id"])

        self.assertTrue(report["declared_grain"]["valid"])

    def test_unique_range_index_does_not_hide_duplicate_business_key(self) -> None:
        frame = pd.DataFrame({"order_id": ["A", "A"]})
        report = INSPECTOR.inspect_dataframe(frame, ["order_id"])

        self.assertTrue(report["table"]["index"]["is_unique"])
        self.assertFalse(report["declared_grain"]["valid"])
        self.assertEqual(report["declared_grain"]["duplicate_key_rows"], 2)

    def test_null_business_key_is_invalid(self) -> None:
        frame = pd.DataFrame({"order_id": ["A", None]})
        report = INSPECTOR.inspect_dataframe(frame, ["order_id"])

        self.assertFalse(report["declared_grain"]["valid"])
        self.assertEqual(report["declared_grain"]["null_key_rows"], 1)
        self.assertEqual(report["declared_grain"]["missing_key_rows"], 1)

    def test_blank_business_keys_are_invalid(self) -> None:
        frame = pd.DataFrame({"order_id": ["A", "", "   "]})
        report = INSPECTOR.inspect_dataframe(frame, ["order_id"])

        self.assertFalse(report["declared_grain"]["valid"])
        self.assertEqual(report["declared_grain"]["null_key_rows"], 0)
        self.assertEqual(report["declared_grain"]["blank_key_rows"], 2)
        self.assertEqual(report["declared_grain"]["missing_key_rows"], 2)

    def test_composite_key_is_checked_as_one_contract(self) -> None:
        valid = pd.DataFrame(
            {
                "order_id": ["A", "A"],
                "product_id": ["P1", "P2"],
            }
        )
        duplicate_pair = pd.DataFrame(
            {
                "order_id": ["A", "A", "A"],
                "product_id": ["P1", "P2", "P1"],
            }
        )

        valid_report = INSPECTOR.inspect_dataframe(valid, ["order_id", "product_id"])
        invalid_report = INSPECTOR.inspect_dataframe(
            duplicate_pair,
            ["order_id", "product_id"],
        )

        self.assertTrue(valid_report["declared_grain"]["valid"])
        self.assertFalse(invalid_report["declared_grain"]["valid"])
        self.assertEqual(invalid_report["declared_grain"]["duplicate_key_rows"], 2)

    def test_blank_or_null_part_invalidates_composite_key(self) -> None:
        frame = pd.DataFrame(
            {
                "order_id": ["A", "B", "C"],
                "product_id": ["P1", "  ", None],
            }
        )
        report = INSPECTOR.inspect_dataframe(frame, ["order_id", "product_id"])

        self.assertFalse(report["declared_grain"]["valid"])
        self.assertEqual(report["declared_grain"]["blank_key_rows"], 1)
        self.assertEqual(report["declared_grain"]["null_key_rows"], 1)
        self.assertEqual(report["declared_grain"]["missing_key_rows"], 2)

    def test_missing_or_empty_key_contract_is_rejected(self) -> None:
        frame = pd.DataFrame({"id": [1]})

        with self.assertRaisesRegex(INSPECTOR.TableContractError, "at least one"):
            INSPECTOR.inspect_dataframe(frame, [])
        with self.assertRaisesRegex(INSPECTOR.TableContractError, "missing key"):
            INSPECTOR.inspect_dataframe(frame, ["order_id"])

    def test_cli_returns_zero_and_json_for_valid_contract(self) -> None:
        result = subprocess.run(
            [sys.executable, ARTIFACT, DATA, "--keys", "order_id"],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["table"]["shape"], [7, 6])
        self.assertTrue(report["declared_grain"]["valid"])

    def test_cli_returns_one_and_keeps_failure_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "duplicate_orders.csv"
            source.write_text("order_id,amount\nA,10\nA,20\n", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, ARTIFACT, source, "--keys", "order_id"],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(result.returncode, 1, result.stderr)
        report = json.loads(result.stdout)
        self.assertFalse(report["declared_grain"]["valid"])
        self.assertEqual(report["declared_grain"]["duplicate_key_rows"], 2)


if __name__ == "__main__":
    unittest.main()
