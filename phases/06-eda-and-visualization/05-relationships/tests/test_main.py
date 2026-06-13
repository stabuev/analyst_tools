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
ARTIFACT = ROOT / "outputs" / "relationship_explorer.py"
DATA = PHASE / "data" / "tiny" / "user_journeys.csv"
SPEC = importlib.util.spec_from_file_location("relationship_explorer", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
EXPLORER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EXPLORER)


class RelationshipExplorerTest(unittest.TestCase):
    def test_analysis_frame_has_complete_unique_users(self) -> None:
        frame = EXPLORER.load_analysis_frame(DATA)
        self.assertTrue(frame["user_id"].is_unique)
        self.assertTrue(frame["observed_days"].eq(7).all())

    def test_control_table_declares_group_size(self) -> None:
        table = EXPLORER.control_table(EXPLORER.load_analysis_frame(DATA))
        self.assertIn("users", table)
        self.assertTrue(table["activation_rate"].between(0, 1).all())

    def test_weighted_strata_reconcile_to_overall_rate(self) -> None:
        frame = EXPLORER.load_analysis_frame(DATA)
        table = EXPLORER.control_table(frame)
        self.assertAlmostEqual(EXPLORER.reconcile_rate(table), frame["activated_7d"].mean())

    def test_overplotting_is_measured_not_hidden(self) -> None:
        report = EXPLORER.overplotting_report(EXPLORER.load_analysis_frame(DATA))
        self.assertGreater(report["overplotted_observations"], 0)
        self.assertLess(report["unique_coordinates"], report["observations"])

    def test_figure_contains_raw_and_stratified_views(self) -> None:
        figure, _ = EXPLORER.build_figure(EXPLORER.load_analysis_frame(DATA))
        self.assertEqual(len(figure.axes), 2)
        self.assertIn("jitter", figure.axes[0].get_title())
        self.assertIn("Стратифицированные", figure.axes[1].get_title())

    def test_seed_makes_jitter_reproducible(self) -> None:
        frame = EXPLORER.load_analysis_frame(DATA)
        first, _ = EXPLORER.build_figure(frame, seed=7)
        second, _ = EXPLORER.build_figure(frame, seed=7)
        first_offsets = first.axes[0].collections[0].get_offsets()
        second_offsets = second.axes[0].collections[0].get_offsets()
        self.assertTrue((first_offsets == second_offsets).all())

    def test_export_marks_result_as_association_only(self) -> None:
        with TemporaryDirectory() as directory:
            report = EXPLORER.export_relationship(DATA, Path(directory))
            self.assertTrue(report["association_only"])
            self.assertAlmostEqual(
                report["overall_activation_rate"],
                report["reconciled_activation_rate"],
            )

    def test_cli_writes_control_table_and_figure(self) -> None:
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
            self.assertTrue((Path(directory) / "control-table.csv").is_file())
            self.assertTrue((Path(directory) / "sessions-activation.png").is_file())
            self.assertEqual(json.loads(result.stdout)["source_rows"], 22)


if __name__ == "__main__":
    unittest.main()
