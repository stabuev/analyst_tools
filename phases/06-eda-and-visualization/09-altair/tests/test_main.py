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
PHASE = ROOT.parents[0]
ARTIFACT = ROOT / "outputs" / "chart_spec_builder.py"
DATA = PHASE / "data" / "tiny" / "user_journeys.csv"
SPEC = importlib.util.spec_from_file_location("chart_spec_builder", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)


class ChartSpecBuilderTest(unittest.TestCase):
    def test_spec_is_validated_by_altair(self) -> None:
        spec = BUILDER.build_spec(BUILDER.load_frame(DATA))
        self.assertIn("$schema", spec)
        self.assertIn("hconcat", spec)

    def test_field_semantic_types_are_explicit(self) -> None:
        spec = BUILDER.build_spec(BUILDER.load_frame(DATA))
        encodings = BUILDER.walk_encodings(spec)
        observed = {item["field"]: item["type"] for item in encodings}
        self.assertEqual(observed["sessions_7d"], "quantitative")
        self.assertEqual(observed["platform"], "nominal")
        self.assertEqual(observed["cohort_week"], "temporal")

    def test_spec_has_named_interval_parameter(self) -> None:
        spec = BUILDER.build_spec(BUILDER.load_frame(DATA))
        serialized = json.dumps(spec)
        self.assertIn("journey_brush", serialized)
        self.assertIn('"select": {"type": "interval"}', serialized)

    def test_second_view_filters_by_selection(self) -> None:
        spec = BUILDER.build_spec(BUILDER.load_frame(DATA))
        transform = spec["hconcat"][1]["transform"]
        self.assertEqual(transform, [{"filter": {"param": "journey_brush"}}])

    def test_wrong_field_type_is_detected_before_render(self) -> None:
        spec = BUILDER.build_spec(BUILDER.load_frame(DATA))
        broken = deepcopy(spec)
        broken["hconcat"][0]["encoding"]["x"]["type"] = "nominal"
        errors = BUILDER.validate_semantics(broken)
        self.assertIn("sessions_7d must be quantitative, got nominal", errors)

    def test_clean_frame_preserves_user_level_rows(self) -> None:
        frame = BUILDER.load_frame(DATA)
        self.assertTrue(frame["user_id"].is_unique)
        self.assertNotIn(-1, frame["onboarding_seconds"].tolist())

    def test_export_writes_machine_readable_json(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "linked.vl.json"
            report = BUILDER.export_spec(DATA, output)
            self.assertEqual(report["views"], 2)
            self.assertEqual(json.loads(output.read_text())["hconcat"][0]["mark"]["type"], "circle")

    def test_cli_prints_validation_report(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "linked.vl.json"
            result = subprocess.run(
                [sys.executable, ARTIFACT, "--input", DATA, "--output", output],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["semantic_errors"], [])


if __name__ == "__main__":
    unittest.main()
