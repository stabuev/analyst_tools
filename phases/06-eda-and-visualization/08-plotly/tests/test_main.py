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
ARTIFACT = ROOT / "outputs" / "anomaly_explorer.py"
DATA = PHASE / "data" / "tiny" / "user_journeys.csv"
SPEC = importlib.util.spec_from_file_location("anomaly_explorer", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
EXPLORER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EXPLORER)


class AnomalyExplorerTest(unittest.TestCase):
    def test_frame_removes_duplicates_incomplete_and_invalid_duration(self) -> None:
        frame = EXPLORER.load_frame(DATA)
        self.assertTrue(frame["user_id"].is_unique)
        self.assertTrue(frame["observed_days"].eq(7).all())
        self.assertTrue((frame["onboarding_seconds"] >= 0).all())

    def test_figure_has_one_trace_per_platform(self) -> None:
        figure = EXPLORER.build_figure(EXPLORER.load_frame(DATA))
        self.assertEqual([trace.name for trace in figure.data], EXPLORER.PLATFORMS)

    def test_hover_exposes_identifier_and_context(self) -> None:
        figure = EXPLORER.build_figure(EXPLORER.load_frame(DATA))
        template = figure.data[0].hovertemplate
        self.assertIn("user=", template)
        self.assertIn("channel=", template)
        self.assertIn("<extra></extra>", template)

    def test_customdata_matches_trace_rows(self) -> None:
        figure = EXPLORER.build_figure(EXPLORER.load_frame(DATA))
        for trace in figure.data:
            self.assertEqual(len(trace.customdata), len(trace.x))

    def test_dropdown_has_all_and_each_platform(self) -> None:
        figure = EXPLORER.build_figure(EXPLORER.load_frame(DATA))
        labels = [button.label for button in figure.layout.updatemenus[0].buttons]
        self.assertEqual(labels, ["Все платформы", *EXPLORER.PLATFORMS])

    def test_figure_json_is_machine_inspectable(self) -> None:
        figure = EXPLORER.build_figure(EXPLORER.load_frame(DATA))
        value = json.loads(figure.to_json())
        self.assertEqual(len(value["data"]), 3)
        self.assertEqual(value["layout"]["xaxis"]["title"]["text"], "sessions_7d")

    def test_export_is_standalone_and_does_not_require_dash(self) -> None:
        with TemporaryDirectory() as directory:
            report = EXPLORER.export_explorer(DATA, Path(directory))
            html = (Path(directory) / "anomaly-explorer.html").read_text()
            self.assertIn("plotly.js", html)
            self.assertFalse(report["dash_required"])
            self.assertGreater(report["files"]["anomaly-explorer.html"]["bytes"], 1_000_000)

    def test_cli_writes_html_json_and_report(self) -> None:
        with TemporaryDirectory() as directory:
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--input",
                    DATA,
                    "--output-dir",
                    directory,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((Path(directory) / "anomaly-explorer.plotly.json").is_file())
            self.assertEqual(json.loads(result.stdout)["traces"], 3)


if __name__ == "__main__":
    unittest.main()
