from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "pipeline_config.py"
EXAMPLE = ROOT / "outputs" / "example_config.json"
SPEC = importlib.util.spec_from_file_location("pipeline_config", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
CONFIG = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONFIG)


def example_payload() -> dict:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


class PipelineConfigTest(unittest.TestCase):
    def test_valid_json_is_normalized(self) -> None:
        report = CONFIG.validate_json(EXAMPLE.read_text(encoding="utf-8"))
        self.assertTrue(report["valid"])
        self.assertEqual(report["config"]["timezone"], "Europe/Moscow")
        self.assertEqual(report["config"]["batch_date"], "2026-06-10")

    def test_unknown_field_is_forbidden(self) -> None:
        payload = example_payload()
        payload["retry_forever"] = True
        report = CONFIG.validate_json(json.dumps(payload))
        self.assertFalse(report["valid"])
        self.assertEqual(report["errors"][0]["location"], "retry_forever")
        self.assertEqual(report["errors"][0]["type"], "extra_forbidden")

    def test_strict_threshold_rejects_numeric_string(self) -> None:
        payload = example_payload()
        payload["thresholds"]["min_orders"] = "1"
        report = CONFIG.validate_json(json.dumps(payload))
        error = next(
            item for item in report["errors"] if item["location"] == "thresholds.min_orders"
        )
        self.assertEqual(error["type"], "int_type")

    def test_unknown_timezone_is_rejected_before_data_read(self) -> None:
        payload = example_payload()
        payload["timezone"] = "Mars/Olympus"
        report = CONFIG.validate_json(json.dumps(payload))
        self.assertEqual(report["errors"][0]["location"], "timezone")
        self.assertIn("unknown IANA timezone", report["errors"][0]["message"])

    def test_volume_bounds_are_consistent(self) -> None:
        payload = example_payload()
        payload["thresholds"]["min_orders"] = 200
        payload["thresholds"]["max_orders"] = 100
        report = CONFIG.validate_json(json.dumps(payload))
        error = next(item for item in report["errors"] if item["location"] == "thresholds")
        self.assertIn("min_orders", error["message"])

    def test_cli_returns_structured_errors_without_traceback(self) -> None:
        with TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            payload = deepcopy(example_payload())
            payload["thresholds"]["max_null_rate"] = 2.0
            config_path.write_text(json.dumps(payload), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, ARTIFACT, "--config", config_path],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 1, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["errors"][0]["location"], "thresholds.max_null_rate")
            self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
