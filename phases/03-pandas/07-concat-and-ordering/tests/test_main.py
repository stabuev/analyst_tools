from __future__ import annotations

import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "batch_concat.py"
EXAMPLE = ROOT / "code" / "main.py"
SPEC = importlib.util.spec_from_file_location("batch_concat", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
CONCAT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONCAT)


def typed_orders(
    order_ids: list[str],
    *,
    sequences: list[int] | None = None,
) -> pd.DataFrame:
    size = len(order_ids)
    sequence_values = sequences if sequences is not None else list(range(size))
    return pd.DataFrame(
        {
            "order_id": order_ids,
            "status": ["paid"] * size,
            "loaded_sequence": sequence_values,
            "amount": [100.0] * size,
        }
    ).astype(
        {
            "order_id": "string",
            "status": "string",
            "loaded_sequence": "Int64",
            "amount": "Float64",
        }
    )


class ConcatBatchesTest(unittest.TestCase):
    def test_appends_rows_and_records_provenance(self) -> None:
        result, audit = CONCAT.concat_batches(
            {
                "part-b": typed_orders(["O3"]),
                "part-a": typed_orders(["O1", "O2"]),
            },
            key=["order_id"],
        )

        self.assertEqual(result["order_id"].tolist(), ["O1", "O2", "O3"])
        self.assertEqual(result["source_batch"].tolist(), ["part-a", "part-a", "part-b"])
        self.assertEqual(audit["input_rows"], 3)
        self.assertEqual(audit["result_rows"], 3)
        self.assertTrue(audit["row_reconciliation_passed"])

    def test_mapping_order_does_not_change_business_result(self) -> None:
        first = typed_orders(["O2"])
        second = typed_orders(["O1"])
        result_ab, _ = CONCAT.concat_batches(
            {"b": first, "a": second}, key=["order_id"]
        )
        result_ba, _ = CONCAT.concat_batches(
            {"a": second, "b": first}, key=["order_id"]
        )

        pd.testing.assert_frame_equal(result_ab, result_ba)

    def test_non_unique_leading_sort_gets_key_tie_breaker(self) -> None:
        result, audit = CONCAT.concat_batches(
            {
                "batch": typed_orders(
                    ["O3", "O1", "O2"], sequences=[2, 1, 1]
                )
            },
            key=["order_id"],
            sort_by=["loaded_sequence"],
        )

        self.assertEqual(result["order_id"].tolist(), ["O1", "O2", "O3"])
        self.assertEqual(
            audit["effective_sort_columns"],
            ["loaded_sequence", "order_id"],
        )

    def test_column_order_is_normalized_to_first_batch(self) -> None:
        first = typed_orders(["O1"])
        second = typed_orders(["O2"])[list(reversed(first.columns))]
        result, audit = CONCAT.concat_batches(
            {"first": first, "second": second}, key=["order_id"]
        )

        self.assertEqual(
            result.columns.tolist(),
            [*first.columns.tolist(), "source_batch"],
        )
        self.assertEqual(audit["column_order_normalized_batches"], ["second"])

    def test_missing_or_extra_schema_column_is_rejected(self) -> None:
        source = typed_orders(["O1"])
        cases = {
            "missing": typed_orders(["O2"]).drop(columns="status"),
            "extra": typed_orders(["O2"]).assign(channel="web"),
        }
        for label, broken in cases.items():
            with (
                self.subTest(label=label),
                self.assertRaisesRegex(CONCAT.ConcatContractError, "schema differs"),
            ):
                CONCAT.concat_batches(
                    {"source": source, label: broken}, key=["order_id"]
                )

    def test_dtype_drift_is_rejected_before_concat(self) -> None:
        broken = typed_orders(["O2"]).astype({"amount": "float64"})
        with self.assertRaisesRegex(CONCAT.ConcatContractError, "dtypes differ"):
            CONCAT.concat_batches(
                {"good": typed_orders(["O1"]), "broken": broken},
                key=["order_id"],
            )

    def test_dtype_metadata_drift_is_rejected_before_concat(self) -> None:
        first = typed_orders(["O1"])
        second = typed_orders(["O2"])
        first["status"] = first["status"].astype(
            pd.CategoricalDtype(["paid", "refunded"])
        )
        second["status"] = second["status"].astype(
            pd.CategoricalDtype(["paid", "pending"])
        )

        with self.assertRaisesRegex(CONCAT.ConcatContractError, "dtypes differ"):
            CONCAT.concat_batches(
                {"first": first, "second": second},
                key=["order_id"],
            )

    def test_overlapping_key_across_batches_is_rejected_with_sources(self) -> None:
        with self.assertRaisesRegex(
            CONCAT.ConcatContractError,
            "business key overlaps.*first.*second",
        ):
            CONCAT.concat_batches(
                {
                    "first": typed_orders(["O1"]),
                    "second": typed_orders(["O1"]),
                },
                key=["order_id"],
            )

    def test_duplicate_key_inside_one_batch_is_rejected(self) -> None:
        with self.assertRaisesRegex(CONCAT.ConcatContractError, "business key overlaps"):
            CONCAT.concat_batches(
                {"batch": typed_orders(["O1", "O1"])}, key=["order_id"]
            )

    def test_missing_or_blank_business_key_is_rejected(self) -> None:
        for value in (pd.NA, "  "):
            with self.subTest(value=value):
                broken = typed_orders(["O1"])
                broken.loc[0, "order_id"] = value
                with self.assertRaisesRegex(
                    CONCAT.ConcatContractError,
                    "non-missing and non-blank",
                ):
                    CONCAT.concat_batches({"broken": broken}, key=["order_id"])

    def test_missing_key_or_sort_column_is_rejected(self) -> None:
        frame = typed_orders(["O1"])
        with self.assertRaisesRegex(CONCAT.ConcatContractError, "key columns"):
            CONCAT.concat_batches({"batch": frame}, key=["user_id"])
        with self.assertRaisesRegex(CONCAT.ConcatContractError, "sort columns"):
            CONCAT.concat_batches(
                {"batch": frame}, key=["order_id"], sort_by=["not_here"]
            )

    def test_source_column_collision_is_rejected(self) -> None:
        frame = typed_orders(["O1"]).assign(source_batch="legacy")
        with self.assertRaisesRegex(CONCAT.ConcatContractError, "already exists"):
            CONCAT.concat_batches({"batch": frame}, key=["order_id"])

    def test_invalid_mapping_names_and_arguments_are_rejected(self) -> None:
        frame = typed_orders(["O1"])
        with self.assertRaisesRegex(CONCAT.ConcatContractError, "non-empty mapping"):
            CONCAT.concat_batches({}, key=["order_id"])
        with self.assertRaisesRegex(CONCAT.ConcatContractError, "batch names"):
            CONCAT.concat_batches({"  ": frame}, key=["order_id"])
        with self.assertRaisesRegex(CONCAT.ConcatContractError, "sequence"):
            CONCAT.concat_batches({"batch": frame}, key="order_id")

    def test_duplicate_column_labels_are_rejected(self) -> None:
        frame = typed_orders(["O1"])
        frame.columns = ["order_id", "status", "amount", "amount"]
        with self.assertRaisesRegex(CONCAT.ConcatContractError, "column labels"):
            CONCAT.concat_batches({"batch": frame}, key=["order_id"])

    def test_typed_empty_batches_keep_schema_and_dtypes(self) -> None:
        empty = typed_orders(["O1"]).iloc[:0]
        result, audit = CONCAT.concat_batches(
            {"empty-a": empty, "empty-b": empty.copy()}, key=["order_id"]
        )

        self.assertTrue(result.empty)
        self.assertEqual(str(result["amount"].dtype), "Float64")
        self.assertEqual(str(result["source_batch"].dtype), "string")
        self.assertEqual(audit["result_rows"], 0)

    def test_inputs_are_not_modified(self) -> None:
        first = typed_orders(["O1"])
        second = typed_orders(["O2"])
        first_before = first.copy(deep=True)
        second_before = second.copy(deep=True)

        CONCAT.concat_batches({"first": first, "second": second}, key=["order_id"])

        pd.testing.assert_frame_equal(first, first_before)
        pd.testing.assert_frame_equal(second, second_before)

    def test_example_runs_without_cli_arguments(self) -> None:
        result = subprocess.run(
            [sys.executable, EXAMPLE],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("AUDIT", result.stdout)
        self.assertIn("O1001", result.stdout)
        self.assertIn("part-02", result.stdout)


if __name__ == "__main__":
    unittest.main()
