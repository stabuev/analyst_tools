from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
PHASE = ROOT.parents[0]
ARTIFACT = ROOT / "outputs" / "seaborn_panel.py"
DATA = PHASE / "data" / "tiny" / "user_journeys.csv"
SPEC = importlib.util.spec_from_file_location("seaborn_panel", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
PANEL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PANEL)


class SeabornPanelTest(unittest.TestCase):
    def test_frame_has_numeric_binary_outcome(self) -> None:
        frame = PANEL.load_frame(DATA)
        self.assertEqual(set(frame["activated_7d"].unique()), {0.0, 1.0})

    def test_control_table_contains_estimate_and_n(self) -> None:
        table = PANEL.control_table(PANEL.load_frame(DATA))
        self.assertIn("estimate", table)
        self.assertIn("users", table)
        self.assertTrue(table["estimate"].between(0, 1).all())

    def test_panel_facets_by_all_platforms(self) -> None:
        grid = PANEL.build_panel(PANEL.load_frame(DATA), n_boot=100)
        self.assertEqual(len(grid.axes.flat), 3)
        self.assertEqual([axis.get_title() for axis in grid.axes.flat], PANEL.PLATFORM_ORDER)

    def test_axes_are_customizable_matplotlib_objects(self) -> None:
        grid = PANEL.build_panel(PANEL.load_frame(DATA), n_boot=100)
        for axis in grid.axes.flat:
            self.assertEqual(axis.get_ylim(), (0.0, 1.0))
            self.assertEqual(axis.get_ylabel(), "Доля activation_7d")

    def test_period_order_is_explicit(self) -> None:
        grid = PANEL.build_panel(PANEL.load_frame(DATA), n_boot=100)
        labels = [tick.get_text() for tick in grid.axes.flat[0].get_xticklabels()]
        self.assertEqual(labels, PANEL.PERIOD_ORDER)

    def test_export_records_estimator_and_errorbar_semantics(self) -> None:
        with TemporaryDirectory() as directory:
            report = PANEL.export_panel(DATA, Path(directory), n_boot=100, seed=3)
            self.assertEqual(report["estimator"], "mean")
            self.assertEqual(report["errorbar"], {"method": "ci", "level": 95})
            self.assertEqual(report["seed"], 3)

    def test_export_writes_control_table_and_figure(self) -> None:
        with TemporaryDirectory() as directory:
            PANEL.export_panel(DATA, Path(directory), n_boot=100)
            self.assertTrue((Path(directory) / "platform-activation-panel.png").is_file())
            self.assertTrue((Path(directory) / "control-table.csv").is_file())

    def test_cli_prints_report(self) -> None:
        with TemporaryDirectory() as directory:
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--input",
                    DATA,
                    "--output-dir",
                    directory,
                    "--n-boot",
                    "100",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["facet"], "platform")


if __name__ == "__main__":
    unittest.main()
