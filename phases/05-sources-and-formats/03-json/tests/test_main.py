from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import unittest
from collections.abc import Callable
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "json_normalizer.py"
DATA = ROOT.parent / "data"
CONTRACT = DATA / "json_contract.json"
VALID = DATA / "tiny" / "events_nested.json"
DRIFT = DATA / "tiny" / "events_schema_drift.json"
MODULE_SPEC = importlib.util.spec_from_file_location("json_normalizer", ARTIFACT)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
NORMALIZER = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(NORMALIZER)


class JsonNormalizerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report = NORMALIZER.normalize_json(VALID, CONTRACT)

    def normalize_modified(
        self,
        mutate_payload: Callable[[dict[str, Any]], None],
        *,
        mutate_contract: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        payload = json.loads(VALID.read_text(encoding="utf-8"))
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        mutate_payload(payload)
        if mutate_contract is not None:
            mutate_contract(contract)
        with TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "input.json"
            contract_path = root / "contract.json"
            input_path.write_text(
                json.dumps(payload, ensure_ascii=False),
                encoding="utf-8",
            )
            contract_path.write_text(
                json.dumps(contract, ensure_ascii=False),
                encoding="utf-8",
            )
            return NORMALIZER.normalize_json(input_path, contract_path)

    def test_valid_json_produces_two_checked_grains(self) -> None:
        self.assertTrue(self.report["summary"]["valid"])
        self.assertEqual(self.report["records"]["grain"]["columns"], ["event_id"])
        self.assertEqual(
            self.report["items"]["grain"]["columns"],
            ["event_id", "item_position"],
        )
        self.assertTrue(self.report["records"]["grain"]["valid"])
        self.assertTrue(self.report["items"]["grain"]["valid"])

    def test_envelope_field_is_checked_and_preserved(self) -> None:
        self.assertEqual(
            self.report["envelope"]["data"]["exported_at"],
            "2026-05-06T00:00:00Z",
        )
        self.assertIn("exported_at", self.report["schema"]["observed_paths"])

    def test_empty_array_keeps_parent_but_has_no_child(self) -> None:
        self.assertEqual(self.report["records"]["rows"], 3)
        self.assertEqual(self.report["items"]["rows"], 3)
        self.assertNotIn(
            "E5002",
            {row["event_id"] for row in self.report["items"]["data"]},
        )

    def test_explicit_nullable_value_is_preserved(self) -> None:
        record = next(row for row in self.report["records"]["data"] if row["event_id"] == "E5003")
        self.assertIsNone(record["device_os"])

    def test_missing_required_nullable_path_is_not_treated_as_null(self) -> None:
        def remove_device_os(payload: dict[str, Any]) -> None:
            del payload["events"][0]["context"]["device"]["os"]

        report = self.normalize_modified(remove_device_os)
        self.assertFalse(report["summary"]["valid"])
        self.assertEqual(
            report["schema"]["missing_required_paths"][0]["path"],
            "context.device.os",
        )
        self.assertEqual(report["errors"][0]["error"], "missing required path")

    def test_missing_array_is_different_from_empty_array(self) -> None:
        def remove_items(payload: dict[str, Any]) -> None:
            del payload["events"][1]["items"]

        report = self.normalize_modified(remove_items)
        self.assertFalse(report["summary"]["valid"])
        error = next(
            value for value in report["errors"] if value["error"] == "missing required array path"
        )
        self.assertEqual(error["location"], "events[2]")

    def test_parent_key_and_position_form_child_grain(self) -> None:
        positions = [
            row["item_position"]
            for row in self.report["items"]["data"]
            if row["event_id"] == "E5001"
        ]
        self.assertEqual(positions, [1, 2])
        self.assertEqual(
            set(self.report["items"]["data"][0]),
            {"event_id", "item_position", "product_id", "quantity", "price"},
        )

    def test_contract_cannot_claim_an_unimplemented_child_grain(self) -> None:
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        contract["array"]["grain"] = ["missing_column"]
        with TemporaryDirectory() as directory:
            path = Path(directory) / "contract.json"
            path.write_text(json.dumps(contract), encoding="utf-8")
            with self.assertRaisesRegex(
                NORMALIZER.JsonContractError,
                "array.grain must equal",
            ):
                NORMALIZER.normalize_json(VALID, path)

    def test_top_level_schema_drift_is_visible(self) -> None:
        def add_schema_version(payload: dict[str, Any]) -> None:
            payload["schema_version"] = "2.0"

        report = self.normalize_modified(add_schema_version)
        self.assertFalse(report["summary"]["valid"])
        self.assertEqual(report["schema"]["unknown_paths"], ["schema_version"])

    def test_unknown_path_can_be_an_explicit_warning_policy(self) -> None:
        def add_schema_version(payload: dict[str, Any]) -> None:
            payload["schema_version"] = "2.0"

        def warn_on_unknown(contract: dict[str, Any]) -> None:
            contract["unknown_path_policy"] = "warn"

        report = self.normalize_modified(
            add_schema_version,
            mutate_contract=warn_on_unknown,
        )
        self.assertTrue(report["summary"]["valid"])
        self.assertEqual(report["warnings"][0]["paths"], ["schema_version"])

    def test_type_drift_is_not_coerced_silently(self) -> None:
        report = NORMALIZER.normalize_json(DRIFT, CONTRACT)
        error = next(value for value in report["errors"] if value.get("field") == "price")
        self.assertEqual(error["expected"], "number")
        self.assertEqual(error["actual"], "string")

    def test_timestamp_requires_an_explicit_utc_offset(self) -> None:
        def remove_offset(payload: dict[str, Any]) -> None:
            payload["events"][0]["occurred_at"] = "2026-05-01T10:00:00"

        report = self.normalize_modified(remove_offset)
        self.assertFalse(report["summary"]["valid"])
        error = next(value for value in report["errors"] if value.get("field") == "occurred_at")
        self.assertEqual(error["error"], "type mismatch")

    def test_duplicate_parent_key_breaks_parent_and_child_grains(self) -> None:
        def duplicate_event_id(payload: dict[str, Any]) -> None:
            payload["events"][2]["event_id"] = payload["events"][0]["event_id"]

        report = self.normalize_modified(duplicate_event_id)
        self.assertFalse(report["records"]["grain"]["valid"])
        self.assertFalse(report["items"]["grain"]["valid"])
        self.assertEqual(
            report["records"]["grain"]["duplicate_rows"][0]["row"],
            3,
        )

    def test_duplicate_json_object_key_is_rejected(self) -> None:
        source = VALID.read_text(encoding="utf-8").replace(
            '"event_id": "E5001",',
            '"event_id": "E5001",\n      "event_id": "E5999",',
            1,
        )
        with TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate.json"
            path.write_text(source, encoding="utf-8")
            with self.assertRaisesRegex(
                NORMALIZER.JsonContractError,
                "duplicate object key: event_id",
            ):
                NORMALIZER.normalize_json(path, CONTRACT)

    def test_non_finite_json_number_is_rejected(self) -> None:
        source = VALID.read_text(encoding="utf-8").replace("1000.0", "NaN", 1)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "nan.json"
            path.write_text(source, encoding="utf-8")
            with self.assertRaisesRegex(
                NORMALIZER.JsonContractError,
                "non-finite number",
            ):
                NORMALIZER.normalize_json(path, CONTRACT)

    def test_valid_export_preserves_raw_bytes_and_writes_jsonl(self) -> None:
        with TemporaryDirectory() as directory:
            exported = NORMALIZER.export_result(self.report, VALID, directory)
            output = Path(directory)
            self.assertEqual(
                exported["source"]["sha256"],
                hashlib.sha256(VALID.read_bytes()).hexdigest(),
            )
            self.assertEqual(
                (output / "raw.json").read_bytes(),
                VALID.read_bytes(),
            )
            self.assertEqual(
                len((output / "events.jsonl").read_text().splitlines()),
                3,
            )
            self.assertTrue((output / "items.jsonl").is_file())
            self.assertEqual(
                {value["path"] for value in exported["delivery"]["files"]},
                {"raw.json", "events.jsonl", "items.jsonl"},
            )

    def test_invalid_report_does_not_publish_normalized_tables(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "delivery"
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--input",
                    DRIFT,
                    "--contract",
                    CONTRACT,
                    "--output-dir",
                    output,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertFalse(output.exists())
            self.assertFalse(json.loads(result.stdout)["delivery"]["written"])

    def test_cli_returns_controlled_error_for_invalid_utf8(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "broken.json"
            path.write_bytes(b'{"events": ["\xff"]}')
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--input",
                    path,
                    "--contract",
                    CONTRACT,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn("not valid UTF-8", json.loads(result.stdout)["error"])

    def test_cli_returns_one_for_contract_drift(self) -> None:
        result = subprocess.run(
            [sys.executable, ARTIFACT, "--input", DRIFT, "--contract", CONTRACT],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertFalse(json.loads(result.stdout)["summary"]["valid"])


if __name__ == "__main__":
    unittest.main()
