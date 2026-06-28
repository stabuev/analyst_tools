from __future__ import annotations

import copy
import csv
import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
PHASE_ROOT = ROOT.parent
ARTIFACT = ROOT / "outputs" / "causal_question_validator.py"
QUESTION = ROOT / "outputs" / "causal_question.json"
TARGET_TRIAL = ROOT / "outputs" / "target_trial_spec.json"
ESTIMAND = ROOT / "outputs" / "estimand.json"
DATA_CONTRACT = PHASE_ROOT / "data" / "contract.json"
DATA_ROOT = PHASE_ROOT / "data" / "tiny"
GENERATOR = PHASE_ROOT / "data" / "generate_data.py"
CODE = ROOT / "code" / "main.py"

MODULE_SPEC = importlib.util.spec_from_file_location("causal_question_validator", ARTIFACT)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
VALIDATOR = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(VALIDATOR)


def load_specs() -> tuple[dict, dict, dict, dict]:
    return (
        json.loads(QUESTION.read_text(encoding="utf-8")),
        json.loads(TARGET_TRIAL.read_text(encoding="utf-8")),
        json.loads(ESTIMAND.read_text(encoding="utf-8")),
        json.loads(DATA_CONTRACT.read_text(encoding="utf-8")),
    )


def check(report: dict, check_id: str) -> dict:
    return next(item for item in report["checks"] if item["id"] == check_id)


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def copy_data_root(target: Path) -> None:
    target.mkdir(parents=True)
    for source in DATA_ROOT.iterdir():
        if source.is_file():
            (target / source.name).write_bytes(source.read_bytes())


def mutate_csv(path: Path, mutate) -> None:
    rows = VALIDATOR.read_csv(path)
    mutate(rows)
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


class CausalQuestionValidatorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.question, self.trial, self.estimand, self.contract = load_specs()

    def validate(
        self,
        *,
        question: dict | None = None,
        trial: dict | None = None,
        estimand: dict | None = None,
        data_root: Path = DATA_ROOT,
    ) -> dict:
        return VALIDATOR.validate_specs(
            self.question if question is None else question,
            self.trial if trial is None else trial,
            self.estimand if estimand is None else estimand,
            self.contract,
            data_root,
        )

    def test_valid_question_is_ready_for_identification_not_effect_claim(self) -> None:
        report = self.validate()
        self.assertTrue(report["valid"])
        self.assertEqual(report["summary"]["estimand_type"], "ATE")
        self.assertEqual(report["summary"]["target_population_users"], 10)
        self.assertEqual(report["summary"]["treated_users"], 6)
        self.assertEqual(report["summary"]["comparator_users"], 4)
        self.assertEqual(report["summary"]["identification_status"], "not_yet_identified")
        warning = check(report, "observational_assignment_requires_identification")
        self.assertEqual(warning["severity"], "warning")
        self.assertFalse(warning["valid"])

    def test_code_example_builds_manual_population_and_estimand(self) -> None:
        result = subprocess.run(
            [sys.executable, CODE],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(result.stdout)
        self.assertTrue(payload["audit_valid"])
        self.assertEqual(payload["target_population_count"], 10)
        self.assertEqual(payload["treated_users"], 6)
        self.assertEqual(payload["blocking_checks"], [])
        self.assertEqual(payload["warnings"], ["observational_assignment_requires_identification"])
        self.assertIn("ATE of assisted_within_24h", payload["manual_estimand"])

    def test_question_trial_and_estimand_ids_must_align(self) -> None:
        estimand = copy.deepcopy(self.estimand)
        estimand["question_id"] = "another_question"
        report = self.validate(estimand=estimand)
        self.assertFalse(report["valid"])
        self.assertFalse(check(report, "spec_ids_align")["valid"])

    def test_target_population_cannot_use_post_treatment_field(self) -> None:
        trial = copy.deepcopy(self.trial)
        trial["target_population"]["criteria"].append(
            {
                "table": "outcomes",
                "field": "onboarding_completed_48h",
                "operator": "==",
                "value": True,
            }
        )
        report = self.validate(trial=trial)
        population_check = check(report, "target_population_contract")
        self.assertFalse(population_check["valid"])
        self.assertEqual(population_check["sample"][-1]["timing"], "post_treatment")

    def test_treatment_versions_and_operational_definition_are_required(self) -> None:
        trial = copy.deepcopy(self.trial)
        trial["treatment"]["strategies"][0]["versions"] = []
        trial["treatment"]["strategies"][1]["operational_definition"] = ""
        report = self.validate(trial=trial)
        treatment_check = check(report, "treatment_definition_precise")
        self.assertFalse(treatment_check["valid"])
        reasons = {item["reason"] for item in treatment_check["sample"]}
        self.assertIn("treatment versions must be explicit", reasons)
        self.assertIn("missing operational definition", reasons)

    def test_ate_requires_eligible_population_scope(self) -> None:
        estimand = copy.deepcopy(self.estimand)
        estimand["population_scope"] = "treated_population"
        report = self.validate(estimand=estimand)
        alignment = check(report, "estimand_population_alignment")
        self.assertFalse(alignment["valid"])
        self.assertEqual(alignment["sample"][0]["expected"], "eligible_population")

    def test_late_requires_instrument_and_complier_population(self) -> None:
        estimand = copy.deepcopy(self.estimand)
        estimand["estimand_type"] = "LATE"
        estimand["population_scope"] = "compliers"
        report = self.validate(estimand=estimand)
        alignment = check(report, "estimand_population_alignment")
        self.assertFalse(alignment["valid"])
        self.assertEqual(alignment["sample"][0]["field"], "instrument")

    def test_all_four_causal_assumptions_are_required(self) -> None:
        estimand = copy.deepcopy(self.estimand)
        del estimand["assumptions"]["positivity"]
        report = self.validate(estimand=estimand)
        assumptions = check(report, "causal_assumptions_declared")
        self.assertFalse(assumptions["valid"])
        self.assertIn("positivity", assumptions["sample"][0]["assumptions"])

    def test_effect_claim_is_blocked_before_identification(self) -> None:
        question = copy.deepcopy(self.question)
        estimand = copy.deepcopy(self.estimand)
        question["current_claim_status"] = "identified_under_stated_assumptions"
        estimand["identification_status"] = "identified"
        estimand["estimator_status"] = "estimated"
        report = self.validate(question=question, estimand=estimand)
        claim_check = check(report, "claim_status_is_pre_identification")
        self.assertFalse(claim_check["valid"])

    def test_treatment_before_time_zero_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            data_root = Path(directory) / "tiny"
            copy_data_root(data_root)

            def start_before_time_zero(rows: list[dict[str, str]]) -> None:
                rows[0]["started_at"] = "2026-07-01T09:55:00+03:00"

            mutate_csv(data_root / "onboarding_assistance.csv", start_before_time_zero)
            report = self.validate(data_root=data_root)
            timing = check(report, "time_zero_treatment_followup_order")
            self.assertFalse(timing["valid"])
            self.assertEqual(timing["sample"][0]["user_id"], "U001")

    def test_incomplete_followup_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            data_root = Path(directory) / "tiny"
            copy_data_root(data_root)

            def shorten_followup(rows: list[dict[str, str]]) -> None:
                rows[0]["followup_end_at"] = "2026-07-15T10:00:00+03:00"

            mutate_csv(data_root / "outcomes.csv", shorten_followup)
            report = self.validate(data_root=data_root)
            timing = check(report, "time_zero_treatment_followup_order")
            self.assertFalse(timing["valid"])
            self.assertEqual(
                timing["sample"][0]["reason"], "follow-up does not cover declared outcomes"
            )

    def test_duplicate_user_breaks_analysis_grain(self) -> None:
        with TemporaryDirectory() as directory:
            data_root = Path(directory) / "tiny"
            copy_data_root(data_root)

            def duplicate_first(rows: list[dict[str, str]]) -> None:
                rows.append(dict(rows[0]))

            mutate_csv(data_root / "outcomes.csv", duplicate_first)
            report = self.validate(data_root=data_root)
            data_check = check(report, "data_columns_grain_relationships")
            self.assertFalse(data_check["valid"])
            self.assertEqual(data_check["sample"][0]["user_ids"], ["U001"])

    def test_tiny_generator_is_byte_reproducible(self) -> None:
        with TemporaryDirectory() as directory:
            generated_root = Path(directory)
            subprocess.run(
                [
                    sys.executable,
                    GENERATOR,
                    "--profile",
                    "tiny",
                    "--output-root",
                    generated_root,
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            manifest = json.loads((DATA_ROOT / "manifest.json").read_text(encoding="utf-8"))
            for filename in manifest["files"]:
                self.assertEqual(
                    (generated_root / "tiny" / filename).read_bytes(),
                    (DATA_ROOT / filename).read_bytes(),
                    filename,
                )

    def test_cli_writes_report_and_returns_nonzero_for_invalid_spec(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            invalid = copy.deepcopy(self.estimand)
            invalid["population_scope"] = "treated_population"
            estimand_path = root / "estimand.json"
            output_path = root / "audit.json"
            write_json(estimand_path, invalid)
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--question",
                    QUESTION,
                    "--target-trial",
                    TARGET_TRIAL,
                    "--estimand",
                    estimand_path,
                    "--data-contract",
                    DATA_CONTRACT,
                    "--data-root",
                    DATA_ROOT,
                    "--output",
                    output_path,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertFalse(json.loads(result.stdout)["valid"])
            self.assertEqual(json.loads(result.stdout), json.loads(output_path.read_text()))


if __name__ == "__main__":
    unittest.main()
