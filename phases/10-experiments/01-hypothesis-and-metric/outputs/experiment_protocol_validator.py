from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

REQUIRED_PROTOCOL_FIELDS = {
    "experiment_id",
    "title",
    "product_hypothesis",
    "statistical_hypotheses",
    "owner",
    "decision_owner",
    "variants",
    "eligible_population",
    "randomization_unit",
    "analysis_unit",
    "assignment_key",
    "traffic_allocation",
    "exposure_event",
    "start_at",
    "planned_end_at",
    "metric_freeze_at",
    "primary_metric",
    "guardrail_metrics",
    "secondary_metrics",
    "exploratory_metrics",
    "metric_windows",
    "pre_experiment_covariates",
    "alpha",
    "power",
    "minimum_detectable_effect",
    "minimum_runtime_days",
    "sample_size_plan",
    "aa_srm_policy",
    "multiple_testing_policy",
    "peeking_policy",
    "cuped_policy",
    "segment_policy",
    "decision_rule",
    "rollback_rule",
    "known_risks",
    "limitations",
}
REQUIRED_METRIC_FIELDS = {
    "metric_id",
    "name",
    "role",
    "question",
    "grain",
    "eligible_population",
    "numerator",
    "denominator",
    "window_days",
    "expected_direction",
    "source_tables",
    "validation_checks",
    "known_failure_modes",
}
METRIC_ROLES = {"primary", "guardrail", "secondary", "exploratory"}
STANDARD_DIRECTIONS = {"up", "down", "neutral"}
GUARDRAIL_DIRECTIONS = {"up_is_bad", "down_is_bad"}
SUPPORTED_UNITS = {"user_id"}
ALLOWED_DECISIONS = {"launch", "hold", "rollback", "iterate", "inconclusive"}
REQUIRED_POLICIES = {
    "aa_srm_policy",
    "multiple_testing_policy",
    "peeking_policy",
    "cuped_policy",
    "segment_policy",
}


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
) -> dict[str, Any]:
    return {
        "id": check_id,
        "severity": "error",
        "valid": False,
        "observed": observed,
        "expected": expected,
        "sample": sample or [],
    }


def read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as source:
        return json.load(source)


def normalize_metric_specs(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict) and isinstance(value.get("metrics"), list):
        value = value["metrics"]
    if not isinstance(value, list):
        raise ValueError("metric specs must be a list or an object with a metrics list")
    specs: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("each metric spec must be an object")
        specs.append(item)
    return specs


def non_empty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def non_empty_list(value: Any) -> bool:
    return isinstance(value, list) and bool(value)


def parse_iso_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed


def contract_table_names(data_contract: dict[str, Any] | None) -> set[str]:
    if not isinstance(data_contract, dict):
        return set()
    tables = data_contract.get("tables")
    if not isinstance(tables, dict):
        return set()
    return {key for key in tables if isinstance(key, str)}


def metric_ids_by_role(specs: list[dict[str, Any]], role: str) -> set[str]:
    return {
        str(spec["metric_id"])
        for spec in specs
        if spec.get("role") == role and isinstance(spec.get("metric_id"), str)
    }


def validate_required_protocol_fields(protocol: dict[str, Any]) -> dict[str, Any]:
    missing = sorted(REQUIRED_PROTOCOL_FIELDS - set(protocol))
    if missing:
        return failed("protocol_required_fields", missing, "all required protocol fields", missing)
    return passed("protocol_required_fields", len(REQUIRED_PROTOCOL_FIELDS), "all required protocol fields")


