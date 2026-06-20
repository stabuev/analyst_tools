from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "reliable_order_pipeline.py"
DATA = ROOT.parent / "data" / "tiny"
OBSERVED_AT = datetime.fromisoformat("2026-06-10T12:00:00+03:00")
SPEC = importlib.util.spec_from_file_location("reliable_order_pipeline", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
PIPELINE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PIPELINE)


def write_config(path: Path, input_dir: Path, output_dir: Path, **overrides) -> None:
    payload = {
        "config_version": "1.0.0",
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "timezone": "Europe/Moscow",
        "batch_date": "2026-06-10",
        "schema_version": "1.0.0",
        "thresholds": {
            "freshness_hours": 24,
            "min_orders": 1,
            "max_orders": 100,
            "max_null_rate": 0.0,
            "max_duplicate_rate": 0.0,
        },
    }
    payload.update(overrides)
    path.write_text(json.dumps(payload), encoding="utf-8")


def copy_data(target: Path) -> None:
    target.mkdir(parents=True)
    for name in ("users.csv", "orders.csv", "order_items.csv"):
        (target / name).write_bytes((DATA / name).read_bytes())


class ReliableOrderPipelineTest(unittest.TestCase):
    def test_success_publishes_complete_immutable_version(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            delivery = root / "delivery"
            config = root / "config.json"
            write_config(config, DATA, delivery)
            report = PIPELINE.run_pipeline(config, OBSERVED_AT)
            current = json.loads((delivery / "current.json").read_text())
            version = delivery / current["version_path"]
            required = {
                "config.json",
                "mart/orders.parquet",
                "mart/daily_metrics.csv",
                "quality/invariant-report.json",
                "quality/schema-report.json",
                "quality/sql-checks.json",
                "quality/regression-report.json",
                "quality/monitoring-report.json",
                "logs/run.jsonl",
                "run-report.json",
                "manifest.json",
            }
            files = {
                path.relative_to(version).as_posix()
                for path in version.rglob("*")
                if path.is_file()
            }
            self.assertEqual(report["status"], "success")
            self.assertTrue(report["published"])
            self.assertTrue(required.issubset(files))
            self.assertEqual(len(pd.read_parquet(version / "mart" / "orders.parquet")), 10)
            manifest = json.loads((version / "manifest.json").read_text())
            self.assertEqual(manifest["row_counts"]["daily_metrics"], 3)

    def test_failed_data_gate_keeps_previous_current_pointer(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            input_dir = root / "input"
            copy_data(input_dir)
            delivery = root / "delivery"
            config = root / "config.json"
            write_config(config, input_dir, delivery)
            first = PIPELINE.run_pipeline(config, OBSERVED_AT)
            current_before = (delivery / "current.json").read_bytes()
            items = pd.read_csv(input_dir / "order_items.csv", dtype=str)
            items.loc[0, "unit_price_rub"] = "700.01"
            items.to_csv(input_dir / "order_items.csv", index=False)
            second = PIPELINE.run_pipeline(config, OBSERVED_AT + timedelta(minutes=1))
            self.assertEqual(first["status"], "success")
            self.assertEqual(second["failure_class"], "data_failure")
            self.assertFalse(second["published"])
            self.assertEqual((delivery / "current.json").read_bytes(), current_before)
            self.assertFalse(second["gates"]["schema"])
            self.assertFalse(second["gates"]["sql"])

    def test_publish_failure_after_staging_keeps_previous_pointer(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            delivery = root / "delivery"
            config = root / "config.json"
            write_config(config, DATA, delivery)
            PIPELINE.run_pipeline(config, OBSERVED_AT)
            current_before = (delivery / "current.json").read_bytes()
            failed = PIPELINE.run_pipeline(
                config,
                OBSERVED_AT + timedelta(minutes=1),
                simulate_publish_failure=True,
            )
            self.assertEqual(failed["failure_class"], "system_failure")
            self.assertFalse(failed["published"])
            self.assertEqual((delivery / "current.json").read_bytes(), current_before)
            self.assertTrue(Path(failed["delivery_path"]).is_dir())

    def test_invalid_config_fails_before_missing_input_is_read(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config.json"
            write_config(
                config,
                root / "missing-input",
                root / "delivery",
                unexpected=True,
            )
            report = PIPELINE.run_pipeline(config, OBSERVED_AT)
            self.assertEqual(report["failure_class"], "configuration_failure")
            self.assertFalse((root / "delivery").exists())

    def test_cli_publishes_and_returns_current_pointer(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            delivery = root / "delivery"
            config = root / "config.json"
            write_config(config, DATA, delivery)
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--config",
                    config,
                    "--observed-at",
                    OBSERVED_AT.isoformat(),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["current"]["run_id"], report["run_id"])
            self.assertTrue((delivery / "current.json").is_file())


if __name__ == "__main__":
    unittest.main()
