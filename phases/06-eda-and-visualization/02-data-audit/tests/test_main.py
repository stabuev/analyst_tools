from __future__ import annotations

import copy
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


def report(frame: pd.DataFrame | None = None, contract: dict | None = None) -> dict:
    return AUDIT.audit_frame(
        AUDIT.load_frame(DATA) if frame is None else frame,
        AUDIT.load_contract(CONTRACT) if contract is None else contract,
        source_sha256=AUDIT.sha256_file(DATA),
        contract_sha256=AUDIT.sha256_file(CONTRACT),
    )


def check(result: dict, check_id: str) -> dict:
    return next(item for item in result["checks"] if item["id"] == check_id)


class EdaAuditTest(unittest.TestCase):
    def test_tiny_separates_exact_delivery_from_key_conflict(self) -> None:
        result = report()
        self.assertEqual(
            check(result, "exact-duplicate-deliveries")["details"]["keys"],
            [{"user_id": "J018"}],
        )
        self.assertEqual(
            check(result, "primary-key-integrity")["details"]["conflicting_duplicate_keys"],
            [],
        )
        self.assertEqual(result["readiness"]["activation_7d"]["status"], "ready_with_decisions")

    def test_conflicting_duplicate_blocks_instead_of_being_dropped(self) -> None:
        frame = AUDIT.load_frame(DATA)
        conflict = frame.iloc[[0]].copy()
        conflict.loc[:, "activated_7d"] = "false"
        result = report(pd.concat([frame, conflict], ignore_index=True))
        primary = check(result, "primary-key-integrity")
        self.assertEqual(primary["status"], "fail")
        self.assertIn({"user_id": "J001"}, primary["details"]["conflicting_duplicate_keys"])
        self.assertEqual(result["readiness"]["activation_7d"]["status"], "blocked")

    def test_blank_primary_key_is_a_blocker(self) -> None:
        frame = AUDIT.load_frame(DATA).drop_duplicates("user_id").copy()
        frame.loc[frame.index[0], "user_id"] = ""
        result = report(frame)
        self.assertEqual(
            check(result, "primary-key-integrity")["details"]["blank_key_rows"],
            [2],
        )
        self.assertEqual(result["readiness"]["activation_7d"]["status"], "blocked")

    def test_integer_and_non_negative_constraints_are_enforced(self) -> None:
        frame = AUDIT.load_frame(DATA).copy()
        frame.loc[frame.index[0], "sessions_7d"] = "1.5"
        frame.loc[frame.index[1], "support_tickets_7d"] = "-1"
        result = report(frame)
        self.assertEqual(check(result, "type:sessions_7d")["status"], "fail")
        self.assertEqual(check(result, "domain:support_tickets_7d")["status"], "fail")
        self.assertFalse(result["valid"])

    def test_contract_categories_drive_the_check(self) -> None:
        contract = copy.deepcopy(AUDIT.load_contract(CONTRACT))
        contract["table"]["columns"]["platform"]["allowed"].remove("android")
        result = report(contract=contract)
        self.assertEqual(
            check(result, "allowed:platform")["details"]["unknown_values"],
            ["android"],
        )
        self.assertEqual(result["readiness"]["activation_7d"]["status"], "blocked")

    def test_observation_policy_excludes_without_rewriting_outcome(self) -> None:
        result = report()
        window = check(result, "observation-window-policy")
        self.assertEqual(window["details"]["incomplete_windows"], 2)
        self.assertEqual(window["details"]["incomplete_with_outcome_rows"], [])
        plan = result["readiness"]["activation_7d"]["selection_plan"]
        self.assertEqual(plan["excluded_by_eligibility"], 2)

    def test_readiness_is_scoped_to_the_declared_question(self) -> None:
        result = report()
        self.assertEqual(result["readiness"]["activation_7d"]["status"], "ready_with_decisions")
        self.assertEqual(result["readiness"]["onboarding_distribution"]["status"], "blocked")
        self.assertIn(
            "domain:onboarding_seconds",
            result["readiness"]["onboarding_distribution"]["blocker_ids"],
        )

    def test_prepare_analysis_frame_applies_only_evidenced_decisions(self) -> None:
        result = report()
        frame = AUDIT.prepare_analysis_frame(DATA, result, "activation_7d")
        self.assertEqual(len(frame), 22)
        self.assertTrue(frame["user_id"].is_unique)
        self.assertTrue(frame["observed_days"].eq(7).all())
        self.assertEqual(str(frame["activated_7d"].dtype), "boolean")
        self.assertTrue(pd.api.types.is_datetime64_any_dtype(frame["cohort_week"]))

    def test_prepare_analysis_frame_rejects_changed_source(self) -> None:
        result = report()
        with TemporaryDirectory() as directory:
            changed = Path(directory) / "changed.csv"
            changed.write_bytes(DATA.read_bytes() + b"\n")
            with self.assertRaisesRegex(AUDIT.AuditError, "checksum"):
                AUDIT.prepare_analysis_frame(changed, result, "activation_7d")

    def test_missing_required_column_stops_dependent_checks(self) -> None:
        frame = AUDIT.load_frame(DATA).drop(columns=["user_id"])
        result = report(frame)
        self.assertEqual(check(result, "schema-required-columns")["status"], "fail")
        self.assertEqual(result["readiness"]["activation_7d"]["status"], "blocked")
        self.assertFalse(any(item["id"] == "primary-key-integrity" for item in result["checks"]))

    def test_cli_exit_code_follows_selected_analysis(self) -> None:
        activation = subprocess.run(
            [
                sys.executable,
                ARTIFACT,
                "--input",
                DATA,
                "--contract",
                CONTRACT,
                "--analysis",
                "activation_7d",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        onboarding = subprocess.run(
            [
                sys.executable,
                ARTIFACT,
                "--input",
                DATA,
                "--contract",
                CONTRACT,
                "--analysis",
                "onboarding_distribution",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(activation.returncode, 0, activation.stderr)
        self.assertEqual(onboarding.returncode, 1, onboarding.stderr)
        self.assertEqual(
            json.loads(activation.stdout)["readiness"]["activation_7d"]["status"],
            "ready_with_decisions",
        )

    def test_report_only_preserves_findings_and_writes_same_json(self) -> None:
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
                    "--analysis",
                    "onboarding_distribution",
                    "--report-only",
                    "--output",
                    output,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), json.loads(output.read_text()))
            self.assertEqual(json.loads(result.stdout)["valid"], False)

    def test_malformed_contract_returns_configuration_error(self) -> None:
        with TemporaryDirectory() as directory:
            contract = Path(directory) / "contract.json"
            contract.write_text('{"table": {"columns": {}}}', encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--input",
                    DATA,
                    "--contract",
                    contract,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("columns", json.loads(result.stdout)["error"])


if __name__ == "__main__":
    unittest.main()
