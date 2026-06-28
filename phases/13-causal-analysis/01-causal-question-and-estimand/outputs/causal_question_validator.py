from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

REQUIRED_QUESTION_FIELDS = {
    "question_id",
    "title",
    "business_decision",
    "causal_question",
    "target_population_id",
    "treatment_id",
    "comparator_id",
    "primary_outcome_id",
    "time_zero_id",
    "estimand_id",
    "current_claim_status",
    "allowed_claim_statuses",
    "known_risks",
    "limitations",
}
REQUIRED_TRIAL_FIELDS = {
    "trial_id",
    "question_id",
    "analysis_unit",
    "target_population",
    "time_zero",
    "treatment",
    "followup",
    "outcomes",
    "baseline_covariates",
    "forbidden_post_treatment_fields",
    "intercurrent_events",
}
REQUIRED_ESTIMAND_FIELDS = {
    "estimand_id",
    "question_id",
    "trial_id",
    "estimand_type",
    "population_scope",
    "population_id",
    "treatment_strategy",
    "comparator_strategy",
    "outcome_id",
    "time_horizon_days",
    "effect_measure",
    "analysis_unit",
    "notation",
    "identification_status",
    "estimator_status",
    "assumptions",
}
REQUIRED_ASSUMPTIONS = {"consistency", "exchangeability", "positivity", "interference"}
SUPPORTED_UNITS = {"user_id"}
ESTIMAND_SCOPES = {
    "ATE": "eligible_population",
    "ATT": "treated_population",
    "LATE": "compliers",
}
PRE_IDENTIFICATION_CLAIM = "design_ready_for_identification"
FORBIDDEN_BASELINE_TIMINGS = {"treatment", "post_treatment", "outcome"}


def passed(
    check_id: str,
    observed: Any = None,
    expected: Any = None,
    severity: str = "error",
) -> dict[str, Any]:
    return {
        "id": check_id,
        "severity": severity,
        "valid": True,
        "observed": observed,
        "expected": expected,
        "sample": [],
    }


def failed(
    check_id: str,
    observed: Any,
    expected: Any,
    sample: list[Any] | None = None,
    severity: str = "error",
) -> dict[str, Any]:
    return {
        "id": check_id,
        "severity": severity,
        "valid": False,
        "observed": observed,
        "expected": expected,
        "sample": sample or [],
    }


def read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as source:
        value = json.load(source)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized == "true":
            return True
        if normalized == "false":
            return False
    raise ValueError(f"expected boolean, got {value!r}")


def parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def non_empty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def contract_table(contract: dict[str, Any], table: str) -> dict[str, Any] | None:
    tables = contract.get("tables")
    if not isinstance(tables, dict):
        return None
    value = tables.get(table)
    return value if isinstance(value, dict) else None


def contract_column(
    contract: dict[str, Any],
    table: str,
    column: str,
) -> dict[str, Any] | None:
    table_spec = contract_table(contract, table)
    columns = table_spec.get("columns") if table_spec else None
    if not isinstance(columns, dict):
        return None
    value = columns.get(column)
    return value if isinstance(value, dict) else None


def required_fields_check(
    payload: dict[str, Any],
    required: set[str],
    check_id: str,
) -> dict[str, Any]:
    missing = sorted(required - set(payload))
    if missing:
        return failed(check_id, missing, "all required fields", missing)
    return passed(check_id, len(required), "all required fields")


def validate_ids(
    question: dict[str, Any],
    trial: dict[str, Any],
    estimand: dict[str, Any],
) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    comparisons = [
        ("trial.question_id", trial.get("question_id"), question.get("question_id")),
        ("estimand.question_id", estimand.get("question_id"), question.get("question_id")),
        ("question.estimand_id", question.get("estimand_id"), estimand.get("estimand_id")),
        (
            "target_population",
            trial.get("target_population", {}).get("population_id"),
            question.get("target_population_id"),
        ),
        (
            "estimand.population_id",
            estimand.get("population_id"),
            question.get("target_population_id"),
        ),
        (
            "time_zero",
            trial.get("time_zero", {}).get("time_zero_id"),
            question.get("time_zero_id"),
        ),
        (
            "treatment",
            trial.get("treatment", {}).get("treatment_id"),
            question.get("treatment_id"),
        ),
        ("estimand.trial_id", estimand.get("trial_id"), trial.get("trial_id")),
        ("estimand.outcome_id", estimand.get("outcome_id"), question.get("primary_outcome_id")),
    ]
    for field, observed, expected in comparisons:
        if observed != expected:
            errors.append({"field": field, "observed": observed, "expected": expected})
    if errors:
        return failed(
            "spec_ids_align", len(errors), "question, trial and estimand ids align", errors
        )
    return passed("spec_ids_align", question.get("question_id"), "all ids align")


