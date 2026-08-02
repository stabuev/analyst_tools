from __future__ import annotations

import copy
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
    def setUp(self) -> None:
        self.contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        self.html = VALID.read_text(encoding="utf-8")

    def extract_text(
        self,
        html: str,
        *,
        contract: dict | None = None,
    ) -> dict:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            html_path = root / "fixture.html"
            contract_path = root / "contract.json"
            html_path.write_text(html, encoding="utf-8")
            contract_path.write_text(
                json.dumps(contract or self.contract, ensure_ascii=False), encoding="utf-8"
            )
            return EXTRACTOR.extract_html(html_path, contract_path)

    def test_valid_fixture_matches_selector_contract(self) -> None:
        result = EXTRACTOR.extract_html(VALID, CONTRACT)
        self.assertTrue(result["summary"]["valid"])
        self.assertEqual(result["summary"]["failed_checks"], [])
        self.assertEqual(result["summary"]["record_count"], 2)

    def test_records_have_declared_grain_and_decimal_type(self) -> None:
        result = EXTRACTOR.extract_html(VALID, CONTRACT)
        self.assertEqual(
            result["records"],
            [
                {"order_id": "O2601", "user_id": "U001", "amount": Decimal("1200.50")},
                {"order_id": "O2602", "user_id": "U002", "amount": Decimal("950.00")},
            ],
        )

    def test_provenance_uses_names_and_checksums_without_local_paths(self) -> None:
        result = EXTRACTOR.extract_html(VALID, CONTRACT)
        serialized = json.dumps(result, default=EXTRACTOR.json_default)
        self.assertEqual(result["source"]["file_name"], "orders.html")
        self.assertEqual(len(result["source"]["sha256"]), 64)
        self.assertEqual(len(result["contract_source"]["sha256"]), 64)
        self.assertNotIn(str(DATA), serialized)

    def test_changed_fixture_is_invalid_and_names_missing_field(self) -> None:
        result = EXTRACTOR.extract_html(CHANGED, CONTRACT)
        self.assertFalse(result["summary"]["valid"])
        error = next(item for item in result["errors"] if item.get("field") == "amount")
        self.assertEqual(error["record_id"], "O2602")
        self.assertEqual(error["matches"], 0)

    def test_missing_container_is_rejected(self) -> None:
        result = self.extract_text(self.html.replace(" data-orders", ""))
        self.assertFalse(result["checks"]["container_exactly_one"])
        self.assertEqual(result["records"], [])

    def test_ambiguous_container_is_rejected(self) -> None:
        result = self.extract_text(
            self.html.replace("</body>", "<section data-orders></section></body>")
        )
        self.assertEqual(result["selector_counts"]["containers"], 2)
        self.assertFalse(result["summary"]["valid"])

    def test_exact_record_count_rejects_growth(self) -> None:
        extra = """<article data-order-card data-order-id="O2603">
        <span data-field="user">U003</span><span data-field="amount">10.00</span></article>"""
        result = self.extract_text(self.html.replace("</section>", f"{extra}</section>"))
        self.assertFalse(result["checks"]["record_count_matches"])

    def test_min_record_count_allows_growth(self) -> None:
        contract = copy.deepcopy(self.contract)
        contract["record_count"]["mode"] = "min"
        extra = """<article data-order-card data-order-id="O2603">
        <span data-field="user">U003</span><span data-field="amount">10.00</span></article>"""
        result = self.extract_text(
            self.html.replace("</section>", f"{extra}</section>"), contract=contract
        )
        self.assertTrue(result["summary"]["valid"])

    def test_missing_record_id_is_rejected(self) -> None:
        result = self.extract_text(self.html.replace(' data-order-id="O2602"', ""))
        self.assertFalse(result["checks"]["record_ids_present"])

    def test_blank_record_id_is_rejected(self) -> None:
        result = self.extract_text(self.html.replace('data-order-id="O2602"', 'data-order-id=" "'))
        self.assertFalse(result["checks"]["record_ids_present"])

    def test_duplicate_record_id_is_rejected(self) -> None:
        result = self.extract_text(self.html.replace("O2602", "O2601"))
        self.assertFalse(result["checks"]["record_ids_unique"])
        grain_error = next(item for item in result["errors"] if item["kind"] == "grain")
        self.assertEqual(grain_error["values"], ["O2601"])

    def test_missing_required_field_is_rejected(self) -> None:
        result = self.extract_text(self.html.replace('<span data-field="user">U002</span>', ""))
        self.assertFalse(result["checks"]["required_fields_valid"])

    def test_ambiguous_field_is_rejected(self) -> None:
        html = self.html.replace(
            '<span data-field="amount">1200.50</span>',
            '<span data-field="amount">1200.50</span><span data-field="amount">1</span>',
        )
        result = self.extract_text(html)
        error = next(item for item in result["errors"] if item.get("field") == "amount")
        self.assertEqual(error["matches"], 2)

    def test_blank_string_is_rejected(self) -> None:
        result = self.extract_text(self.html.replace(">U002<", ">  <"))
        self.assertFalse(result["checks"]["required_fields_valid"])

    def test_invalid_decimal_spellings_are_rejected(self) -> None:
        for value in ["NaN", "Infinity", "1e3", "1,20", ""]:
            with self.subTest(value=value):
                result = self.extract_text(self.html.replace("950.00", value))
                self.assertFalse(result["checks"]["required_fields_valid"])

    def test_attribute_source_is_supported_explicitly(self) -> None:
        contract = copy.deepcopy(self.contract)
        contract["fields"]["user_id"] = {
            "selector": "[data-field='user']",
            "source": "attribute",
            "attribute": "data-user-id",
            "type": "string",
            "non_blank": True,
        }
        html = self.html.replace(">U001<", ' data-user-id="U001">name<').replace(
            ">U002<", ' data-user-id="U002">name<'
        )
        result = self.extract_text(html, contract=contract)
        self.assertTrue(result["summary"]["valid"])
        self.assertEqual([row["user_id"] for row in result["records"]], ["U001", "U002"])

    def test_missing_attribute_value_is_rejected(self) -> None:
        contract = copy.deepcopy(self.contract)
        contract["fields"]["user_id"] = {
            "selector": "[data-field='user']",
            "source": "attribute",
            "attribute": "data-user-id",
            "type": "string",
            "non_blank": True,
        }
        result = self.extract_text(self.html, contract=contract)
        self.assertFalse(result["checks"]["required_fields_valid"])

    def test_invalid_utf8_is_controlled_error(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "bad.html"
            path.write_bytes(b"\xff")
            with self.assertRaisesRegex(EXTRACTOR.HtmlContractError, "not valid UTF-8"):
                EXTRACTOR.extract_html(path, CONTRACT)

    def test_missing_or_conflicting_charset_declaration_is_rejected(self) -> None:
        for html in [
            self.html.replace('<meta charset="utf-8">', ""),
            self.html.replace('charset="utf-8"', 'charset="windows-1251"'),
        ]:
            with self.subTest():
                result = self.extract_text(html)
                self.assertFalse(result["checks"]["charset_declaration_matches"])

    def test_max_bytes_is_enforced(self) -> None:
        with self.assertRaisesRegex(EXTRACTOR.HtmlContractError, "exceeds max_bytes"):
            EXTRACTOR.extract_html(VALID, CONTRACT, max_bytes=10)

    def test_invalid_selector_is_controlled_contract_error(self) -> None:
        contract = copy.deepcopy(self.contract)
        contract["record_selector"] = "["
        with self.assertRaisesRegex(EXTRACTOR.HtmlContractError, "valid CSS selector"):
            self.extract_text(self.html, contract=contract)

    def test_contract_rejects_unknown_key_and_unsupported_version(self) -> None:
        for key, value, message in [
            ("surprise", True, "unknown keys"),
            ("version", "9.0.0", "unsupported contract version"),
        ]:
            with self.subTest(key=key):
                contract = copy.deepcopy(self.contract)
                contract[key] = value
                with self.assertRaisesRegex(EXTRACTOR.HtmlContractError, message):
                    self.extract_text(self.html, contract=contract)

    def test_duplicate_contract_keys_are_rejected(self) -> None:
        raw = CONTRACT.read_text(encoding="utf-8").replace(
            '"version": "2.0.0",', '"version": "2.0.0",\n  "version": "2.0.0",'
        )
        with TemporaryDirectory() as directory:
            path = Path(directory) / "contract.json"
            path.write_text(raw, encoding="utf-8")
            with self.assertRaisesRegex(EXTRACTOR.HtmlContractError, "duplicate JSON key"):
                EXTRACTOR.load_contract(path)

    def test_publish_is_self_contained_and_marks_snapshot(self) -> None:
        result = EXTRACTOR.extract_html(VALID, CONTRACT)
        with TemporaryDirectory() as directory:
            output = Path(directory) / "orders_snapshot.json"
            EXTRACTOR.publish_snapshot(result, output)
            payload = json.loads(output.read_text(encoding="utf-8"))
        self.assertTrue(payload["summary"]["published"])
        self.assertEqual(len(payload["records"]), 2)
        self.assertEqual(payload["contract"]["version"], "2.0.0")
        self.assertIn("sha256", payload["source"])

    def test_invalid_result_cannot_replace_previous_snapshot(self) -> None:
        result = EXTRACTOR.extract_html(CHANGED, CONTRACT)
        with TemporaryDirectory() as directory:
            output = Path(directory) / "orders_snapshot.json"
            output.write_text("previous\n", encoding="utf-8")
            with self.assertRaisesRegex(EXTRACTOR.HtmlContractError, "cannot be published"):
                EXTRACTOR.publish_snapshot(result, output)
            self.assertEqual(output.read_text(encoding="utf-8"), "previous\n")

    def test_atomic_publish_leaves_no_temporary_file(self) -> None:
        result = EXTRACTOR.extract_html(VALID, CONTRACT)
        with TemporaryDirectory() as directory:
            output = Path(directory) / "orders_snapshot.json"
            EXTRACTOR.publish_snapshot(result, output)
            self.assertEqual([path.name for path in Path(directory).iterdir()], [output.name])

    def test_cli_valid_fixture_publishes_snapshot(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "snapshot.json"
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--input",
                    VALID,
                    "--contract",
                    CONTRACT,
                    "--output",
                    output,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(output.is_file())
            self.assertTrue(json.loads(result.stdout)["summary"]["published"])

    def test_cli_changed_fixture_is_quality_gate_and_does_not_publish(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "snapshot.json"
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--input",
                    CHANGED,
                    "--contract",
                    CONTRACT,
                    "--output",
                    output,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertFalse(output.exists())
            self.assertFalse(json.loads(result.stdout)["summary"]["valid"])

    def test_allow_failures_is_diagnostic_only(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "snapshot.json"
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--input",
                    CHANGED,
                    "--contract",
                    CONTRACT,
                    "--output",
                    output,
                    "--allow-failures",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
