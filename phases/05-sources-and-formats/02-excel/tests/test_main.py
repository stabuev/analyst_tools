from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "excel_audit.py"
DATA = ROOT.parent / "data"
SPEC_PATH = DATA / "excel_spec.json"
VALID = DATA / "tiny" / "orders_report.xlsx"
SHIFTED = DATA / "tiny" / "orders_report_shifted.xlsx"
MODULE_SPEC = importlib.util.spec_from_file_location("excel_audit", ARTIFACT)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
AUDITOR = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(AUDITOR)


class ExcelAuditTest(unittest.TestCase):
    def test_declared_range_is_valid(self) -> None:
        report = AUDITOR.audit_workbook(VALID, SPEC_PATH)
        self.assertTrue(report["summary"]["valid"])
        self.assertEqual(report["selection"]["data_rows"], 5)
        self.assertEqual(report["selection"]["header"][0], "order_id")

    def test_workbook_structure_is_visible(self) -> None:
        report = AUDITOR.audit_workbook(VALID, SPEC_PATH)
        self.assertEqual(report["workbook"]["sheet_names"], ["Инструкция", "Заказы", "Справочник"])
        self.assertIn("A1:G1", report["workbook"]["merged_ranges"])
        self.assertEqual(report["workbook"]["hidden_columns"], ["H"])

    def test_formulas_are_detected_but_excluded_from_range(self) -> None:
        report = AUDITOR.audit_workbook(VALID, SPEC_PATH)
        self.assertIn("G5", report["workbook"]["formulas"])
        self.assertEqual(report["selection"]["formulas_in_range"], [])

    def test_shifted_header_fails_explicitly(self) -> None:
        report = AUDITOR.audit_workbook(SHIFTED, SPEC_PATH)
        self.assertFalse(report["summary"]["valid"])
        self.assertFalse(report["selection"]["header_matches"])
        self.assertEqual(
            report["selection"]["header"][0],
            "Сформировано повторно: структура сдвинута",
        )

    def test_formula_inside_selected_range_is_rejected(self) -> None:
        spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
        spec["range"] = "A4:G9"
        spec["columns"].append("line_total")
        with TemporaryDirectory() as directory:
            path = Path(directory) / "spec.json"
            path.write_text(json.dumps(spec), encoding="utf-8")
            report = AUDITOR.audit_workbook(VALID, path)
        self.assertFalse(report["summary"]["valid"])
        self.assertIn("G5", report["selection"]["formulas_in_range"])

    def test_formula_and_cached_value_are_different_views(self) -> None:
        formulas = load_workbook(VALID, data_only=False)["Заказы"]["G5"].value
        cached = load_workbook(VALID, data_only=True)["Заказы"]["G5"].value
        self.assertEqual(formulas, "=D5*F5")
        self.assertIsNone(cached)

    def test_pandas_uses_declared_sheet_header_and_columns(self) -> None:
        report = AUDITOR.audit_workbook(VALID, SPEC_PATH)
        self.assertTrue(report["pandas"]["valid"])
        self.assertEqual(report["pandas"]["columns"], json.loads(SPEC_PATH.read_text())["columns"])

    def test_cli_is_a_quality_gate(self) -> None:
        result = subprocess.run(
            [sys.executable, ARTIFACT, "--input", SHIFTED, "--spec", SPEC_PATH],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertFalse(json.loads(result.stdout)["summary"]["valid"])


if __name__ == "__main__":
    unittest.main()
