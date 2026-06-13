from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "arrow_compatibility.py"
CONVERTER_PATH = ROOT.parent / "08-parquet" / "outputs" / "parquet_converter.py"
DATA = ROOT.parent / "data"
CSV = DATA / "tiny" / "orders_typed.csv"
SCHEMA = DATA / "parquet_schema.json"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


REPORTER = load_module("arrow_compatibility", ARTIFACT)
CONVERTER = load_module("parquet_converter_for_arrow", CONVERTER_PATH)


class ArrowCompatibilityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.directory = TemporaryDirectory()
        cls.parquet = Path(cls.directory.name) / "orders.parquet"
        CONVERTER.convert_csv(CSV, cls.parquet, SCHEMA)
        cls.report = REPORTER.build_report(cls.parquet)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.directory.cleanup()

    def test_report_is_valid(self) -> None:
        self.assertTrue(self.report["summary"]["valid"])
        self.assertEqual(self.report["arrow"]["rows"], 5)

    def test_schema_survives_pandas_roundtrip(self) -> None:
        self.assertTrue(self.report["checks"]["pandas_roundtrip_names_types"])
        amount = next(
            field for field in self.report["roundtrip"]["schema"] if field["name"] == "amount"
        )
        self.assertEqual(amount["type"], "decimal128(12, 2)")
        self.assertFalse(self.report["roundtrip"]["field_nullability_preserved"])
        self.assertFalse(self.report["roundtrip"]["schema_metadata_equal"])

    def test_null_counts_are_preserved(self) -> None:
        self.assertTrue(self.report["checks"]["null_counts_preserved"])
        self.assertEqual(self.report["pandas"]["null_counts"]["comment"], 2)

    def test_pandas_uses_arrow_backed_dtypes(self) -> None:
        self.assertIn("[pyarrow]", self.report["pandas"]["dtypes"]["order_id"])
        self.assertIn("[pyarrow]", self.report["pandas"]["dtypes"]["amount"])

    def test_buffer_reuse_is_measured_per_column(self) -> None:
        buffers = self.report["roundtrip"]["buffers"]
        self.assertEqual(set(buffers), set(self.report["arrow"]["null_counts"]))
        self.assertIn("shared_buffer_count", buffers["order_id"])

    def test_duckdb_receives_same_rows_and_aggregate(self) -> None:
        self.assertEqual(self.report["duckdb"]["rows"], 5)
        self.assertEqual(self.report["duckdb"]["amount_sum"], "3226.59")
        self.assertEqual(self.report["duckdb"]["null_comments"], 2)

    def test_duckdb_can_return_arrow_result(self) -> None:
        names = [field["name"] for field in self.report["duckdb"]["arrow_result_schema"]]
        self.assertEqual(names, ["order_id", "amount"])

    def test_cli_writes_report_file(self) -> None:
        output = Path(self.directory.name) / "report.json"
        result = subprocess.run(
            [sys.executable, ARTIFACT, "--input", self.parquet, "--output", output],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(output.read_text())["arrow"]["rows"], 5)


if __name__ == "__main__":
    unittest.main()
