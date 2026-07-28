from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "cohort_mart.py"
DATA = ROOT.parent / "data" / "tiny"
SPEC = importlib.util.spec_from_file_location("cohort_mart", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
COHORT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(COHORT)


class CohortMartTest(unittest.TestCase):
    def setUp(self) -> None:
        self.report = COHORT.build_cohort_mart(
            DATA / "users.csv",
            DATA / "events.csv",
        )
        self.rows = {(row["cohort_month"], row["period_index"]): row for row in self.report["rows"]}

    def test_cohort_sizes_use_all_registered_users(self) -> None:
        self.assertEqual(
            self.report["cohort_sizes"],
            {"2025-12-01": 2, "2026-01-01": 3, "2026-02-01": 3},
        )

    def test_matrix_has_complete_zero_periods(self) -> None:
        self.assertEqual(self.report["checks"]["matrix_rows"], 12)
        self.assertEqual(self.rows[("2025-12-01", 0)]["active_users"], 0)
        self.assertTrue(self.report["checks"]["grain_unique"])

    def test_december_cohort_retention(self) -> None:
        period_one = self.rows[("2025-12-01", 1)]
        self.assertEqual(period_one["active_users"], 2)
        self.assertEqual(period_one["retention"], 1.0)
        self.assertEqual(self.rows[("2025-12-01", 2)]["retention"], 0.5)

    def test_january_cohort_uses_fixed_denominator(self) -> None:
        self.assertEqual(self.rows[("2026-01-01", 1)]["retention"], 1.0)
        self.assertAlmostEqual(self.rows[("2026-01-01", 2)]["retention"], 0.3333)

    def test_activity_month_matches_period_index(self) -> None:
        row = self.rows[("2026-02-01", 2)]
        self.assertEqual(row["activity_month"], "2026-04-01")

    def test_duplicate_delivery_is_removed_from_event_count(self) -> None:
        self.assertEqual(self.report["checks"]["source_event_rows"], 16)
        self.assertEqual(self.report["checks"]["unique_events"], 15)
        self.assertEqual(self.report["checks"]["duplicate_event_rows"], 1)

    def test_retention_never_exceeds_one(self) -> None:
        self.assertTrue(all(0 <= row["retention"] <= 1 for row in self.report["rows"]))

    def test_cli_prints_json(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                ARTIFACT,
                "--users",
                DATA / "users.csv",
                "--events",
                DATA / "events.csv",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["checks"]["matrix_rows"], 12)


if __name__ == "__main__":
    unittest.main()