def validate_variants_and_allocation(protocol: dict[str, Any]) -> dict[str, Any]:
    variants = protocol.get("variants")
    allocation = protocol.get("traffic_allocation")
    errors: list[dict[str, Any]] = []
    if not isinstance(variants, list) or len(variants) < 2:
        return failed("variants_and_allocation", len(variants or []), "at least two variants", [])
    if not isinstance(allocation, dict):
        return failed("variants_and_allocation", type(allocation).__name__, "allocation object keyed by variant_id", [])

    variant_ids: list[str] = []
    control_count = 0
    for variant in variants:
        if not isinstance(variant, dict):
            errors.append({"variant": variant, "reason": "variant must be an object"})
            continue
        variant_id = variant.get("variant_id")
        if not non_empty_text(variant_id):
            errors.append({"variant": variant, "reason": "missing variant_id"})
            continue
        variant_ids.append(str(variant_id))
        if variant.get("is_control") is True:
            control_count += 1
    duplicate_ids = sorted({variant_id for variant_id in variant_ids if variant_ids.count(variant_id) > 1})
    if duplicate_ids:
        errors.append({"reason": "duplicate variant_id", "variant_ids": duplicate_ids})
    if control_count != 1:
        errors.append({"reason": "exactly one control variant is required", "control_count": control_count})
    if set(variant_ids) != set(allocation):
        errors.append(
            {
                "reason": "traffic_allocation keys must match variants",
                "variants": sorted(variant_ids),
                "allocation": sorted(allocation),
            }
        )
    allocation_values: list[float] = []
    for variant_id, value in allocation.items():
        if not isinstance(value, (int, float)) or value <= 0:
            errors.append({"variant_id": variant_id, "allocation": value, "reason": "allocation must be positive"})
        else:
            allocation_values.append(float(value))
    allocation_sum = round(sum(allocation_values), 10)
    if allocation_sum != 1.0:
        errors.append({"reason": "allocation must sum to 1.0", "allocation_sum": allocation_sum})
    if errors:
        return failed("variants_and_allocation", len(errors), "variants align with positive allocation summing to 1", errors)
    return passed("variants_and_allocation", {"variants": variant_ids, "allocation_sum": allocation_sum}, "valid")


def validate_timeline(protocol: dict[str, Any]) -> dict[str, Any]:
    start = parse_iso_datetime(protocol.get("start_at"))
    end = parse_iso_datetime(protocol.get("planned_end_at"))
    freeze = parse_iso_datetime(protocol.get("metric_freeze_at"))
    minimum_runtime = protocol.get("minimum_runtime_days")
    if start is None or end is None or freeze is None:
        return failed("experiment_timeline", "invalid datetime", "timezone-aware ISO datetimes", [])
    runtime_days = (end - start).total_seconds() / 86400
    freeze_delay_days = (freeze - end).total_seconds() / 86400
    errors: list[dict[str, Any]] = []
    if runtime_days <= 0:
        errors.append({"reason": "planned_end_at must be after start_at", "runtime_days": runtime_days})
    if not isinstance(minimum_runtime, int) or minimum_runtime <= 0:
        errors.append({"reason": "minimum_runtime_days must be a positive integer", "minimum_runtime_days": minimum_runtime})
    elif runtime_days < minimum_runtime:
        errors.append({"reason": "planned runtime is shorter than minimum_runtime_days", "runtime_days": runtime_days})
    if freeze_delay_days < 0:
        errors.append({"reason": "metric_freeze_at must be after planned_end_at", "freeze_delay_days": freeze_delay_days})
    if errors:
        return failed("experiment_timeline", len(errors), "valid start/end/freeze chronology", errors)
    return passed(
        "experiment_timeline",
        {"runtime_days": runtime_days, "freeze_delay_days": freeze_delay_days},
        "runtime >= minimum and freeze after end",
    )


def validate_design_parameters(protocol: dict[str, Any]) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    alpha = protocol.get("alpha")
    power = protocol.get("power")
    if not isinstance(alpha, (int, float)) or not 0 < float(alpha) < 1:
        errors.append({"field": "alpha", "value": alpha})
    if not isinstance(power, (int, float)) or not 0 < float(power) < 1:
        errors.append({"field": "power", "value": power})
    mde = protocol.get("minimum_detectable_effect")
    if not isinstance(mde, dict):
        errors.append({"field": "minimum_detectable_effect", "value": type(mde).__name__})
    else:
        if mde.get("metric_id") != protocol.get("primary_metric"):
            errors.append({"field": "minimum_detectable_effect.metric_id", "value": mde.get("metric_id")})
        for field in ("absolute", "relative"):
            value = mde.get(field)
            if not isinstance(value, (int, float)) or float(value) <= 0:
                errors.append({"field": f"minimum_detectable_effect.{field}", "value": value})
    sample_size_plan = protocol.get("sample_size_plan")
    if not isinstance(sample_size_plan, dict) or sample_size_plan.get("planned_units_per_variant", 0) <= 0:
        errors.append({"field": "sample_size_plan.planned_units_per_variant", "value": sample_size_plan})
    if errors:
        return failed("statistical_design_parameters", len(errors), "alpha/power/MDE/sample size declared", errors)
    return passed(
        "statistical_design_parameters",
        {"alpha": alpha, "power": power, "primary_mde": mde},
        "valid design parameters",
    )


