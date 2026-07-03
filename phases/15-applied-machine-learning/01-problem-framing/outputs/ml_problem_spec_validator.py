from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

REQUIRED_SPEC_FIELDS = {
    "problem_id",
    "business_decision",
    "prediction_unit",
    "target_name",
    "target_definition",
    "positive_class",
    "negative_class",
    "prediction_time",
    "label_window",
    "eligible_population",
    "decision_action",
    "decision_budget",
    "business_costs",
    "allowed_feature_sources",
    "forbidden_feature_sources",
    "split_policy",
    "baseline_policy",
    "metric_policy",
    "threshold_policy",
    "calibration_policy",
    "segment_policy",
    "model_card_policy",
    "known_limitations",
    "rerun_instructions",
}
REQUIRED_SNAPSHOT_COLUMNS = {
    "snapshot_id",
    "user_id",
    "prediction_time",
    "trial_end_at",
    "segment_id",
    "eligible_for_offer",
    "days_until_trial_end",
    "split_group",
}
REQUIRED_LABEL_COLUMNS = {
    "snapshot_id",
    "target_name",
    "label_observed_at",
    "churned_14d",
    "label_window_complete",
}
REQUIRED_FEATURE_COLUMNS = {
    "source_id",
    "source_table",
    "timing",
    "available_at_policy",
    "max_observed_at",
    "allowed",
    "reason",
}
ALLOWED_FEATURE_TIMINGS = {
    "known_before_prediction_time",
    "lookback_before_prediction_time",
}
FORBIDDEN_FEATURE_TIMINGS = {
    "label_after_prediction_time",
    "post_prediction_time",
    "intervention_after_prediction_time",
}


class MLProblemSpecError(ValueError):
    """Raised when lesson inputs cannot be parsed."""


