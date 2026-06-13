from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
PHASE = ROOT.parents[0]
ARTIFACT = ROOT / "outputs" / "bootstrap_visualizer.py"
DATA = PHASE / "data" / "tiny" / "user_journeys.csv"
SPEC = importlib.util.spec_from_file_location("bootstrap_visualizer", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
BOOT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BOOT)


class BootstrapVisualizerTest(unittest.TestCase):
    def test_frame_uses_unique_complete_users(self) -> None:
        frame = BOOT.load_frame(DATA)
        self.assertTrue(frame["user_id"].is_unique)
        self.assertTrue(frame["observed_days"].eq(7).all())

    def test_same_seed_reproduces_interval(self) -> None:
        values = np.array([0.0, 1.0, 1.0, 0.0, 1.0])
        first = BOOT.bootstrap_rate(
            values,
            repeats=500,
            confidence=0.95,
            rng=np.random.default_rng(7),
        )
        second = BOOT.bootstrap_rate(
            values,
            repeats=500,
            confidence=0.95,
            rng=np.random.default_rng(7),
        )
        self.assertEqual(first, second)

    def test_interval_contains_observed_estimate(self) -> None:
        table = BOOT.interval_table(BOOT.load_frame(DATA), repeats=500)
        self.assertTrue((table["lower"] <= table["estimate"]).all())
        self.assertTrue((table["estimate"] <= table["upper"]).all())

    def test_group_size_is_shown(self) -> None:
        table = BOOT.interval_table(BOOT.load_frame(DATA), repeats=200)
        self.assertTrue((table["users"] > 0).all())
        self.assertEqual(table["users"].sum(), len(BOOT.load_frame(DATA)))

    def test_report_records_resampling_unit_and_provenance(self) -> None:
        _, report = BOOT.build_report(BOOT.load_frame(DATA), repeats=200, seed=11)
        self.assertEqual(report["resampling_unit"], "user")
        self.assertEqual(report["seed"], 11)
        self.assertEqual(len(report["source_user_ids_sha256"]), 64)

    def test_figure_has_rate_domain_and_n_annotations(self) -> None:
        table = BOOT.interval_table(BOOT.load_frame(DATA), repeats=200)
        figure = BOOT.build_figure(table, confidence=0.95)
        self.assertEqual(figure.axes[0].get_ylim(), (0.0, 1.0))
        self.assertEqual(len(figure.axes[0].texts), len(table))

    def test_empty_group_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "empty"):
            BOOT.bootstrap_rate(
                np.array([]),
                repeats=10,
                confidence=0.95,
                rng=np.random.default_rng(1),
            )

    def test_cli_exports_figure_table_and_report(self) -> None:
        with TemporaryDirectory() as directory:
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--input",
                    DATA,
                    "--output-dir",
                    directory,
                    "--repeats",
                    "200",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((Path(directory) / "activation-intervals.png").is_file())
            self.assertTrue((Path(directory) / "intervals.csv").is_file())
            self.assertEqual(json.loads(result.stdout)["repeats"], 200)


if __name__ == "__main__":
    unittest.main()
