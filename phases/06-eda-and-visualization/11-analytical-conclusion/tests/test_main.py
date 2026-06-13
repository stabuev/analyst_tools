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
ARTIFACT = ROOT / "outputs" / "eda_report_builder.py"
DATA = PHASE / "data" / "tiny" / "user_journeys.csv"
CONTRACT = PHASE / "data" / "contract.json"
SPEC = importlib.util.spec_from_file_location("eda_report_builder", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)


def build(directory: str) -> tuple[Path, dict]:
    output = Path(directory) / "eda-report"
    manifest = BUILDER.build_delivery(
        DATA,
        CONTRACT,
        output,
        bootstrap_repeats=200,
    )
    return output, manifest


class EdaReportBuilderTest(unittest.TestCase):
    def test_delivery_contains_required_artifacts(self) -> None:
        with TemporaryDirectory() as directory:
            output, _ = build(directory)
            required = [
                "question.json",
                "audit.json",
                "report.md",
                "figures/activation-overview.png",
                "figures/activation-overview.svg",
                "figures/segment-comparison.png",
                "interactive/anomaly-explorer.html",
                "specs/linked-segments.vl.json",
                "manifest.json",
            ]
            for relative in required:
                self.assertTrue((output / relative).is_file(), relative)

    def test_question_brief_is_ready(self) -> None:
        with TemporaryDirectory() as directory:
            output, _ = build(directory)
            self.assertEqual(json.loads((output / "question.json").read_text())["status"], "ready")

    def test_audit_preserves_known_defects_and_decisions(self) -> None:
        with TemporaryDirectory() as directory:
            output, _ = build(directory)
            audit = json.loads((output / "audit.json").read_text())
            self.assertIn("primary-key", audit["failure_ids"])
            self.assertTrue(any("incomplete" in item for item in audit["decision_log"]))

    def test_analysis_excludes_duplicate_and_incomplete_windows(self) -> None:
        with TemporaryDirectory() as directory:
            _, manifest = build(directory)
            self.assertEqual(manifest["input"]["raw_rows"], 25)
            self.assertEqual(manifest["input"]["analysis_rows"], 22)

    def test_report_separates_observation_hypothesis_limit_and_next_step(self) -> None:
        with TemporaryDirectory() as directory:
            output, _ = build(directory)
            report = (output / "report.md").read_text()
            for heading in (
                "## Наблюдения",
                "## Объяснения-гипотезы",
                "## Ограничения",
                "## Следующий шаг",
            ):
                self.assertIn(heading, report)
            self.assertIn("не доказывают причинный эффект", report)

    def test_interactive_appendix_is_standalone(self) -> None:
        with TemporaryDirectory() as directory:
            output, _ = build(directory)
            html = output / "interactive" / "anomaly-explorer.html"
            self.assertGreater(html.stat().st_size, 1_000_000)
            self.assertIn("plotly.js", html.read_text())

    def test_vega_lite_spec_contains_linked_selection(self) -> None:
        with TemporaryDirectory() as directory:
            output, _ = build(directory)
            spec = json.loads((output / "specs" / "linked-segments.vl.json").read_text())
            serialized = json.dumps(spec)
            self.assertIn("journey_brush", serialized)
            self.assertIn('"filter": {"param": "journey_brush"}', serialized)

    def test_manifest_checksums_match_every_file(self) -> None:
        with TemporaryDirectory() as directory:
            output, manifest = build(directory)
            for relative, metadata in manifest["files"].items():
                self.assertEqual(
                    BUILDER.sha256_file(output / relative),
                    metadata["sha256"],
                    relative,
                )

    def test_cli_prints_manifest(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "delivery"
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--input",
                    DATA,
                    "--contract",
                    CONTRACT,
                    "--output-dir",
                    output,
                    "--bootstrap-repeats",
                    "200",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["input"]["analysis_rows"], 22)


if __name__ == "__main__":
    unittest.main()
