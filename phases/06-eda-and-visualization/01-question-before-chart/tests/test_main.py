from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "visual_question_brief.py"
SPEC = importlib.util.spec_from_file_location("visual_question_brief", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
BRIEF = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BRIEF)


def example() -> dict:
    return json.loads(json.dumps(BRIEF.EXAMPLE_SPEC))


class VisualQuestionBriefTest(unittest.TestCase):
    def test_example_is_ready_and_preserves_decision_contract(self) -> None:
        report = BRIEF.build_brief(example())
        self.assertEqual(report["status"], "ready")
        self.assertEqual(report["brief"]["id"], "activation-after-release")
        self.assertIn("следующей", report["interpretation_contract"]["decision"])
        self.assertEqual(len(report["required_checks"]), 5)

    def test_trend_plan_uses_time_and_requires_complete_windows(self) -> None:
        report = BRIEF.build_brief(example())
        plan = report["chart_plan"]
        self.assertEqual(plan["encodings"]["x"], "cohort_week")
        self.assertEqual(plan["encodings"]["y"], "activation_7d")
        self.assertIn("complete observation windows", plan["required_context"])

    def test_distribution_plan_exposes_bins_and_outlier_policy(self) -> None:
        spec = example()
        spec["question_type"] = "distribution"
        spec["comparison"] = {
            "dimension": "platform",
            "levels": ["all complete windows"],
            "baseline": "all complete windows",
        }
        spec["metric"] = {
            "name": "onboarding_seconds",
            "kind": "duration",
            "definition": "Duration of the first completed onboarding flow in seconds.",
        }
        report = BRIEF.build_brief(spec)
        self.assertIn("ECDF", report["chart_plan"]["primary_view"])
        self.assertIn("outlier policy and scale choice", report["chart_plan"]["required_context"])

    def test_relationship_plan_requires_explicit_x_and_y(self) -> None:
        spec = example()
        spec["question_type"] = "relationship"
        spec["comparison"] = {
            "dimension": "platform",
            "levels": ["all complete windows"],
            "baseline": "all complete windows",
            "x": "sessions_7d",
            "y": "onboarding_seconds",
        }
        report = BRIEF.build_brief(spec)
        self.assertEqual(
            report["chart_plan"]["encodings"],
            {"x": "sessions_7d", "y": "onboarding_seconds"},
        )
        self.assertIn("overplotting control", report["chart_plan"]["required_context"])

    def test_rate_without_denominator_is_rejected(self) -> None:
        spec = example()
        del spec["metric"]["denominator"]
        with self.assertRaisesRegex(BRIEF.BriefError, "metric.denominator"):
            BRIEF.build_brief(spec)

    def test_duplicate_comparison_levels_are_rejected(self) -> None:
        spec = example()
        spec["comparison"]["levels"] = ["до релиза", "до релиза"]
        with self.assertRaisesRegex(BRIEF.BriefError, "duplicate"):
            BRIEF.build_brief(spec)

    def test_causal_wording_produces_warning_not_causal_claim(self) -> None:
        spec = example()
        spec["question"] = "Каково влияние релиза на семидневную активацию новых пользователей?"
        report = BRIEF.build_brief(spec)
        self.assertEqual(len(report["warnings"]), 1)
        self.assertIn("causality", report["warnings"][0])

    def test_unexpected_top_level_field_is_rejected(self) -> None:
        spec = example()
        spec["chart"] = "line"
        with self.assertRaisesRegex(BRIEF.BriefError, "unexpected"):
            BRIEF.build_brief(spec)

    def test_cli_writes_same_valid_json_to_stdout_and_output(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "brief.json"
            result = subprocess.run(
                [sys.executable, ARTIFACT, "--example", "--output", output],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), json.loads(output.read_text()))
            self.assertEqual(json.loads(result.stdout)["status"], "ready")


if __name__ == "__main__":
    unittest.main()