def validate_analysis_unit(
    trial: dict[str, Any],
    estimand: dict[str, Any],
) -> dict[str, Any]:
    unit = trial.get("analysis_unit")
    if unit not in SUPPORTED_UNITS or estimand.get("analysis_unit") != unit:
        return failed(
            "analysis_unit_supported",
            {"trial": unit, "estimand": estimand.get("analysis_unit")},
            sorted(SUPPORTED_UNITS),
        )
    return passed("analysis_unit_supported", unit, sorted(SUPPORTED_UNITS))


def referenced_field_errors(
    references: list[dict[str, Any]],
    contract: dict[str, Any],
    *,
    forbid_timings: set[str] | None = None,
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    for reference in references:
        if not isinstance(reference, dict):
            errors.append({"reference": reference, "reason": "reference must be an object"})
            continue
        table = reference.get("table")
        field = reference.get("field")
        column = contract_column(contract, str(table), str(field))
        if column is None:
            errors.append({"table": table, "field": field, "reason": "missing from data contract"})
            continue
        if forbid_timings and column.get("timing") in forbid_timings:
            errors.append(
                {
                    "table": table,
                    "field": field,
                    "timing": column.get("timing"),
                    "reason": (
                        "post-treatment field cannot define baseline population or covariates"
                    ),
                }
            )
    return errors


def validate_target_population(
    trial: dict[str, Any],
    contract: dict[str, Any],
) -> dict[str, Any]:
    population = trial.get("target_population")
    if not isinstance(population, dict):
        return failed(
            "target_population_contract", type(population).__name__, "target population object"
        )
    criteria = population.get("criteria")
    if not isinstance(criteria, list) or not criteria:
        return failed("target_population_contract", criteria, "non-empty criteria list")
    errors = referenced_field_errors(
        criteria,
        contract,
        forbid_timings=FORBIDDEN_BASELINE_TIMINGS,
    )
    for criterion in criteria:
        if isinstance(criterion, dict) and criterion.get("operator") not in {
            "==",
            ">=",
            "<=",
            ">",
            "<",
        }:
            errors.append(
                {
                    "table": criterion.get("table"),
                    "field": criterion.get("field"),
                    "operator": criterion.get("operator"),
                    "reason": "unsupported operator",
                }
            )
    has_test_exclusion = any(
        criterion.get("table") == "users"
        and criterion.get("field") == "is_test_user"
        and criterion.get("operator") == "=="
        and criterion.get("value") is False
        for criterion in criteria
        if isinstance(criterion, dict)
    )
    if not has_test_exclusion:
        errors.append({"reason": "target population must explicitly exclude test users"})
    if errors:
        return failed(
            "target_population_contract",
            len(errors),
            "baseline-only criteria with explicit test-user exclusion",
            errors,
        )
    return passed(
        "target_population_contract",
        population.get("population_id"),
        "baseline-only criteria with explicit test-user exclusion",
    )


def validate_treatment(
    question: dict[str, Any],
    trial: dict[str, Any],
    contract: dict[str, Any],
) -> dict[str, Any]:
    treatment = trial.get("treatment")
    errors: list[dict[str, Any]] = []
    if not isinstance(treatment, dict):
        return failed("treatment_definition_precise", type(treatment).__name__, "treatment object")
    required = {
        "treatment_id",
        "source_table",
        "column",
        "timing_column",
        "assignment_type",
        "grace_period_hours",
        "contrast",
        "strategies",
    }
    missing = sorted(required - set(treatment))
    if missing:
        errors.append({"reason": "missing treatment fields", "fields": missing})
    for field_name in ("column", "timing_column", "offer_column", "offer_timing_column"):
        if (
            field_name in treatment
            and contract_column(
                contract,
                str(treatment.get("source_table")),
                str(treatment.get(field_name)),
            )
            is None
        ):
            errors.append({"field": field_name, "reason": "column missing from data contract"})
    grace = treatment.get("grace_period_hours")
    if not isinstance(grace, int) or grace <= 0:
        errors.append({"field": "grace_period_hours", "value": grace})
    strategies = treatment.get("strategies")
    if not isinstance(strategies, list) or len(strategies) != 2:
        errors.append({"field": "strategies", "reason": "exactly two strategies required"})
    else:
        strategy_ids = {
            strategy.get("strategy_id") for strategy in strategies if isinstance(strategy, dict)
        }
        values = {strategy.get("value") for strategy in strategies if isinstance(strategy, dict)}
        if strategy_ids != {question.get("treatment_id"), question.get("comparator_id")}:
            errors.append(
                {
                    "field": "strategies.strategy_id",
                    "observed": sorted(str(value) for value in strategy_ids),
                    "expected": sorted(
                        [question.get("treatment_id"), question.get("comparator_id")]
                    ),
                }
            )
        if values != {True, False}:
            errors.append({"field": "strategies.value", "observed": list(values)})
        for strategy in strategies:
            if not isinstance(strategy, dict):
                continue
            if not non_empty_text(strategy.get("operational_definition")):
                errors.append(
                    {
                        "strategy_id": strategy.get("strategy_id"),
                        "reason": "missing operational definition",
                    }
                )
            versions = strategy.get("versions")
            if (
                not isinstance(versions, list)
                or not versions
                or not all(non_empty_text(item) for item in versions)
            ):
                errors.append(
                    {
                        "strategy_id": strategy.get("strategy_id"),
                        "reason": "treatment versions must be explicit",
                    }
                )
    if errors:
        return failed(
            "treatment_definition_precise",
            len(errors),
            "two operational strategies with versions and grace period",
            errors,
        )
    return passed(
        "treatment_definition_precise",
        treatment.get("contrast"),
        "two operational strategies with versions and grace period",
    )


def validate_outcomes(
    question: dict[str, Any],
    trial: dict[str, Any],
    estimand: dict[str, Any],
    contract: dict[str, Any],
) -> dict[str, Any]:
    outcomes = trial.get("outcomes")
    errors: list[dict[str, Any]] = []
    if not isinstance(outcomes, list) or not outcomes:
        return failed("outcome_contract", outcomes, "non-empty outcome list")
    by_id = {
        outcome.get("outcome_id"): outcome
        for outcome in outcomes
        if isinstance(outcome, dict) and isinstance(outcome.get("outcome_id"), str)
    }
    primary = by_id.get(question.get("primary_outcome_id"))
    if primary is None or primary.get("role") != "primary":
        errors.append({"reason": "primary outcome does not resolve to role=primary"})
    followup = trial.get("followup")
    end_days = followup.get("end_days") if isinstance(followup, dict) else None
    for outcome in outcomes:
        if not isinstance(outcome, dict):
            errors.append({"outcome": outcome, "reason": "outcome must be an object"})
            continue
        table = outcome.get("source_table")
        column = outcome.get("column")
        contract_spec = contract_column(contract, str(table), str(column))
        if contract_spec is None:
            errors.append(
                {"outcome_id": outcome.get("outcome_id"), "reason": "column missing from contract"}
            )
        elif contract_spec.get("timing") != "outcome":
            errors.append(
                {
                    "outcome_id": outcome.get("outcome_id"),
                    "timing": contract_spec.get("timing"),
                    "reason": "outcome column must have outcome timing",
                }
            )
        window = outcome.get("window_days")
        if not isinstance(window, int) or window <= 0:
            errors.append({"outcome_id": outcome.get("outcome_id"), "window_days": window})
        elif not isinstance(end_days, int) or window > end_days:
            errors.append(
                {
                    "outcome_id": outcome.get("outcome_id"),
                    "window_days": window,
                    "followup_end_days": end_days,
                }
            )
    if estimand.get("time_horizon_days") != (primary or {}).get("window_days"):
        errors.append(
            {
                "field": "estimand.time_horizon_days",
                "observed": estimand.get("time_horizon_days"),
                "expected": (primary or {}).get("window_days"),
            }
        )
    if (
        primary
        and primary.get("type") == "binary"
        and estimand.get("effect_measure")
        not in {
            "risk_difference",
            "risk_ratio",
            "odds_ratio",
        }
    ):
        errors.append(
            {
                "field": "effect_measure",
                "observed": estimand.get("effect_measure"),
                "expected": "binary-outcome effect measure",
            }
        )
    if errors:
        return failed(
            "outcome_contract", len(errors), "declared outcomes fit follow-up and estimand", errors
        )
    return passed("outcome_contract", sorted(by_id), "declared outcomes fit follow-up and estimand")


def validate_baseline_fields(
    trial: dict[str, Any],
    contract: dict[str, Any],
) -> dict[str, Any]:
    baseline = trial.get("baseline_covariates")
    forbidden = trial.get("forbidden_post_treatment_fields")
    errors: list[dict[str, Any]] = []
    if not isinstance(baseline, list) or not baseline:
        errors.append({"field": "baseline_covariates", "reason": "non-empty list required"})
    else:
        errors.extend(
            referenced_field_errors(
                baseline,
                contract,
                forbid_timings=FORBIDDEN_BASELINE_TIMINGS,
            )
        )
    if not isinstance(forbidden, list) or not forbidden:
        errors.append(
            {"field": "forbidden_post_treatment_fields", "reason": "non-empty list required"}
        )
    else:
        for reference in forbidden:
            column = contract_column(
                contract,
                str(reference.get("table")),
                str(reference.get("field")),
            )
            if column is None or column.get("timing") not in {"post_treatment", "outcome"}:
                errors.append(
                    {
                        "reference": reference,
                        "reason": (
                            "forbidden field must resolve to post-treatment or outcome timing"
                        ),
                    }
                )
    if errors:
        return failed(
            "baseline_and_forbidden_fields", len(errors), "timing-safe covariate contract", errors
        )
    return passed(
        "baseline_and_forbidden_fields",
        {"baseline": len(baseline), "forbidden": len(forbidden)},
        "timing-safe covariate contract",
    )


def validate_estimand(estimand: dict[str, Any]) -> dict[str, Any]:
    estimand_type = estimand.get("estimand_type")
    expected_scope = ESTIMAND_SCOPES.get(str(estimand_type))
    errors: list[dict[str, Any]] = []
    if expected_scope is None:
        errors.append({"field": "estimand_type", "value": estimand_type})
    elif estimand.get("population_scope") != expected_scope:
        errors.append(
            {
                "field": "population_scope",
                "estimand_type": estimand_type,
                "observed": estimand.get("population_scope"),
                "expected": expected_scope,
            }
        )
    if estimand_type == "LATE" and not isinstance(estimand.get("instrument"), dict):
        errors.append({"field": "instrument", "reason": "LATE requires an explicit instrument"})
    if not isinstance(estimand.get("time_horizon_days"), int) or estimand["time_horizon_days"] <= 0:
        errors.append({"field": "time_horizon_days", "value": estimand.get("time_horizon_days")})
    if not non_empty_text(estimand.get("notation")):
        errors.append({"field": "notation", "reason": "counterfactual notation is required"})
    if errors:
        return failed(
            "estimand_population_alignment",
            len(errors),
            "estimand type matches population scope",
            errors,
        )
    return passed(
        "estimand_population_alignment",
        {"type": estimand_type, "scope": estimand.get("population_scope")},
        "estimand type matches population scope",
    )


def validate_assumptions(estimand: dict[str, Any]) -> dict[str, Any]:
    assumptions = estimand.get("assumptions")
    errors: list[dict[str, Any]] = []
    if not isinstance(assumptions, dict):
        return failed(
            "causal_assumptions_declared", type(assumptions).__name__, sorted(REQUIRED_ASSUMPTIONS)
        )
    missing = sorted(REQUIRED_ASSUMPTIONS - set(assumptions))
    if missing:
        errors.append({"reason": "missing assumptions", "assumptions": missing})
    for name in sorted(REQUIRED_ASSUMPTIONS & set(assumptions)):
        assumption = assumptions[name]
        if not isinstance(assumption, dict):
            errors.append({"assumption": name, "reason": "assumption must be an object"})
            continue
        if not non_empty_text(assumption.get("statement")):
            errors.append({"assumption": name, "reason": "statement is required"})
        if assumption.get("status") not in {"untested", "partially_testable", "design_assumption"}:
            errors.append({"assumption": name, "status": assumption.get("status")})
        evidence = assumption.get("evidence_needed")
        if not isinstance(evidence, list) or not evidence:
            errors.append({"assumption": name, "reason": "evidence_needed is required"})
    if errors:
        return failed(
            "causal_assumptions_declared",
            len(errors),
            "consistency, exchangeability, positivity and interference",
            errors,
        )
    return passed(
        "causal_assumptions_declared",
        sorted(assumptions),
        sorted(REQUIRED_ASSUMPTIONS),
    )


def validate_claim_status(
    question: dict[str, Any],
    estimand: dict[str, Any],
) -> dict[str, Any]:
    observed = {
        "claim": question.get("current_claim_status"),
        "identification": estimand.get("identification_status"),
        "estimator": estimand.get("estimator_status"),
    }
    expected = {
        "claim": PRE_IDENTIFICATION_CLAIM,
        "identification": "not_yet_identified",
        "estimator": "not_selected",
    }
    if observed != expected or PRE_IDENTIFICATION_CLAIM not in question.get(
        "allowed_claim_statuses", []
    ):
        return failed(
            "claim_status_is_pre_identification",
            observed,
            expected,
            [{"reason": "lesson 13/01 cannot claim an identified or estimated effect"}],
        )
    return passed("claim_status_is_pre_identification", observed, expected)


def table_rows(data_root: Path, contract: dict[str, Any], table: str) -> list[dict[str, str]]:
    table_spec = contract_table(contract, table)
    if table_spec is None or not non_empty_text(table_spec.get("file")):
        raise ValueError(f"missing table {table!r} in data contract")
    return read_csv(data_root / table_spec["file"])


def duplicate_values(rows: list[dict[str, str]], column: str) -> list[str]:
    counts = Counter(row.get(column, "") for row in rows)
    return sorted(value for value, count in counts.items() if value and count > 1)


def validate_data_grain_and_columns(
    data_root: Path,
    contract: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, list[dict[str, str]]]]:
    tables = {
        table: table_rows(data_root, contract, table)
        for table in ("users", "pre_treatment_behavior", "onboarding_assistance", "outcomes")
    }
    errors: list[dict[str, Any]] = []
    for table, rows in tables.items():
        table_spec = contract_table(contract, table) or {}
        required = set((table_spec.get("columns") or {}).keys())
        observed = set(rows[0]) if rows else set()
        missing = sorted(required - observed)
        if missing:
            errors.append({"table": table, "reason": "missing columns", "columns": missing})
        duplicates = duplicate_values(rows, "user_id")
        if duplicates:
            errors.append({"table": table, "reason": "duplicate user_id", "user_ids": duplicates})
    user_ids = {row["user_id"] for row in tables["users"]}
    for table in ("pre_treatment_behavior", "onboarding_assistance", "outcomes"):
        unknown = sorted({row["user_id"] for row in tables[table]} - user_ids)
        missing = sorted(user_ids - {row["user_id"] for row in tables[table]})
        if unknown:
            errors.append({"table": table, "reason": "unknown user_id", "user_ids": unknown})
        if missing:
            errors.append({"table": table, "reason": "missing users", "user_ids": missing})
    if errors:
        return (
            failed(
                "data_columns_grain_relationships",
                len(errors),
                "complete one-row-per-user analysis tables",
                errors,
            ),
            tables,
        )
    return (
        passed(
            "data_columns_grain_relationships",
            {table: len(rows) for table, rows in tables.items()},
            "complete one-row-per-user analysis tables",
        ),
        tables,
    )


