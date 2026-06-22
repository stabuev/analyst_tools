from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "macro_review_auditor.py"
PROJECT = ROOT / "outputs" / "macro_project"
CHECKLIST = ROOT / "outputs" / "compiled_sql_review_checklist.json"
DATA_CONTRACT = ROOT.parent / "data" / "contract.json"
SPEC = importlib.util.spec_from_file_location("macro_review_auditor", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
AUDITOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDITOR)


def check(report: dict[str, Any], check_id: str) -> dict[str, Any]:
    return next(item for item in report["checks"] if item["id"] == check_id)


def read_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def write_yaml(path: Path, value: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")


def macro_doc(properties: dict[str, Any], name: str) -> dict[str, Any]:
    return next(item for item in properties["macros"] if item["name"] == name)


class MacroReviewAuditorTest(unittest.TestCase):
    def copy_project(self, tmp: str) -> Path:
        base = Path(tmp)
        destination = base / "project"
        shutil.copytree(PROJECT, destination)
        shutil.copy(CHECKLIST, base / CHECKLIST.name)
        return destination

    def test_valid_project_declares_documented_low_level_macros(self) -> None:
        report = AUDITOR.validate_project(PROJECT, DATA_CONTRACT, run_dbt=False)
        self.assertTrue(report["valid"])
        self.assertEqual(
            report["summary"]["macro_calls"],
            {
                "money_product": 1,
                "normalize_currency": 4,
                "normalize_status": 3,
                "rub_amount": 3,
                "to_decimal": 10,
            },
        )
        self.assertTrue(check(report, "expected_macros_defined")["valid"])
        self.assertTrue(check(report, "macro_arguments_are_documented")["valid"])
        self.assertTrue(check(report, "business_logic_stays_out_of_macros")["valid"])

    def test_macro_documentation_is_required(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_project(directory)
            properties_path = project / "macros" / "properties.yml"
            properties = read_yaml(properties_path)
            properties["macros"] = [item for item in properties["macros"] if item["name"] != "rub_amount"]
            write_yaml(properties_path, properties)
            report = AUDITOR.validate_project(project, DATA_CONTRACT, run_dbt=False)
            docs_check = check(report, "macro_arguments_are_documented")
            self.assertFalse(docs_check["valid"])
            self.assertEqual(docs_check["sample"][0]["macro"], "rub_amount")

    def test_documented_arguments_must_match_macro_signature(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_project(directory)
            properties_path = project / "macros" / "properties.yml"
            properties = read_yaml(properties_path)
            macro_doc(properties, "to_decimal")["arguments"][0]["name"] = "value"
            write_yaml(properties_path, properties)
            report = AUDITOR.validate_project(project, DATA_CONTRACT, run_dbt=False)
            docs_check = check(report, "macro_arguments_are_documented")
            self.assertFalse(docs_check["valid"])
            self.assertEqual(docs_check["sample"][0]["macro"], "to_decimal")

    def test_expected_macro_usage_cannot_be_bypassed_with_inline_sql(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_project(directory)
            stg_orders = project / "models" / "staging" / "stg_orders.sql"
            stg_orders.write_text(
                stg_orders.read_text(encoding="utf-8").replace("{{ normalize_currency('currency') }}", "upper(currency)"),
                encoding="utf-8",
            )
            report = AUDITOR.validate_project(project, DATA_CONTRACT, run_dbt=False)
            usage_check = check(report, "macro_usage_is_intentional")
            self.assertFalse(usage_check["valid"])
            self.assertEqual(usage_check["sample"][0]["macro"], "normalize_currency")

    def test_business_logic_macro_is_rejected_even_if_it_compiles(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_project(directory)
            macro_path = project / "macros" / "normalization.sql"
            macro_path.write_text(
                macro_path.read_text(encoding="utf-8")
                + "\n{%- macro customer_health_segment() -%}\n'no_revenue'\n{%- endmacro -%}\n",
                encoding="utf-8",
            )
            report = AUDITOR.validate_project(project, DATA_CONTRACT, run_dbt=False)
            business_check = check(report, "business_logic_stays_out_of_macros")
            self.assertFalse(business_check["valid"])
            self.assertEqual(business_check["sample"], ["customer_health_segment"])

    def test_review_checklist_is_required(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_project(directory)
            (Path(directory) / CHECKLIST.name).unlink()
            report = AUDITOR.validate_project(project, DATA_CONTRACT, run_dbt=False)
            self.assertFalse(check(report, "compiled_sql_review_checklist_exists")["valid"])

    def test_live_dbt_compile_outputs_reviewable_sql_and_same_mart(self) -> None:
        report = AUDITOR.validate_project(PROJECT, DATA_CONTRACT, run_dbt=True)
        self.assertTrue(report["valid"])
        self.assertEqual(report["summary"]["compiled_file_count"], 13)
        self.assertEqual(report["summary"]["compiled_mart_line_count"], 113)
        self.assertEqual(report["summary"]["mart_output"], {"row_count": 5, "paid_revenue_rub": "4312.50"})
        self.assertTrue(check(report, "compiled_sql_has_no_jinja")["valid"])
        self.assertTrue(check(report, "compiled_fragments_match_expected_sql")["valid"])

    def test_compiled_sql_change_is_caught_before_reader_reviews_wrong_shape(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_project(directory)
            macro_path = project / "macros" / "normalization.sql"
            macro_path.write_text(
                macro_path.read_text(encoding="utf-8").replace(
                    "upper({{ column_name }})",
                    "trim(upper({{ column_name }}))",
                ),
                encoding="utf-8",
            )
            report = AUDITOR.validate_project(project, DATA_CONTRACT, run_dbt=True)
            self.assertFalse(report["valid"])
            self.assertFalse(check(report, "compiled_fragments_match_expected_sql")["valid"])

    def test_broken_rub_macro_fails_dbt_quality_gate(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_project(directory)
            macro_path = project / "macros" / "normalization.sql"
            macro_path.write_text(
                macro_path.read_text(encoding="utf-8").replace(
                    "{{ amount_column }} * {{ rate_column }}",
                    "{{ amount_column }} / {{ rate_column }}",
                ),
                encoding="utf-8",
            )
            report = AUDITOR.validate_project(project, DATA_CONTRACT, run_dbt=True)
            self.assertFalse(report["valid"])
            self.assertFalse(check(report, "dbt_parse_compile_run_test_succeed")["valid"])

    def test_cli_writes_report_and_returns_nonzero_for_invalid_project(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_project(directory)
            output = Path(directory) / "report.json"
            macro_path = project / "macros" / "normalization.sql"
            macro_path.write_text(
                macro_path.read_text(encoding="utf-8").replace(
                    "{%- macro rub_amount(amount_column, rate_column, precision=18, scale=2) -%}",
                    "{%- macro rub_amount(amount_column, precision=18, scale=2) -%}",
                ),
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--project",
                    project,
                    "--data-contract",
                    DATA_CONTRACT,
                    "--output",
                    output,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 1, result.stderr)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertFalse(report["valid"])
            self.assertFalse(check(report, "expected_macros_defined")["valid"])


if __name__ == "__main__":
    unittest.main()
