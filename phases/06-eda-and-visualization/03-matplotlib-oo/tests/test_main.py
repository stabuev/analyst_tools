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
ARTIFACT = ROOT / "outputs" / "figure_factory.py"
DATA = PHASE / "data" / "tiny" / "user_journeys.csv"
SPEC = importlib.util.spec_from_file_location("figure_factory", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
FACTORY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FACTORY)


class FigureFactoryTest(unittest.TestCase):
    def test_clean_frame_has_one_row_per_complete_user(self) -> None:
        frame = FACTORY.load_clean_frame(DATA)
        self.assertTrue(frame["user_id"].is_unique)
        self.assertTrue(frame["observed_days"].eq(7).all())

    def test_activation_table_has_explicit_denominator(self) -> None:
        table = FACTORY.activation_table(FACTORY.load_clean_frame(DATA))
        self.assertIn("users", table)
        self.assertTrue(table["activation"].between(0, 1).all())

    def test_figure_uses_two_explicit_axes(self) -> None:
        figure, axes, _ = FACTORY.build_figure(FACTORY.load_clean_frame(DATA))
        self.assertEqual(len(figure.axes), 2)
        self.assertEqual(len(axes), 2)

    def test_activation_axis_has_honest_rate_scale(self) -> None:
        figure, axes, _ = FACTORY.build_figure(FACTORY.load_clean_frame(DATA))
        self.assertEqual(axes[0].get_ylabel(), "Доля пользователей")
        self.assertEqual(axes[0].get_ylim(), (0.0, 1.0))

    def test_count_axis_names_the_denominator(self) -> None:
        _, axes, _ = FACTORY.build_figure(FACTORY.load_clean_frame(DATA))
        self.assertEqual(axes[1].get_ylabel(), "Пользователи")

    def test_export_writes_png_svg_and_manifest(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory)
            manifest = FACTORY.export_figure(FACTORY.load_clean_frame(DATA), output)
            self.assertTrue((output / "activation-overview.png").is_file())
            self.assertTrue((output / "activation-overview.svg").is_file())
            self.assertEqual(
                set(manifest["files"]),
                {
                    "activation-overview.png",
                    "activation-overview.svg",
                },
            )

    def test_manifest_checksums_match_exported_bytes(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory)
            manifest = FACTORY.export_figure(FACTORY.load_clean_frame(DATA), output)
            for filename, metadata in manifest["files"].items():
                self.assertEqual(FACTORY.sha256_file(output / filename), metadata["sha256"])

    def test_cli_prints_manifest(self) -> None:
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
            self.assertEqual(json.loads(result.stdout)["figure"]["axes"], 2)


if __name__ == "__main__":
    unittest.main()
