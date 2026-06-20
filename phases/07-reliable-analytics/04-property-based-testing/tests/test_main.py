from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "property_suite.py"
SPEC = importlib.util.spec_from_file_location("property_suite", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
SUITE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SUITE)


class PropertySuiteTest(unittest.TestCase):
    def test_all_declared_properties_pass(self) -> None:
        report = SUITE.run_suite()
        self.assertTrue(report["valid"])
        self.assertEqual(len(report["properties"]), 4)
        self.assertTrue(all(item["examples"] == 100 for item in report["properties"]))

    def test_revenue_property_handles_empty_and_mixed_batches(self) -> None:
        self.assertEqual(SUITE.paid_revenue_kopecks([]), 0)
        self.assertEqual(
            SUITE.paid_revenue_kopecks([("paid", 101), ("pending", 999), ("paid", 2)]),
            103,
        )

    def test_deduplication_keeps_latest_and_is_idempotent(self) -> None:
        rows = [(2, 1, 500), (1, 2, 200), (1, 1, 100), (2, 3, 700)]
        result = SUITE.deduplicate_latest(rows)
        self.assertEqual(result, [(1, 2, 200), (2, 3, 700)])
        self.assertEqual(SUITE.deduplicate_latest(result), result)

    def test_hypothesis_shrinks_rounding_bug_to_real_counterexample(self) -> None:
        example = SUITE.minimal_rounding_counterexample()
        self.assertNotEqual(SUITE.buggy_rounded_total(example), sum(example))
        self.assertEqual(len(example), 1)

    def test_cli_emits_property_report(self) -> None:
        result = subprocess.run(
            [sys.executable, ARTIFACT],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["valid"])
        self.assertEqual(payload["shrunk_counterexample"]["bug"], "round_each_amount_before_sum")


if __name__ == "__main__":
    unittest.main()