def passed(check_id: str, observed: Any = None, expected: Any = None) -> dict[str, Any]:
    return {
        "id": check_id,
        "severity": "error",
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
    *,
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
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise MLProblemSpecError(f"{path} must contain a JSON object")
    return value


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open(encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        return list(reader), list(reader.fieldnames or [])


def parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized == "true":
            return True
        if normalized == "false":
            return False
    raise MLProblemSpecError(f"expected boolean, got {value!r}")


def parse_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise MLProblemSpecError(f"expected integer, got {value!r}") from error


def parse_timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise MLProblemSpecError(f"{field} must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise MLProblemSpecError(f"{field} must be an ISO timestamp: {value}") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise MLProblemSpecError(f"{field} must be timezone-aware: {value}")
    return parsed


def non_empty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def required_fields_check(
    payload: dict[str, Any], required: set[str], check_id: str
) -> dict[str, Any]:
    missing = sorted(required - set(payload))
    if missing:
        return failed(check_id, missing, "all required fields", missing)
    return passed(check_id, len(required), "all required fields")


def validate_business_decision(spec: dict[str, Any]) -> dict[str, Any]:
    budget = spec.get("decision_budget")
    costs = spec.get("business_costs")
    errors: list[dict[str, Any]] = []
    if not non_empty_text(spec.get("business_decision")):
        errors.append({"field": "business_decision", "reason": "decision must be explicit"})
    if not non_empty_text(spec.get("decision_action")):
        errors.append({"field": "decision_action", "reason": "action must be explicit"})
    if not isinstance(budget, dict) or parse_int(budget.get("max_actions", 0)) <= 0:
        errors.append({"field": "decision_budget", "reason": "positive action budget required"})
    if not isinstance(costs, dict):
        errors.append({"field": "business_costs", "reason": "cost object required"})
    elif not {"false_positive", "false_negative"} <= set(costs):
        errors.append({"field": "business_costs", "reason": "FP and FN costs required"})
    if errors:
        return failed(
            "business_decision_precedes_model",
            len(errors),
            "decision, action, budget, FP/FN costs",
            errors,
        )
    return passed(
        "business_decision_precedes_model",
        {"action": spec["decision_action"], "budget": budget["max_actions"]},
        "decision, action, budget, FP/FN costs",
    )


def validate_policy_sections(spec: dict[str, Any]) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    split = spec.get("split_policy")
    metric = spec.get("metric_policy")
    threshold = spec.get("threshold_policy")
    baseline = spec.get("baseline_policy")
    calibration = spec.get("calibration_policy")
    segment = spec.get("segment_policy")
    model_card = spec.get("model_card_policy")
    if not isinstance(split, dict) or not {
        "group_key",
        "time_key",
        "validation_role",
        "test_role",
    } <= set(split):
        errors.append({"field": "split_policy", "reason": "group/time and role contract required"})
    if not isinstance(metric, dict) or not non_empty_text(metric.get("primary_metric")):
        errors.append({"field": "metric_policy", "reason": "primary metric required"})
    if not isinstance(threshold, dict) or threshold.get("selection_data") != "validation":
        errors.append(
            {"field": "threshold_policy", "reason": "threshold must be selected on validation"}
        )
    if not isinstance(baseline, dict) or not baseline.get("required_baselines"):
        errors.append({"field": "baseline_policy", "reason": "simple baseline must be required"})
    if not isinstance(calibration, dict) or calibration.get("required") is not True:
        errors.append(
            {"field": "calibration_policy", "reason": "calibration decision must be predeclared"}
        )
    if not isinstance(segment, dict) or not segment.get("required_slices"):
        errors.append({"field": "segment_policy", "reason": "segment slices must be predeclared"})
    if not isinstance(model_card, dict) or not non_empty_text(model_card.get("intended_use")):
        errors.append({"field": "model_card_policy", "reason": "intended use is required"})
    if errors:
        return failed(
            "evaluation_policies_predeclared",
            len(errors),
            "split, baseline, metric, threshold, calibration, segment and model-card policies",
            errors,
        )
    return passed(
        "evaluation_policies_predeclared",
        {
            "primary_metric": metric["primary_metric"],
            "threshold_selection_data": threshold["selection_data"],
        },
        "policies declared before fit",
    )


def validate_prediction_unit(
    spec: dict[str, Any],
    snapshots: list[dict[str, str]],
    snapshot_columns: list[str],
) -> dict[str, Any]:
    unit = spec.get("prediction_unit")
    errors: list[dict[str, Any]] = []
    if not isinstance(unit, dict):
        return failed("prediction_unit_is_snapshot", type(unit).__name__, "prediction unit object")
    key = unit.get("key")
    if key != "snapshot_id":
        errors.append({"field": "prediction_unit.key", "observed": key, "expected": "snapshot_id"})
    missing = sorted(REQUIRED_SNAPSHOT_COLUMNS - set(snapshot_columns))
    if missing:
        errors.append({"field": "ml_scoring_snapshots", "missing_columns": missing})
    if not missing and snapshots:
        key_counts = Counter(row[key] for row in snapshots)
        duplicate_keys = sorted(value for value, count in key_counts.items() if count > 1)
        if duplicate_keys:
            errors.append(
                {"field": key, "reason": "duplicate prediction rows", "sample": duplicate_keys[:10]}
            )
        grain_counts = Counter((row["user_id"], row["prediction_time"]) for row in snapshots)
        duplicate_grain = [key for key, count in grain_counts.items() if count > 1]
        if duplicate_grain:
            errors.append(
                {
                    "field": "user_id + prediction_time",
                    "reason": "prediction grain duplicated",
                    "sample": ["/".join(item) for item in duplicate_grain[:10]],
                }
            )
    if errors:
        return failed("prediction_unit_is_snapshot", len(errors), "unique snapshot_id rows", errors)
    return passed("prediction_unit_is_snapshot", len(snapshots), "unique snapshot_id rows")


def criterion_matches(observed: Any, operator: str, expected: Any) -> bool:
    if operator == "==":
        return observed == expected
    if operator == ">=":
        return observed >= expected
    if operator == "<=":
        return observed <= expected
    if operator == ">":
        return observed > expected
    if operator == "<":
        return observed < expected
    raise MLProblemSpecError(f"unsupported operator: {operator}")


def coerce_like(value: Any, expected: Any) -> Any:
    if isinstance(expected, bool):
        return parse_bool(value)
    if isinstance(expected, int):
        return parse_int(value)
    return value


def eligible_snapshot_ids(
    spec: dict[str, Any],
    snapshots: list[dict[str, str]],
) -> tuple[list[str], list[dict[str, Any]]]:
    population = spec.get("eligible_population")
    errors: list[dict[str, Any]] = []
    if not isinstance(population, dict):
        return [], [{"field": "eligible_population", "reason": "object required"}]
    criteria = population.get("criteria")
    if not isinstance(criteria, list) or not criteria:
        return [], [{"field": "eligible_population.criteria", "reason": "non-empty list required"}]
    selected: list[str] = []
    for row in snapshots:
        include = True
        for criterion in criteria:
            if not isinstance(criterion, dict):
                errors.append({"criterion": criterion, "reason": "criterion must be an object"})
                include = False
                continue
            field = criterion.get("field")
            operator = criterion.get("operator")
            if field not in row:
                errors.append({"field": field, "reason": "criterion field missing from snapshots"})
                include = False
                continue
            try:
                observed = coerce_like(row[field], criterion.get("value"))
                expected = criterion.get("value")
                if not criterion_matches(observed, str(operator), expected):
                    include = False
                    break
            except MLProblemSpecError as error:
                errors.append({"field": field, "reason": str(error)})
                include = False
        if include:
            selected.append(row["snapshot_id"])
    return selected, errors


def validate_population_and_decision_timing(
    spec: dict[str, Any],
    snapshots: list[dict[str, str]],
) -> tuple[dict[str, Any], list[str]]:
    selected, errors = eligible_snapshot_ids(spec, snapshots)
    expected_gap = (
        (spec.get("prediction_time") or {}).get("relative_to_trial_end_days")
        if isinstance(spec.get("prediction_time"), dict)
        else None
    )
    timing_errors: list[dict[str, Any]] = []
    for row in snapshots:
        if row["snapshot_id"] not in selected:
            continue
        prediction_time = parse_timestamp(row["prediction_time"], "prediction_time")
        trial_end_at = parse_timestamp(row["trial_end_at"], "trial_end_at")
        days_until_trial_end = parse_int(row["days_until_trial_end"])
        if expected_gap is not None and days_until_trial_end != expected_gap:
            timing_errors.append(
                {
                    "snapshot_id": row["snapshot_id"],
                    "days_until_trial_end": days_until_trial_end,
                    "expected": expected_gap,
                }
            )
        if trial_end_at - prediction_time != timedelta(days=days_until_trial_end):
            timing_errors.append(
                {
                    "snapshot_id": row["snapshot_id"],
                    "reason": "trial_end_at does not match prediction_time + days_until_trial_end",
                }
            )
    all_errors = errors + timing_errors
    if all_errors or not selected:
        return (
            failed(
                "eligible_population_and_prediction_time",
                len(all_errors) if all_errors else 0,
                "eligible rows scored seven days before trial end",
                all_errors,
            ),
            selected,
        )
    return (
        passed(
            "eligible_population_and_prediction_time",
            len(selected),
            "eligible rows scored seven days before trial end",
        ),
        selected,
    )


def validate_target_contract(
    spec: dict[str, Any],
    snapshots: list[dict[str, str]],
    labels: list[dict[str, str]],
    label_columns: list[str],
    eligible_ids: list[str],
) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    missing_columns = sorted(REQUIRED_LABEL_COLUMNS - set(label_columns))
    if missing_columns:
        errors.append({"field": "ml_labels", "missing_columns": missing_columns})
        return failed(
            "target_has_horizon_and_classes", len(errors), "valid target label table", errors
        )

    target_definition = spec.get("target_definition")
    label_window = spec.get("label_window")
    positive_class = spec.get("positive_class")
    negative_class = spec.get("negative_class")
    if not isinstance(target_definition, dict) or not isinstance(label_window, dict):
        errors.append({"field": "target_definition/label_window", "reason": "objects required"})
    if not isinstance(positive_class, dict) or not isinstance(negative_class, dict):
        errors.append({"field": "positive_class/negative_class", "reason": "both classes required"})
    elif positive_class.get("value") == negative_class.get("value"):
        errors.append(
            {"field": "positive_class", "reason": "positive and negative class values must differ"}
        )
    if errors:
        return failed("target_has_horizon_and_classes", len(errors), "target contract", errors)

    target_name = spec["target_name"]
    target_column = str(target_definition.get("target_column"))
    horizon_days = parse_int(label_window.get("duration_days"))
    if horizon_days <= 0:
        errors.append(
            {"field": "label_window.duration_days", "reason": "positive horizon required"}
        )
    snapshots_by_id = {row["snapshot_id"]: row for row in snapshots}
    label_counts = Counter(row["snapshot_id"] for row in labels)
    duplicate_labels = sorted(
        snapshot_id for snapshot_id, count in label_counts.items() if count > 1
    )
    if duplicate_labels:
        errors.append(
            {
                "field": "ml_labels.snapshot_id",
                "reason": "duplicate labels",
                "sample": duplicate_labels[:10],
            }
        )
    unknown = sorted(set(label_counts) - set(snapshots_by_id))
    if unknown:
        errors.append(
            {
                "field": "ml_labels.snapshot_id",
                "reason": "unknown snapshot_id",
                "sample": unknown[:10],
            }
        )
    labels_by_snapshot = {row["snapshot_id"]: row for row in labels}
    missing_eligible_labels = sorted(set(eligible_ids) - set(labels_by_snapshot))
    if missing_eligible_labels:
        errors.append(
            {
                "field": "ml_labels",
                "reason": "missing labels for eligible rows",
                "sample": missing_eligible_labels[:10],
            }
        )

    class_values: list[bool] = []
    for snapshot_id in eligible_ids:
        label = labels_by_snapshot.get(snapshot_id)
        if label is None:
            continue
        snapshot = snapshots_by_id[snapshot_id]
        if label["target_name"] != target_name:
            errors.append(
                {
                    "snapshot_id": snapshot_id,
                    "field": "target_name",
                    "observed": label["target_name"],
                    "expected": target_name,
                }
            )
        prediction_time = parse_timestamp(snapshot["prediction_time"], "prediction_time")
        observed_at = parse_timestamp(label["label_observed_at"], "label_observed_at")
        if observed_at < prediction_time + timedelta(days=horizon_days):
            errors.append(
                {
                    "snapshot_id": snapshot_id,
                    "field": "label_observed_at",
                    "observed": observed_at.isoformat(),
                    "expected": f">= prediction_time + {horizon_days} days",
                }
            )
        if not parse_bool(label["label_window_complete"]):
            errors.append(
                {
                    "snapshot_id": snapshot_id,
                    "field": "label_window_complete",
                    "reason": "label window incomplete",
                }
            )
        class_values.append(parse_bool(label[target_column]))
    class_set = set(class_values)
    expected_classes = {bool(positive_class["value"]), bool(negative_class["value"])}
    if class_set != expected_classes:
        errors.append(
            {
                "field": target_column,
                "observed": sorted(class_set),
                "expected": sorted(expected_classes),
            }
        )
    if errors:
        return failed(
            "target_has_horizon_and_classes",
            len(errors),
            "target after prediction time with both classes",
            errors,
        )
    positive_count = sum(value == positive_class["value"] for value in class_values)
    negative_count = len(class_values) - positive_count
    return passed(
        "target_has_horizon_and_classes",
        {"positive": positive_count, "negative": negative_count, "horizon_days": horizon_days},
        "target after prediction time with both classes",
    )


def validate_feature_sources(
    spec: dict[str, Any],
    snapshots: list[dict[str, str]],
    sources: list[dict[str, str]],
    source_columns: list[str],
) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    missing_columns = sorted(REQUIRED_FEATURE_COLUMNS - set(source_columns))
    if missing_columns:
        return failed(
            "feature_sources_available_before_prediction",
            missing_columns,
            "feature inventory columns",
            [{"missing_columns": missing_columns}],
        )
    allowed = spec.get("allowed_feature_sources")
    forbidden = spec.get("forbidden_feature_sources")
    if not isinstance(allowed, list) or not isinstance(forbidden, list):
        return failed(
            "feature_sources_available_before_prediction",
            "invalid lists",
            "allowed and forbidden source lists",
        )
    overlap = sorted(set(allowed) & set(forbidden))
    if overlap:
        errors.append(
            {"reason": "allowed and forbidden feature sources overlap", "source_ids": overlap}
        )
    by_source = {row["source_id"]: row for row in sources}
    missing = sorted((set(allowed) | set(forbidden)) - set(by_source))
    if missing:
        errors.append({"reason": "source missing from inventory", "source_ids": missing})
    prediction_times = [
        parse_timestamp(row["prediction_time"], "prediction_time") for row in snapshots
    ]
    earliest_prediction_time = min(prediction_times) if prediction_times else None
    for source_id in allowed:
        row = by_source.get(str(source_id))
        if row is None:
            continue
        timing = row["timing"]
        if timing not in ALLOWED_FEATURE_TIMINGS or not parse_bool(row["allowed"]):
            errors.append(
                {
                    "source_id": source_id,
                    "timing": timing,
                    "allowed_flag": row["allowed"],
                    "reason": "allowed sources must be available before prediction",
                }
            )
        if row["max_observed_at"] and earliest_prediction_time is not None:
            max_observed_at = parse_timestamp(row["max_observed_at"], "max_observed_at")
            if max_observed_at > earliest_prediction_time:
                errors.append(
                    {
                        "source_id": source_id,
                        "max_observed_at": max_observed_at.isoformat(),
                        "prediction_time": earliest_prediction_time.isoformat(),
                    }
                )
    for source_id in forbidden:
        row = by_source.get(str(source_id))
        if row is None:
            continue
        if row["timing"] not in FORBIDDEN_FEATURE_TIMINGS and parse_bool(row["allowed"]):
            errors.append(
                {
                    "source_id": source_id,
                    "timing": row["timing"],
                    "reason": "forbidden source must be explicitly post-prediction or disallowed",
                }
            )
    if errors:
        return failed(
            "feature_sources_available_before_prediction",
            len(errors),
            "only pre-prediction sources allowed",
            errors,
        )
    return passed(
        "feature_sources_available_before_prediction",
        {"allowed": len(allowed), "forbidden": len(forbidden)},
        "only pre-prediction sources allowed",
    )


def validate_no_causal_claim(spec: dict[str, Any]) -> dict[str, Any]:
    model_card = spec.get("model_card_policy")
    if not isinstance(model_card, dict):
        return failed("no_causal_claim_boundary", "missing", "model card claim boundary")
    claim_boundary = str(model_card.get("claim_boundary", "")).lower()
    out_of_scope = set(model_card.get("out_of_scope_uses", []))
    has_boundary = "does not estimate the causal effect" in claim_boundary
    has_out_of_scope = "causal_effect_of_offer" in out_of_scope
    if not has_boundary or not has_out_of_scope:
        return failed(
            "no_causal_claim_boundary",
            {
                "claim_boundary": model_card.get("claim_boundary"),
                "out_of_scope_uses": sorted(out_of_scope),
            },
            "risk score is not an offer-effect claim",
            [{"reason": "model performance cannot justify treatment-effect wording"}],
        )
    return passed(
        "no_causal_claim_boundary",
        model_card["claim_boundary"],
        "risk score is not an offer-effect claim",
    )


def build_summary(
    spec: dict[str, Any],
    snapshots: list[dict[str, str]],
    labels: list[dict[str, str]],
    eligible_ids: list[str],
    checks: list[dict[str, Any]],
) -> dict[str, Any]:
    label_by_snapshot = {row["snapshot_id"]: row for row in labels}
    positives = sum(
        parse_bool(label_by_snapshot[snapshot_id]["churned_14d"])
        for snapshot_id in eligible_ids
        if snapshot_id in label_by_snapshot
    )
    negatives = len(eligible_ids) - positives
    positive_rate = positives / len(eligible_ids) if eligible_ids else 0.0
    if eligible_ids and (positive_rate < 0.35 or positive_rate > 0.65):
        checks.append(
            failed(
                "class_imbalance_expected",
                round(positive_rate, 4),
                "review imbalance before accuracy-based evaluation",
                [{"positive": positives, "negative": negatives}],
                severity="warning",
            )
        )
    segments = sorted(
        {row["segment_id"] for row in snapshots if row["snapshot_id"] in eligible_ids}
    )
    return {
        "problem_id": spec.get("problem_id"),
        "target_name": spec.get("target_name"),
        "prediction_unit_key": (spec.get("prediction_unit") or {}).get("key")
        if isinstance(spec.get("prediction_unit"), dict)
        else None,
        "snapshot_rows": len(snapshots),
        "eligible_prediction_rows": len(eligible_ids),
        "positive_labels": positives,
        "negative_labels": negatives,
        "positive_rate": round(positive_rate, 4),
        "segments": segments,
        "readiness_status": "ready_for_split_design",
    }


def build_report(
    spec: dict[str, Any], checks: list[dict[str, Any]], summary: dict[str, Any]
) -> dict[str, Any]:
    errors = [check for check in checks if not check["valid"] and check["severity"] == "error"]
    warnings = [check for check in checks if not check["valid"] and check["severity"] == "warning"]
    return {
        "audit_id": "ml-problem-spec-readiness",
        "problem_id": spec.get("problem_id"),
        "valid": not errors,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "checks": checks,
        "summary": {
            **summary,
            "checks_total": len(checks),
            "checks_failed": len(errors) + len(warnings),
            "blocking_errors": [check["id"] for check in errors],
            "warnings": [check["id"] for check in warnings],
        },
    }


def validate_problem_spec(
    *,
    spec: dict[str, Any],
    snapshots: list[dict[str, str]],
    snapshot_columns: list[str],
    labels: list[dict[str, str]],
    label_columns: list[str],
    feature_sources: list[dict[str, str]],
    feature_columns: list[str],
) -> dict[str, Any]:
    checks = [required_fields_check(spec, REQUIRED_SPEC_FIELDS, "problem_spec_required_fields")]
    if not checks[0]["valid"]:
        return build_report(spec, checks, {})

    checks.append(validate_business_decision(spec))
    checks.append(validate_policy_sections(spec))
    checks.append(validate_prediction_unit(spec, snapshots, snapshot_columns))
    population_check, eligible_ids = validate_population_and_decision_timing(spec, snapshots)
    checks.append(population_check)
    if population_check["valid"]:
        checks.append(
            validate_target_contract(spec, snapshots, labels, label_columns, eligible_ids)
        )
    checks.append(validate_feature_sources(spec, snapshots, feature_sources, feature_columns))
    checks.append(validate_no_causal_claim(spec))

    summary: dict[str, Any] = {}
    if all(check["valid"] or check["severity"] != "error" for check in checks):
        summary = build_summary(spec, snapshots, labels, eligible_ids, checks)
    return build_report(spec, checks, summary)


def run(
    *,
    spec_path: Path,
    snapshots_path: Path,
    labels_path: Path,
    feature_sources_path: Path,
) -> dict[str, Any]:
    snapshots, snapshot_columns = read_csv(snapshots_path)
    labels, label_columns = read_csv(labels_path)
    feature_sources, feature_columns = read_csv(feature_sources_path)
    return validate_problem_spec(
        spec=read_json(spec_path),
        snapshots=snapshots,
        snapshot_columns=snapshot_columns,
        labels=labels,
        label_columns=label_columns,
        feature_sources=feature_sources,
        feature_columns=feature_columns,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate supervised ML problem framing before modeling."
    )
    parser.add_argument("--spec", type=Path, required=True, help="problem_spec.json")
    parser.add_argument("--snapshots", type=Path, required=True, help="ml_scoring_snapshots.csv")
    parser.add_argument("--labels", type=Path, required=True, help="ml_labels.csv")
    parser.add_argument(
        "--feature-sources", type=Path, required=True, help="feature_source_inventory.csv"
    )
    parser.add_argument("--output", type=Path, help="write JSON report to this path")
    parser.add_argument(
        "--fail-on-warning", action="store_true", help="return non-zero when warning checks fail"
    )
    args = parser.parse_args()
    try:
        report = run(
            spec_path=args.spec,
            snapshots_path=args.snapshots,
            labels_path=args.labels,
            feature_sources_path=args.feature_sources,
        )
    except (OSError, json.JSONDecodeError, MLProblemSpecError) as error:
        print(json.dumps({"valid": False, "error": str(error)}, ensure_ascii=False, indent=2))
        raise SystemExit(2) from error
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    sys.stdout.write(rendered)
    if not report["valid"] or (args.fail_on_warning and report["warning_count"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