def coerce_contract_value(value: Any, type_name: str) -> Any:
    if type_name == "boolean":
        return parse_bool(value)
    if type_name == "integer":
        return int(value)
    if type_name == "decimal":
        return float(value)
    return value


def criterion_matches(
    value: Any,
    operator: str,
    expected: Any,
) -> bool:
    if operator == "==":
        return value == expected
    if operator == ">=":
        return value >= expected
    if operator == "<=":
        return value <= expected
    if operator == ">":
        return value > expected
    if operator == "<":
        return value < expected
    raise ValueError(f"unsupported operator {operator!r}")


def build_target_population(
    trial: dict[str, Any],
    contract: dict[str, Any],
    tables: dict[str, list[dict[str, str]]],
) -> list[str]:
    by_table = {
        table: {row["user_id"]: row for row in rows}
        for table, rows in tables.items()
        if rows and "user_id" in rows[0]
    }
    user_ids = sorted(by_table["users"])
    criteria = trial["target_population"]["criteria"]
    result: list[str] = []
    for user_id in user_ids:
        matches = True
        for criterion in criteria:
            table = criterion["table"]
            field = criterion["field"]
            row = by_table[table][user_id]
            column = contract_column(contract, table, field) or {}
            observed = coerce_contract_value(row[field], str(column.get("type")))
            expected = coerce_contract_value(criterion["value"], str(column.get("type")))
            if not criterion_matches(observed, criterion["operator"], expected):
                matches = False
                break
        if matches:
            result.append(user_id)
    return result


