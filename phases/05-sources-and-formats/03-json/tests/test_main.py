from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

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
    def test_valid_json_produces_two_grains(self) -> None:
        report = NORMALIZER.normalize_json(VALID, CONTRACT)
        self.assertTrue(report["summary"]["valid"])
        self.assertEqual(report["records"]["grain"], ["event_id"])
        self.assertEqual(report["items"]["grain"], ["event_id", "item_position"])

    def test_empty_array_keeps_parent_but_has_no_child(self) -> None:
        report = NORMALIZER.normalize_json(VALID, CONTRACT)
        self.assertEqual(report["records"]["rows"], 3)
        self.assertEqual(report["items"]["rows"], 3)
        self.assertNotIn("E5002", {row["event_id"] for row in report["items"]["data"]})

    def test_nested_nullable_value_is_preserved(self) -> None:
        report = NORMALIZER.normalize_json(VALID, CONTRACT)
        record = next(row for row in report["records"]["data"] if row["event_id"] == "E5003")
        self.assertIsNone(record["device_os"])

    def test_array_position_is_part_of_child_grain(self) -> None:
        report = NORMALIZER.normalize_json(VALID, CONTRACT)
        positions = [
            row["item_position"] for row in report["items"]["data"] if row["event_id"] == "E5001"
        ]
        self.assertEqual(positions, [1, 2])

    def test_schema_drift_reports_new_path(self) -> None:
        report = NORMALIZER.normalize_json(DRIFT, CONTRACT)
        self.assertFalse(report["summary"]["valid"])
        self.assertEqual(report["schema"]["unknown_paths"], ["context.app_version"])

    def test_type_drift_is_not_coerced_silently(self) -> None:
        report = NORMALIZER.normalize_json(DRIFT, CONTRACT)
        error = next(value for value in report["errors"] if value.get("field") == "price")
        self.assertEqual(error["expected"], "number")
        self.assertEqual(error["actual"], "str")

    def test_export_preserves_raw_bytes_and_writes_jsonl(self) -> None:
        report = NORMALIZER.normalize_json(VALID, CONTRACT)
        with TemporaryDirectory() as directory:
            exported = NORMALIZER.export_result(report, VALID, directory)
            output = Path(directory)
            self.assertEqual(
                exported["raw_copy_sha256"],
                hashlib.sha256(VALID.read_bytes()).hexdigest(),
            )
            self.assertEqual(len((output / "events.jsonl").read_text().splitlines()), 3)
            self.assertTrue((output / "items.jsonl").is_file())

    def test_cli_returns_one_for_drift(self) -> None:
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
