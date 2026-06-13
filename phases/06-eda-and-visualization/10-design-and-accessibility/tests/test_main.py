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
ARTIFACT = ROOT / "outputs" / "visual_review.py"
SPEC = importlib.util.spec_from_file_location("visual_review", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
REVIEW = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REVIEW)


class VisualReviewTest(unittest.TestCase):
    def test_example_passes_all_checks(self) -> None:
        report = REVIEW.audit_review(deepcopy(REVIEW.EXAMPLE_REVIEW))
        self.assertTrue(report["valid"])
        self.assertEqual(report["failure_ids"], [])

    def test_color_only_meaning_fails(self) -> None:
        value = deepcopy(REVIEW.EXAMPLE_REVIEW)
        value["color"]["color_only"] = True
        report = REVIEW.audit_review(value)
        self.assertIn("redundant-channel", report["failure_ids"])

    def test_bar_requires_zero_baseline(self) -> None:
        value = deepcopy(REVIEW.EXAMPLE_REVIEW)
        value["chart_type"] = "bar"
        value["axes"]["baseline"] = 0.5
        report = REVIEW.audit_review(value)
        self.assertIn("baseline", report["failure_ids"])

    def test_rate_uses_full_domain(self) -> None:
        value = deepcopy(REVIEW.EXAMPLE_REVIEW)
        value["axes"]["y_domain"] = [0.5, 0.8]
        report = REVIEW.audit_review(value)
        self.assertIn("rate-domain", report["failure_ids"])

    def test_estimate_requires_interval_semantics_and_n(self) -> None:
        value = deepcopy(REVIEW.EXAMPLE_REVIEW)
        value["uncertainty"]["semantics"] = ""
        value["uncertainty"]["sample_size_shown"] = False
        report = REVIEW.audit_review(value)
        self.assertIn("uncertainty", report["failure_ids"])

    def test_alt_text_requires_meaningful_description(self) -> None:
        value = deepcopy(REVIEW.EXAMPLE_REVIEW)
        value["alt_text"] = "График."
        report = REVIEW.audit_review(value)
        self.assertIn("alt-text", report["failure_ids"])

    def test_cli_returns_one_for_failed_review(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "review.json"
            value = deepcopy(REVIEW.EXAMPLE_REVIEW)
            value["color"]["color_only"] = True
            path.write_text(json.dumps(value), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, ARTIFACT, "--review", path],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 1)
            self.assertFalse(json.loads(result.stdout)["valid"])

    def test_cli_example_writes_same_report_to_output(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "review-report.json"
            result = subprocess.run(
                [sys.executable, ARTIFACT, "--example", "--output", output],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), json.loads(output.read_text()))


if __name__ == "__main__":
    unittest.main()
