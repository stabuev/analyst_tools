from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "reshape_contract.py"
DATA = ROOT.parent / "data" / "tiny" / "orders.csv"
SPEC = importlib.util.spec_from_file_location("reshape_contract", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
RESHAPE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RESHAPE)


class ReshapeContractTest(unittest.TestCase):
    def test_melt_multiplies_rows_by_metric_count(self) -> None:
        frame = pd.DataFrame({"id": ["A", "B"], "x": [1, 2], "y": [3, 4]})
        long = RESHAPE.to_long(frame, id_vars=["id"], value_vars=["x", "y"])
        self.assertEqual(len(long), 4)

    def test_melt_preserves_identifier(self) -> None:
        frame = pd.DataFrame({"id": ["A"], "x": [1], "y": [2]})
        long = RESHAPE.to_long(frame, id_vars=["id"], value_vars=["x", "y"])
        self.assertEqual(long["id"].tolist(), ["A", "A"])

    def test_null_identifier_is_rejected(self) -> None:
        frame = pd.DataFrame({"id": [None], "x": [1]})
        with self.assertRaisesRegex(RESHAPE.ReshapeContractError, "null"):
            RESHAPE.to_long(frame, id_vars=["id"], value_vars=["x"])

    def test_unique_cells_can_be_pivoted(self) -> None:
        long = pd.DataFrame({"id": ["A", "A"], "metric": ["x", "y"], "value": [1, 2]})
        wide = RESHAPE.pivot_unique(
            long,
            index=["id"],
            columns="metric",
            values="value",
        )
        self.assertEqual(wide.loc[0, "x"], 1)

    def test_ambiguous_pivot_is_rejected(self) -> None:
        long = pd.DataFrame({"id": ["A", "A"], "metric": ["x", "x"], "value": [1, 2]})
        with self.assertRaisesRegex(RESHAPE.ReshapeContractError, "not unique"):
            RESHAPE.pivot_unique(
                long,
                index=["id"],
                columns="metric",
                values="value",
            )

    def test_status_matrix_has_one_row_per_user(self) -> None:
        _, wide = RESHAPE.build_status_matrix(pd.read_csv(DATA))
        self.assertTrue(wide["user_id"].is_unique)

    def test_status_matrix_normalizes_status_values(self) -> None:
        long, _ = RESHAPE.build_status_matrix(pd.read_csv(DATA))
        self.assertIn("paid", long["status"].tolist())
        self.assertNotIn(" paid ", long["status"].tolist())

    def test_cli_reports_both_shapes(self) -> None:
        result = subprocess.run(
            [sys.executable, ARTIFACT, DATA],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertGreater(report["long_rows"], report["wide_rows"])


if __name__ == "__main__":
    unittest.main()