def validate_data_timing(
    trial: dict[str, Any],
    tables: dict[str, list[dict[str, str]]],
) -> dict[str, Any]:
    baseline = {row["user_id"]: row for row in tables["pre_treatment_behavior"]}
    assistance = {row["user_id"]: row for row in tables["onboarding_assistance"]}
    outcomes = {row["user_id"]: row for row in tables["outcomes"]}
    treatment = trial["treatment"]
    grace = timedelta(hours=int(treatment["grace_period_hours"]))
    max_window = max(outcome["window_days"] for outcome in trial["outcomes"])
    errors: list[dict[str, Any]] = []

    for user_id, treatment_row in assistance.items():
        time_zero = parse_datetime(baseline[user_id]["time_zero"])
        treatment_time_zero = parse_datetime(treatment_row["time_zero"])
        if time_zero is None or treatment_time_zero != time_zero:
            errors.append({"user_id": user_id, "reason": "time_zero mismatch or invalid"})
            continue
        offered = parse_bool(treatment_row[treatment["offer_column"]])
        received = parse_bool(treatment_row[treatment["column"]])
        offered_at = parse_datetime(treatment_row[treatment["offer_timing_column"]])
        started_at = parse_datetime(treatment_row[treatment["timing_column"]])
        if offered and (offered_at is None or offered_at < time_zero):
            errors.append({"user_id": user_id, "reason": "offer is missing or before time zero"})
        if not offered and offered_at is not None:
            errors.append({"user_id": user_id, "reason": "non-offered user has offered_at"})
        if received:
            if not offered:
                errors.append({"user_id": user_id, "reason": "received treatment without offer"})
            if started_at is None or not time_zero <= started_at <= time_zero + grace:
                errors.append(
                    {
                        "user_id": user_id,
                        "reason": "treatment start is outside time zero and grace period",
                        "started_at": treatment_row[treatment["timing_column"]],
                    }
                )
        elif started_at is not None:
            errors.append({"user_id": user_id, "reason": "untreated user has started_at"})
        followup_end = parse_datetime(outcomes[user_id]["followup_end_at"])
        if followup_end is None or followup_end < time_zero + timedelta(days=max_window):
            errors.append(
                {
                    "user_id": user_id,
                    "reason": "follow-up does not cover declared outcomes",
                    "followup_end_at": outcomes[user_id]["followup_end_at"],
                }
            )
    if errors:
        return failed(
            "time_zero_treatment_followup_order",
            len(errors),
            "treatment follows time zero and follow-up covers outcomes",
            errors,
        )
    return passed(
        "time_zero_treatment_followup_order",
        len(assistance),
        "treatment follows time zero and follow-up covers outcomes",
    )