def validate_eligible_population(protocol: dict[str, Any], tables: set[str]) -> dict[str, Any]:
    population = protocol.get("eligible_population")
    errors: list[Any] = []
    if not isinstance(population, dict):
        return failed("eligible_population_contract", type(population).__name__, "eligible population object", [])
    if population.get("unit") not in SUPPORTED_UNITS:
        errors.append({"field": "eligible_population.unit", "value": population.get("unit")})
    if protocol.get("randomization_unit") != protocol.get("analysis_unit"):
        errors.append(
            {
                "field": "randomization_unit/analysis_unit",
                "value": [protocol.get("randomization_unit"), protocol.get("analysis_unit")],
                "reason": "lesson 10/01 supports user-level experiments",
            }
        )
    if protocol.get("assignment_key") != protocol.get("randomization_unit"):
        errors.append({"field": "assignment_key", "value": protocol.get("assignment_key")})
    if population.get("source_table") not in tables:
        errors.append({"field": "eligible_population.source_table", "value": population.get("source_table")})
    filters = population.get("filters")
    if not isinstance(filters, list) or not filters:
        errors.append({"field": "eligible_population.filters", "value": filters})
    else:
        has_test_filter = any(
            item.get("field") == "is_test_user" and item.get("operator") == "==" and item.get("value") is False
            for item in filters
            if isinstance(item, dict)
        )
        if not has_test_filter:
            errors.append({"field": "eligible_population.filters", "reason": "must exclude test users"})
    if errors:
        return failed("eligible_population_contract", len(errors), "user-level eligible non-test population", errors)
    return passed("eligible_population_contract", population.get("description"), "eligible population is explicit")


