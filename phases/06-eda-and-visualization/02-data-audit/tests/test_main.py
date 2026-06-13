from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PHASE = ROOT.parents[0]
ARTIFACT = ROOT / "outputs" / "eda_audit.py"
DATA = PHASE / "data" / "tiny" / "user_journeys.csv"
CONTRACT = PHASE / "data" / "contract.json"
SPEC = importlib.util.spec_from_file_location("eda_audit", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


def report() -> dict:
    return AUDIT.audit_frame(
        AUDIT.load_frame(DATA),
        AUDIT.load_contract(CONTRACT),
        source_sha256=AUDIT.sha256_file(DATA),
    )


class EdaAuditTest(unittest.TestCase):
    def test_tiny_profile_exposes_declared_row_grain_failure(self) -> None:
        result = report()
        self.assertEqual(result["source"]["rows"], 25)
        self.assertEqual(result["source"]["unique_users"], 24)
        primary = next(check for check in result["checks"] if check["id"] == "primary-key")
        self.assertEqual(primary["details"]["duplicate_user_ids"], ["J018"])

    def test_incomplete_windows_are_not_treated_as_false_outcomes(self) -> None:
        result = report()
        window = next(check for check in result["checks"] if check["id"] == "observation-window")
        self.assertEqual(window["details"]["incomplete_windows"], 2)
        self.assertEqual(window["details"]["incomplete_with_outcomes"], 0)

    def test_structural_app_version_nulls_pass_policy(self) -> None:
        result = report()
        version = next(check for check in result["checks"] if check["id"] == "app-version-policy")
        self.assertEqual(version["status"], "pass")
        self.assertGreater(version["details"]["structural_web_nulls"], 0)

    def test_negative_onboarding_is_a_failure_but_extreme_is_visible(self) -> None:
        result = report()
        onboarding = next(check for check in result["checks"] if check["id"] == "onboarding-range")
        self.assertEqual(onboarding["status"], "fail")
        self.assertEqual(onboarding["details"]["negative_rows"], 1)
        self.assertEqual(onboarding["details"]["extreme_rows"], 1)

    def test_missing_country_is_reported_as_nullable_not_silently_filled(self) -> None:
        result = report()
        country = result["missingness"]["country"]
        self.assertEqual(country["missing"], 1)
        self.assertEqual(country["policy"], "nullable but requires reporting")

    def test_cleaned_frame_becomes_ready_for_activation(self) -> None:
        frame = AUDIT.load_frame(DATA)
        frame = frame.drop_duplicates("user_id")
        frame = frame[pd.to_numeric(frame["observed_days"]).eq(7)]
        frame = frame[pd.to_numeric(frame["onboarding_seconds"]).ge(0)]
        result = AUDIT.audit_frame(frame, AUDIT.load_contract(CONTRACT))
        self.assertTrue(result["ready_for_activation"])
        self.assertTrue(result["valid"])

    def test_missing_required_column_stops_before_type_checks(self) -> None:
        frame = AUDIT.load_frame(DATA).drop(columns=["user_id"])
        result = AUDIT.audit_frame(frame, AUDIT.load_contract(CONTRACT))
        self.assertFalse(result["valid"])
        self.assertEqual(result["schema"]["missing_columns"], ["user_id"])
        self.assertEqual(result["checks"], [])

    def test_cli_is_quality_gate_and_allow_failures_is_explicit(self) -> None:
        failed = subprocess.run(
            [sys.executable, ARTIFACT, "--input", DATA, "--contract", CONTRACT],
            check=False,
            capture_output=True,
            text=True,
        )
        allowed = subprocess.run(
            [
                sys.executable,
                ARTIFACT,
                "--input",
                DATA,
                "--contract",
                CONTRACT,
                "--allow-failures",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(failed.returncode, 1)
        self.assertEqual(allowed.returncode, 0)
        self.assertEqual(json.loads(failed.stdout), json.loads(allowed.stdout))

    def test_cli_writes_same_report_to_file(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "audit.json"
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--input",
                    DATA,
                    "--contract",
                    CONTRACT,
                    "--output",
                    output,
                    "--allow-failures",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), json.loads(output.read_text()))


if __name__ == "__main__":
    unittest.main()