def validate_specs(
    question: dict[str, Any],
    trial: dict[str, Any],
    estimand: dict[str, Any],
    contract: dict[str, Any],
    data_root: Path,
) -> dict[str, Any]:
    checks = [
        required_fields_check(question, REQUIRED_QUESTION_FIELDS, "question_required_fields"),
        required_fields_check(trial, REQUIRED_TRIAL_FIELDS, "target_trial_required_fields"),
        required_fields_check(estimand, REQUIRED_ESTIMAND_FIELDS, "estimand_required_fields"),
    ]
    if any(not check["valid"] for check in checks):
        return {"valid": False, "checks": checks, "summary": {}}

    checks.extend(
        [
            validate_ids(question, trial, estimand),
            validate_analysis_unit(trial, estimand),
            validate_target_population(trial, contract),
            validate_treatment(question, trial, contract),
            validate_outcomes(question, trial, estimand, contract),
            validate_baseline_fields(trial, contract),
            validate_estimand(estimand),
            validate_assumptions(estimand),
            validate_claim_status(question, estimand),
        ]
    )
    if any(not check["valid"] and check["severity"] == "error" for check in checks):
        return {"valid": False, "checks": checks, "summary": {}}

    data_check, tables = validate_data_grain_and_columns(data_root, contract)
    checks.append(data_check)
    if data_check["valid"]:
        checks.append(validate_data_timing(trial, tables))
    if all(check["valid"] or check["severity"] != "error" for check in checks):
        target_population = build_target_population(trial, contract, tables)
        assistance = {row["user_id"]: row for row in tables["onboarding_assistance"]}
        treated = sum(
            parse_bool(assistance[user_id][trial["treatment"]["column"]])
            for user_id in target_population
        )
        checks.append(
            failed(
                "observational_assignment_requires_identification",
                trial["treatment"]["assignment_type"],
                "causal DAG and identification argument before effect estimation",
                [
                    {
                        "reason": (
                            "valid question and estimand do not make the "
                            "observational effect identified"
                        )
                    }
                ],
                severity="warning",
            )
        )
        summary = {
            "question_id": question["question_id"],
            "estimand_id": estimand["estimand_id"],
            "estimand_type": estimand["estimand_type"],
            "population_scope": estimand["population_scope"],
            "effect_measure": estimand["effect_measure"],
            "target_population_users": len(target_population),
            "treated_users": treated,
            "comparator_users": len(target_population) - treated,
            "identification_status": estimand["identification_status"],
            "claim_status": question["current_claim_status"],
            "warning_count": sum(
                not check["valid"] and check["severity"] == "warning" for check in checks
            ),
        }
    else:
        summary = {}
    valid = all(check["valid"] for check in checks if check["severity"] == "error")
    return {"valid": valid, "checks": checks, "summary": summary}


def run(
    question_path: Path,
    trial_path: Path,
    estimand_path: Path,
    contract_path: Path,
    data_root: Path,
) -> dict[str, Any]:
    return validate_specs(
        read_json(question_path),
        read_json(trial_path),
        read_json(estimand_path),
        read_json(contract_path),
        data_root,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Validate a causal question, target-trial specification and "
            "estimand before identification."
        )
    )
    parser.add_argument("--question", type=Path, required=True)
    parser.add_argument("--target-trial", type=Path, required=True)
    parser.add_argument("--estimand", type=Path, required=True)
    parser.add_argument("--data-contract", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = run(
            args.question,
            args.target_trial,
            args.estimand,
            args.data_contract,
            args.data_root,
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"valid": False, "error": str(error)}, ensure_ascii=False, indent=2))
        raise SystemExit(2) from error
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    sys.stdout.write(rendered)
    raise SystemExit(0 if report["valid"] else 1)


if __name__ == "__main__":
    main()
