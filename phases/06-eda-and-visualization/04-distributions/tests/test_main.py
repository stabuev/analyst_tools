from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PHASE = ROOT.parents[0]
ARTIFACT = ROOT / "outputs" / "distribution_panel.py"
DATA = PHASE / "data" / "tiny" / "user_journeys.csv"
SPEC = importlib.util.spec_from_file_location("distribution_panel", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
PANEL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PANEL)


class DistributionPanelTest(unittest.TestCase):
    def test_invalid_negative_is_separate_from_valid_tail(self) -> None:
        valid, invalid = PANEL.load_values(DATA, "onboarding_seconds")
        self.assertEqual(invalid.tolist(), [-1.0])
        self.assertIn(3600.0, valid.tolist())

    def test_fd_edges_cover_full_range(self) -> None:
        valid, _ = PANEL.load_values(DATA, "onboarding_seconds")
        edges = PANEL.freedman_diaconis_edges(valid)
        self.assertEqual(edges[0], valid.min())
        self.assertEqual(edges[-1], valid.max())
        self.assertGreater(len(edges), 2)

    def test_robust_summary_keeps_outlier_count(self) -> None:
        valid, _ = PANEL.load_values(DATA, "onboarding_seconds")
        summary = PANEL.robust_summary(valid)
        self.assertEqual(summary["maximum"], 3600.0)
        self.assertGreater(summary["above_upper_fence"], 0)

    def test_ecdf_ends_at_one(self) -> None:
        x, y = PANEL.ecdf(pd.Series([3.0, 1.0, 2.0]))
        self.assertEqual(x.tolist(), [1.0, 2.0, 3.0])
        self.assertEqual(y[-1], 1.0)

    def test_panel_uses_same_column_on_both_axes(self) -> None:
        valid, _ = PANEL.load_values(DATA, "onboarding_seconds")
        figure, report = PANEL.build_panel(valid, column="onboarding_seconds")
        self.assertEqual(len(figure.axes), 2)
        self.assertEqual(figure.axes[0].get_xlabel(), "onboarding_seconds")
        self.assertEqual(figure.axes[1].get_xlabel(), "onboarding_seconds")
        self.assertIn("Freedman-Diaconis", report["bin_policy"])

    def test_log_scale_rejects_zero(self) -> None:
        with self.assertRaisesRegex(ValueError, "strictly positive"):
            PANEL.build_panel(pd.Series([0.0, 1.0]), column="x", scale="log")

    def test_export_writes_figure_and_report(self) -> None:
        with TemporaryDirectory() as directory:
            report = PANEL.export_panel(
                DATA,
                "onboarding_seconds",
                Path(directory),
            )
            self.assertTrue((Path(directory) / "onboarding_seconds-distribution.png").is_file())
            self.assertTrue((Path(directory) / "distribution-report.json").is_file())
            self.assertEqual(report["invalid_negative_values"], [-1.0])

    def test_cli_prints_machine_readable_report(self) -> None:
        with TemporaryDirectory() as directory:
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--input",
                    DATA,
                    "--column",
                    "onboarding_seconds",
                    "--output-dir",
                    directory,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["summary"]["maximum"], 3600.0)


if __name__ == "__main__":
    unittest.main()
