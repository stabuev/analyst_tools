from __future__ import annotations

import csv
import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "golden_regression.py"
GOLDEN = ROOT / "outputs" / "orders_golden.json"
DATA = ROOT.parent / "data" / "tiny"
SPEC = importlib.util.spec_from_file_location("golden_regression", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
GOLDEN_TOOL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GOLDEN_TOOL)


def write_orders(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


class GoldenRegressionTest(unittest.TestCase):
    def test_reviewed_tiny_baseline_matches(self) -> None:
        report = GOLDEN_TOOL.compare_with_golden(DATA, GOLDEN)
        self.assertTrue(report["valid"])
        self.assertEqual(report["difference_count"], 0)

    def test_row_order_does_not_change_semantic_snapshot(self) -> None:
        rows = GOLDEN_TOOL.read_orders(DATA)
        with TemporaryDirectory() as directory:
            target = Path(directory)
            write_orders(target / "orders.csv", list(reversed(rows)), list(rows[0]))
            actual = GOLDEN_TOOL.semantic_snapshot(target)
        expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
        self.assertEqual(actual, expected)

    def test_paid_rule_change_produces_specific_semantic_diff(self) -> None:
        rows = GOLDEN_TOOL.read_orders(DATA)
        rows[6]["status"] = "paid"
        with TemporaryDirectory() as directory:
            target = Path(directory)
            write_orders(target / "orders.csv", rows, list(rows[0]))
            report = GOLDEN_TOOL.compare_with_golden(target, GOLDEN)
        paths = {difference["path"] for difference in report["differences"]}
        self.assertIn("$.summary.paid_order_count", paths)
        self.assertIn("$.summary.paid_revenue_kopecks", paths)
        self.assertNotIn("$.summary.order_count", paths)

    def test_diff_reports_missing_and_extra_fields(self) -> None:
        differences = GOLDEN_TOOL.semantic_diff({"a": 1}, {"b": 2})
        self.assertEqual(
            differences,
            [
                {"path": "$.a", "expected": 1, "actual": None},
                {"path": "$.b", "expected": None, "actual": 2},
            ],
        )

    def test_cli_returns_nonzero_on_regression(self) -> None:
        rows = GOLDEN_TOOL.read_orders(DATA)
        rows[0]["amount_rub"] = "1200.01"
        with TemporaryDirectory() as directory:
            target = Path(directory)
            write_orders(target / "orders.csv", rows, list(rows[0]))
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--data-dir",
                    target,
                    "--golden",
                    GOLDEN,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertGreater(json.loads(result.stdout)["difference_count"], 0)


if __name__ == "__main__":
    unittest.main()