def validate_metric_specs(specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    missing_fields: list[dict[str, Any]] = []
    duplicate_ids: list[str] = []
    ids = [spec.get("metric_id") for spec in specs if isinstance(spec.get("metric_id"), str)]
    duplicate_ids = sorted({metric_id for metric_id in ids if ids.count(metric_id) > 1})
    if duplicate_ids:
        missing_fields.append({"metric_id": "<duplicates>", "missing": [], "duplicates": duplicate_ids})
    for spec in specs:
        missing = sorted(REQUIRED_METRIC_FIELDS - set(spec))
        if missing:
            missing_fields.append({"metric_id": spec.get("metric_id", "<missing>"), "missing": missing})
        if spec.get("role") not in METRIC_ROLES:
            missing_fields.append({"metric_id": spec.get("metric_id", "<missing>"), "invalid_role": spec.get("role")})
        if not non_empty_text(spec.get("denominator")):
            missing_fields.append({"metric_id": spec.get("metric_id", "<missing>"), "invalid_denominator": spec.get("denominator")})
        if not non_empty_list(spec.get("source_tables")):
            missing_fields.append({"metric_id": spec.get("metric_id", "<missing>"), "invalid_source_tables": spec.get("source_tables")})
        if not non_empty_list(spec.get("validation_checks")):
            missing_fields.append({"metric_id": spec.get("metric_id", "<missing>"), "invalid_validation_checks": spec.get("validation_checks")})
    if missing_fields:
        checks.append(failed("metric_specs_required_fields", len(missing_fields), "complete metric specs with unique ids", missing_fields))
    else:
        checks.append(passed("metric_specs_required_fields", len(specs), "complete metric specs with unique ids"))

    role_counts = {role: sum(1 for spec in specs if spec.get("role") == role) for role in METRIC_ROLES}
    if role_counts["primary"] != 1 or role_counts["guardrail"] < 1:
        checks.append(failed("metric_roles_declared", role_counts, "exactly one primary and at least one guardrail", []))
    else:
        checks.append(passed("metric_roles_declared", role_counts, "exactly one primary and at least one guardrail"))
    return checks


def validate_protocol_metrics(protocol: dict[str, Any], specs: list[dict[str, Any]], tables: set[str]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    spec_by_id = {spec.get("metric_id"): spec for spec in specs if isinstance(spec.get("metric_id"), str)}
    protocol_metrics = {
        "primary": [protocol.get("primary_metric")],
        "guardrail": protocol.get("guardrail_metrics", []),
        "secondary": protocol.get("secondary_metrics", []),
    }
    resolution_errors: list[dict[str, Any]] = []
    for role, metric_ids in protocol_metrics.items():
        if not isinstance(metric_ids, list):
            resolution_errors.append({"role": role, "reason": "metric list expected", "value": metric_ids})
            continue
        for metric_id in metric_ids:
            spec = spec_by_id.get(metric_id)
            if spec is None:
                resolution_errors.append({"metric_id": metric_id, "role": role, "reason": "missing metric spec"})
            elif spec.get("role") != role:
                resolution_errors.append({"metric_id": metric_id, "protocol_role": role, "spec_role": spec.get("role")})
    if resolution_errors:
        checks.append(failed("protocol_metrics_resolve", len(resolution_errors), "protocol metrics resolve to matching specs", resolution_errors))
    else:
        checks.append(passed("protocol_metrics_resolve", sum(len(v) for v in protocol_metrics.values()), "protocol metrics resolve to matching specs"))

    windows = protocol.get("metric_windows")
    window_errors: list[dict[str, Any]] = []
    if not isinstance(windows, dict):
        window_errors.append({"reason": "metric_windows must be an object"})
    else:
        for metric_id, spec in spec_by_id.items():
            window = windows.get(metric_id)
            if not isinstance(window, dict):
                window_errors.append({"metric_id": metric_id, "reason": "missing window"})
                continue
            if window.get("start") != "exposure_event" or window.get("days") != spec.get("window_days"):
                window_errors.append(
                    {
                        "metric_id": metric_id,
                        "observed": window,
                        "expected_days": spec.get("window_days"),
                    }
                )
    if window_errors:
        checks.append(failed("metric_windows_declared", len(window_errors), "each spec metric has an exposure-based window", window_errors))
    else:
        checks.append(passed("metric_windows_declared", len(spec_by_id), "each spec metric has an exposure-based window"))

    source_errors: list[dict[str, Any]] = []
    for spec in specs:
        for table in spec.get("source_tables", []):
            if table not in tables:
                source_errors.append({"metric_id": spec.get("metric_id"), "table": table})
    if source_errors:
        checks.append(failed("metric_sources_exist", len(source_errors), "metric source tables exist in data contract", source_errors))
    else:
        checks.append(passed("metric_sources_exist", len(specs), "metric source tables exist in data contract"))

    direction_errors: list[dict[str, Any]] = []
    for spec in specs:
        direction = spec.get("expected_direction")
        if spec.get("role") == "guardrail":
            if direction not in GUARDRAIL_DIRECTIONS:
                direction_errors.append({"metric_id": spec.get("metric_id"), "expected_direction": direction})
        elif direction not in STANDARD_DIRECTIONS:
            direction_errors.append({"metric_id": spec.get("metric_id"), "expected_direction": direction})
    if direction_errors:
        checks.append(failed("guardrail_risk_directions", len(direction_errors), "guardrails use risk directions and others use standard directions", direction_errors))
    else:
        checks.append(passed("guardrail_risk_directions", len(specs), "guardrails use risk directions and others use standard directions"))
    return checks


def validate_policies(protocol: dict[str, Any], tables: set[str]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    policy_errors = [policy for policy in REQUIRED_POLICIES if not isinstance(protocol.get(policy), dict)]
    if policy_errors:
        checks.append(failed("policies_declared", policy_errors, "all experiment policies are objects", policy_errors))
    else:
        checks.append(passed("policies_declared", sorted(REQUIRED_POLICIES), "all experiment policies are objects"))

    covariate_errors: list[dict[str, Any]] = []
    for covariate in protocol.get("pre_experiment_covariates", []):
        if not isinstance(covariate, dict):
            covariate_errors.append({"covariate": covariate, "reason": "must be object"})
            continue
        if covariate.get("timing") != "pre_treatment":
            covariate_errors.append({"name": covariate.get("name"), "timing": covariate.get("timing")})
        if covariate.get("source_table") not in tables:
            covariate_errors.append({"name": covariate.get("name"), "source_table": covariate.get("source_table")})
    cuped_covariates = protocol.get("cuped_policy", {}).get("covariates", [])
    declared_covariates = {
        covariate.get("name")
        for covariate in protocol.get("pre_experiment_covariates", [])
        if isinstance(covariate, dict)
    }
    for covariate in cuped_covariates:
        if covariate not in declared_covariates:
            covariate_errors.append({"name": covariate, "reason": "CUPED covariate not declared as pre-experiment"})
    if covariate_errors:
        checks.append(failed("pre_experiment_covariates_are_pre_treatment", len(covariate_errors), "pre-treatment covariates only", covariate_errors))
    else:
        checks.append(passed("pre_experiment_covariates_are_pre_treatment", len(declared_covariates), "pre-treatment covariates only"))
    return checks


def validate_decision_rule(protocol: dict[str, Any]) -> dict[str, Any]:
    rule = protocol.get("decision_rule")
    rollback = protocol.get("rollback_rule")
    guardrails = set(protocol.get("guardrail_metrics", []))
    errors: list[dict[str, Any]] = []
    if not isinstance(rule, dict):
        return failed("decision_rule_uses_primary_and_guardrails", type(rule).__name__, "decision rule object", [])
    allowed = rule.get("allowed_decisions")
    if not isinstance(allowed, list) or not set(allowed).issubset(ALLOWED_DECISIONS):
        errors.append({"field": "allowed_decisions", "value": allowed})
    launch = rule.get("launch")
    if not isinstance(launch, dict):
        errors.append({"field": "launch", "reason": "missing launch rule"})
    else:
        if launch.get("requires_primary_metric") != protocol.get("primary_metric"):
            errors.append({"field": "launch.requires_primary_metric", "value": launch.get("requires_primary_metric")})
        if launch.get("requires_all_guardrails_not_breached") is not True:
            errors.append({"field": "launch.requires_all_guardrails_not_breached", "value": launch.get("requires_all_guardrails_not_breached")})
    if not isinstance(rollback, dict) or set(rollback.get("guardrails", [])) != guardrails:
        errors.append({"field": "rollback_rule.guardrails", "value": None if not isinstance(rollback, dict) else rollback.get("guardrails")})
    if errors:
        return failed("decision_rule_uses_primary_and_guardrails", len(errors), "decision rule references primary and all guardrails", errors)
    return passed("decision_rule_uses_primary_and_guardrails", allowed, "decision rule references primary and all guardrails")


def validate_protocol(
    protocol: dict[str, Any],
    specs: list[dict[str, Any]],
    data_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tables = contract_table_names(data_contract)
    checks: list[dict[str, Any]] = [
        validate_required_protocol_fields(protocol),
        validate_variants_and_allocation(protocol),
        validate_timeline(protocol),
        validate_design_parameters(protocol),
        validate_eligible_population(protocol, tables),
    ]
    checks.extend(validate_metric_specs(specs))
    checks.extend(validate_protocol_metrics(protocol, specs, tables))
    checks.extend(validate_policies(protocol, tables))
    checks.append(validate_decision_rule(protocol))

    valid = all(check["valid"] for check in checks)
    return {
        "valid": valid,
        "checks": checks,
        "summary": {
            "experiment_id": protocol.get("experiment_id"),
            "primary_metric": protocol.get("primary_metric"),
            "guardrail_metrics": protocol.get("guardrail_metrics", []),
            "secondary_metrics": protocol.get("secondary_metrics", []),
            "metric_count": len(specs),
            "primary_metric_count": len(metric_ids_by_role(specs, "primary")),
            "guardrail_metric_count": len(metric_ids_by_role(specs, "guardrail")),
            "allowed_decisions": protocol.get("decision_rule", {}).get("allowed_decisions", []),
        },
    }


def run(protocol_path: Path, specs_path: Path, data_contract_path: Path | None = None) -> dict[str, Any]:
    protocol = read_json(protocol_path)
    specs = normalize_metric_specs(read_json(specs_path))
    data_contract = read_json(data_contract_path) if data_contract_path is not None else None
    if not isinstance(protocol, dict):
        raise ValueError("experiment protocol must be a JSON object")
    if data_contract is not None and not isinstance(data_contract, dict):
        raise ValueError("data contract must be a JSON object")
    return validate_protocol(protocol, specs, data_contract)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate an A/B experiment protocol before analysis")
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--specs", type=Path, required=True)
    parser.add_argument("--data-contract", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--allow-failures", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = run(args.protocol, args.specs, args.data_contract)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    if report["valid"] or args.allow_failures:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
