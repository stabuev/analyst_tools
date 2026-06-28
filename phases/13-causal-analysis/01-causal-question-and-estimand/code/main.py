from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PHASE_ROOT = ROOT.parent
QUESTION = ROOT / "outputs" / "causal_question.json"
TARGET_TRIAL = ROOT / "outputs" / "target_trial_spec.json"
ESTIMAND = ROOT / "outputs" / "estimand.json"
DATA_CONTRACT = PHASE_ROOT / "data" / "contract.json"
DATA_ROOT = PHASE_ROOT / "data" / "tiny"
VALIDATOR_PATH = ROOT / "outputs" / "causal_question_validator.py"


def load_validator():
    spec = importlib.util.spec_from_file_location("causal_question_validator", VALIDATOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {VALIDATOR_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as source:
        return json.load(source)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def manual_target_population() -> list[str]:
    users = {row["user_id"]: row for row in read_csv(DATA_ROOT / "users.csv")}
    baseline = {row["user_id"]: row for row in read_csv(DATA_ROOT / "pre_treatment_behavior.csv")}
    return sorted(
        user_id
        for user_id, user in users.items()
        if user["is_test_user"] == "false"
        and user["eligible_for_program"] == "true"
        and int(baseline[user_id]["friction_score"]) >= 50
    )


def manual_estimand_sentence(estimand: dict[str, Any]) -> str:
    return (
        f"{estimand['estimand_type']} of {estimand['treatment_strategy']} versus "
        f"{estimand['comparator_strategy']} on {estimand['outcome_id']} "
        f"at {estimand['time_horizon_days']} days for {estimand['population_scope']}"
    )


def main() -> None:
    validator = load_validator()
    estimand = read_json(ESTIMAND)
    target_population = manual_target_population()
    report = validator.run(
        QUESTION,
        TARGET_TRIAL,
        ESTIMAND,
        DATA_CONTRACT,
        DATA_ROOT,
    )
    payload = {
        "question_id": report["summary"]["question_id"],
        "manual_estimand": manual_estimand_sentence(estimand),
        "manual_target_population_users": target_population,
        "target_population_count": len(target_population),
        "treated_users": report["summary"]["treated_users"],
        "comparator_users": report["summary"]["comparator_users"],
        "identification_status": report["summary"]["identification_status"],
        "audit_valid": report["valid"],
        "blocking_checks": [
            check["id"]
            for check in report["checks"]
            if not check["valid"] and check["severity"] == "error"
        ],
        "warnings": [
            check["id"]
            for check in report["checks"]
            if not check["valid"] and check["severity"] == "warning"
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
