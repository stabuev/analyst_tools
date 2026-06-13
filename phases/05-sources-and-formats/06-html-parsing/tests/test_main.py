from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "html_extractor.py"
DATA = ROOT.parent / "data"
CONTRACT = DATA / "html_contract.json"
VALID = DATA / "tiny" / "orders.html"
CHANGED = DATA / "tiny" / "orders_changed.html"
SPEC = importlib.util.spec_from_file_location("html_extractor", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
EXTRACTOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EXTRACTOR)


class HtmlExtractorTest(unittest.TestCase):
    def test_valid_fixture_matches_selector_contract(self) -> None:
        result = EXTRACTOR.extract_html(VALID, CONTRACT)
        self.assertTrue(result["summary"]["valid"])
        self.assertEqual(result["summary"]["record_count"], 2)

    def test_data_attributes_provide_stable_identity(self) -> None:
        result = EXTRACTOR.extract_html(VALID, CONTRACT)
        self.assertEqual([row["order_id"] for row in result["records"]], ["O2601", "O2602"])

    def test_number_is_converted_without_float_rounding(self) -> None:
        result = EXTRACTOR.extract_html(VALID, CONTRACT)
        self.assertEqual(result["records"][0]["amount"], Decimal("1200.50"))

    def test_changed_markup_reports_missing_selector(self) -> None:
        result = EXTRACTOR.extract_html(CHANGED, CONTRACT)
        self.assertFalse(result["summary"]["valid"])
        error = result["errors"][0]
        self.assertEqual(error["field"], "amount")
        self.assertEqual(error["matches"], 0)

    def test_ambiguous_selector_is_rejected(self) -> None:
        html = VALID.read_text(encoding="utf-8").replace(
            '<span data-field="amount">1200.50</span>',
            '<span data-field="amount">1200.50</span><span data-field="amount">1</span>',
        )
        with TemporaryDirectory() as directory:
            path = Path(directory) / "ambiguous.html"
            path.write_text(html, encoding="utf-8")
            result = EXTRACTOR.extract_html(path, CONTRACT)
        self.assertEqual(result["errors"][0]["matches"], 2)

    def test_duplicate_record_id_is_rejected(self) -> None:
        html = VALID.read_text(encoding="utf-8").replace("O2602", "O2601")
        with TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate.html"
            path.write_text(html, encoding="utf-8")
            result = EXTRACTOR.extract_html(path, CONTRACT)
        self.assertFalse(result["checks"]["record_ids_unique"])

    def test_export_writes_jsonl_and_report(self) -> None:
        result = EXTRACTOR.extract_html(VALID, CONTRACT)
        with TemporaryDirectory() as directory:
            EXTRACTOR.export_result(result, directory)
            output = Path(directory)
            self.assertEqual(len((output / "orders.jsonl").read_text().splitlines()), 2)
            self.assertTrue((output / "report.json").is_file())

    def test_cli_is_quality_gate_for_changed_markup(self) -> None:
        result = subprocess.run(
            [sys.executable, ARTIFACT, "--input", CHANGED, "--contract", CONTRACT],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertFalse(json.loads(result.stdout)["summary"]["valid"])


if __name__ == "__main__":
    unittest.main()
