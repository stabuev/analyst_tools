from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd

LESSON_ROOT = Path(__file__).resolve().parents[1]
PHASE_ROOT = LESSON_ROOT.parent
REPO_ROOT = PHASE_ROOT.parents[1]
DEFAULT_DATA_DIR = PHASE_ROOT / "data" / "tiny"
DEFAULT_SPEC = LESSON_ROOT / "outputs" / "sensitivity_spec.json"
DEFAULT_OUTPUT = LESSON_ROOT / "outputs" / "sensitivity_report.json"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def to_bool(series: pd.Series) -> pd.Series:
    return series.astype(str).str.lower().map({"true": True, "false": False})


def scalar(value: Any) -> Any:
    if hasattr(value, "item"):
        return value.item()
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [
        {key: scalar(value) for key, value in row.items()}
        for row in frame.to_dict(orient="records")
    ]


def add_check(
    checks: list[dict[str, Any]],
    check_id: str,
    valid: bool,
    *,
    severity: str = "error",
    sample: Any = None,
    message: str = "",
) -> None:
    payload: dict[str, Any] = {
        "id": check_id,
        "valid": bool(valid),
        "severity": severity,
    }
    if message:
        payload["message"] = message
    if sample is not None:
        payload["sample"] = sample
    checks.append(payload)


def blocking_checks(checks: list[dict[str, Any]]) -> list[str]:
    return [
        check["id"]
        for check in checks
        if not check["valid"] and check["severity"] == "error"
    ]


def warning_checks(checks: list[dict[str, Any]]) -> list[str]:
    return [
        check["id"]
        for check in checks
        if not check["valid"] and check["severity"] == "warning"
    ]


def load_tables(data_dir: Path) -> dict[str, pd.DataFrame]:
    tables = {
        "users": pd.read_csv(data_dir / "users.csv"),
        "pre_treatment_behavior": pd.read_csv(data_dir / "pre_treatment_behavior.csv"),
        "onboarding_assistance": pd.read_csv(data_dir / "onboarding_assistance.csv"),
        "outcomes": pd.read_csv(data_dir / "outcomes.csv"),
    }
    bool_columns = {
        "users": ["is_test_user", "eligible_for_program"],
        "pre_treatment_behavior": ["activation_14d_pre"],
        "onboarding_assistance": ["offered_assistance", "received_assistance"],
        "outcomes": [
            "activation_14d",
            "paid_subscription_30d",
            "cancelled_subscription_30d",
            "telemetry_complete_30d",
        ],
    }
    for table, columns in bool_columns.items():
        for column in columns:
            tables[table][column] = to_bool(tables[table][column])
    for table, columns in {
        "pre_treatment_behavior": [
            "friction_score",
            "app_crashes_before_time_zero",
            "sessions_before_time_zero",
            "specialist_capacity",
        ],
        "onboarding_assistance": ["friction_score", "specialist_capacity"],
        "outcomes": ["support_minutes_14d", "refund_amount_30d"],
    }.items():
        for column in columns:
            tables[table][column] = pd.to_numeric(tables[table][column])
    return tables


def duplicate_rows(frame: pd.DataFrame, keys: list[str]) -> list[dict[str, Any]]:
    duplicates = frame[frame.duplicated(keys, keep=False)].sort_values(keys)
    return records(duplicates[keys]) if not duplicates.empty else []


def audit_source_grain(tables: dict[str, pd.DataFrame], checks: list[dict[str, Any]]) -> None:
    failures = []
    for table, keys in {
        "users": ["user_id"],
        "pre_treatment_behavior": ["user_id"],
        "onboarding_assistance": ["program_id", "user_id"],
        "outcomes": ["user_id"],
    }.items():
        duplicates = duplicate_rows(tables[table], keys)
        if duplicates:
            failures.append({"table": table, "keys": keys, "duplicates": duplicates})
    add_check(
        checks,
        "source_tables_preserve_declared_grain",
        not failures,
        sample=failures or None,
        message="Sensitivity checks must run on one-row-per-unit source tables.",
    )


def build_cohort(tables: dict[str, pd.DataFrame], spec: dict[str, Any]) -> pd.DataFrame:
    cohort = (
        tables["users"]
        .merge(tables["onboarding_assistance"], on="user_id", suffixes=("", "_assistance"))
        .merge(tables["pre_treatment_behavior"], on="user_id", suffixes=("", "_baseline"))
        .merge(tables["outcomes"], on="user_id")
        .sort_values("user_id")
        .reset_index(drop=True)
    )
    population = spec["target_population"]
    if population["exclude_test_users"]:
        cohort = cohort[~cohort["is_test_user"]]
    if population["eligible_for_program"]:
        cohort = cohort[cohort["eligible_for_program"]]
    cohort = cohort[cohort["friction_score"] >= population["minimum_friction_score"]].copy()
    cohort["user_id_number"] = cohort["user_id"].str[1:].astype(int)
    cohort["even_user_id"] = cohort["user_id_number"] % 2 == 0
    return cohort.reset_index(drop=True)


def mean_value(frame: pd.DataFrame, column: str) -> float:
    series = frame[column]
    if series.dtype == bool:
        return float(series.astype(int).mean())
    return float(pd.to_numeric(series).mean())


def difference_by_group(
    cohort: pd.DataFrame,
    treatment: str,
    outcome: str,
) -> dict[str, Any]:
    treated = cohort[cohort[treatment]]
    control = cohort[~cohort[treatment]]
    treated_mean = mean_value(treated, outcome)
    control_mean = mean_value(control, outcome)
    return {
        "treatment": treatment,
        "outcome": outcome,
        "treated_n": int(len(treated)),
        "control_n": int(len(control)),
        "treated_mean": treated_mean,
        "control_mean": control_mean,
        "effect": treated_mean - control_mean,
    }


def run_falsification_checks(
    cohort: pd.DataFrame,
    spec: dict[str, Any],
    upstream_reports: dict[str, dict[str, Any]],
    checks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for item in spec["falsification_checks"]:
        check_id = item["check_id"]
        if item["type"] == "upstream_did_placebo":
            did_report = upstream_reports[item["source_report"]]
            source = next(
                check for check in did_report["checks"] if check["id"] == item["source_check"]
            )
            result = {
                "check_id": check_id,
                "type": item["type"],
                "source_check": item["source_check"],
                "passes": bool(source["valid"]),
                "effect": source.get("sample", {}).get("did_estimate"),
                "max_abs_effect": source.get("sample", {}).get("max_abs_placebo_effect"),
            }
        else:
            treatment = item.get("treatment") or item["treatment_expression"]
            result = difference_by_group(cohort, treatment, item["outcome"])
            result.update(
                {
                    "check_id": check_id,
                    "type": item["type"],
                    "max_abs_effect": item["max_abs_effect"],
                    "passes": abs(result["effect"]) <= float(item["max_abs_effect"]),
                }
            )
        add_check(
            checks,
            check_id,
            result["passes"],
            severity="warning",
            sample=result,
            message=(
                "Falsification checks can block strong causal wording without breaking "
                "the pipeline."
            ),
        )
        results.append(result)
    return results


def load_upstream_reports(
    spec: dict[str, Any],
    checks: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    loaded: dict[str, dict[str, Any]] = {}
    failures: list[dict[str, str]] = []
    for report_id, relative_path in spec["upstream_reports"].items():
        path = REPO_ROOT / relative_path
        if not path.exists():
            path = REPO_ROOT / "phases" / relative_path
        try:
            loaded[report_id] = read_json(path)
        except (OSError, json.JSONDecodeError) as error:
            failures.append({"report_id": report_id, "path": relative_path, "error": str(error)})
    add_check(
        checks,
        "upstream_reports_are_available",
        not failures,
        sample=failures or None,
        message="Sensitivity suite depends on committed estimator/design reports.",
    )
    invalid = [
        {"report_id": report_id, "summary": report.get("summary", {})}
        for report_id, report in loaded.items()
        if not report.get("valid", False)
    ]
    add_check(
        checks,
        "upstream_reports_are_structurally_valid",
        not invalid,
        sample=invalid or None,
        message="Refutation should start from structurally valid upstream reports.",
    )
    return loaded


def extract_estimate_table(upstream_reports: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    ipw = upstream_reports["ipw_aipw"]["summary"]
    did = upstream_reports["did"]["summary"]
    quasi = upstream_reports["quasi"]["summary"]
    return [
        {
            "estimate_id": "naive_risk_difference",
            "source": "ipw_aipw",
            "estimand": "unadjusted_association",
            "estimate": ipw["naive_risk_difference"],
            "poolable": False,
        },
        {
            "estimate_id": "ipw_hajek_ate",
            "source": "ipw_aipw",
            "estimand": "ATE_under_exchangeability",
            "estimate": ipw["ipw_hajek_ate"],
            "poolable": False,
        },
        {
            "estimate_id": "aipw_ate",
            "source": "ipw_aipw",
            "estimand": "ATE_under_exchangeability",
            "estimate": ipw["aipw_ate"],
            "poolable": False,
        },
        {
            "estimate_id": "outcome_regression_ate",
            "source": "ipw_aipw",
            "estimand": "ATE_under_exchangeability",
            "estimate": ipw["outcome_regression_ate"],
            "poolable": False,
        },
        {
            "estimate_id": "did_estimate",
            "source": "did",
            "estimand": "regional_rollout_ATT_under_parallel_trends",
            "estimate": did["did_estimate"],
            "poolable": False,
        },
        {
            "estimate_id": "rdd_wald_local_effect_diagnostic",
            "source": "quasi",
            "estimand": "local_cutoff_diagnostic",
            "estimate": quasi["rdd_wald_local_effect_diagnostic"],
            "poolable": False,
        },
        {
            "estimate_id": "iv_wald_late",
            "source": "quasi",
            "estimand": "LATE_for_compliers",
            "estimate": quasi["iv_wald_late"],
            "poolable": False,
        },
    ]


def compare_design_estimates(
    estimate_table: list[dict[str, Any]],
    checks: list[dict[str, Any]],
) -> dict[str, Any]:
    estimates = [float(row["estimate"]) for row in estimate_table]
    signs = sorted({-1 if value < 0 else 1 if value > 0 else 0 for value in estimates})
    comparison = {
        "min_estimate": min(estimates),
        "max_estimate": max(estimates),
        "range": max(estimates) - min(estimates),
        "signs": signs,
        "pooling_allowed": False,
        "reason": "Estimates target different assumptions and estimands.",
    }
    add_check(
        checks,
        "design_estimates_are_not_poolable",
        True,
        sample=comparison,
        message="RA/IPW/AIPW, DiD, RDD and IV estimates must not be averaged together.",
    )
    add_check(
        checks,
        "design_estimates_show_directional_disagreement",
        len([sign for sign in signs if sign != 0]) <= 1,
        severity="warning",
        sample=comparison,
        message="Opposite signs across designs make a single strong story inappropriate.",
    )
    return comparison


def omitted_confounding_grid(
    primary_estimate: float,
    spec: dict[str, Any],
) -> dict[str, Any]:
    sensitivity = spec["omitted_confounding_sensitivity"]
    rows: list[dict[str, Any]] = []
    for imbalance in sensitivity["control_minus_treated_prevalence_grid"]:
        for outcome_effect in sensitivity["outcome_risk_difference_grid"]:
            bias = float(imbalance) * float(outcome_effect)
            adjusted = primary_estimate + bias
            rows.append(
                {
                    "control_minus_treated_prevalence": imbalance,
                    "outcome_risk_difference": outcome_effect,
                    "bias_toward_zero": bias,
                    "adjusted_effect": adjusted,
                    "crosses_null": adjusted >= float(spec["primary_effect"]["claim_threshold"]),
                }
            )
    nulling = [row for row in rows if row["crosses_null"]]
    first_nulling = min(nulling, key=lambda row: row["bias_toward_zero"]) if nulling else None
    return {
        "primary_estimate": primary_estimate,
        "required_bias_to_reach_null": abs(primary_estimate),
        "scenario": sensitivity["scenario"],
        "rows": rows,
        "first_nulling_scenario": first_nulling,
    }


def calculated_claim_status(
    claim: dict[str, Any],
    *,
    falsification_failures: list[str],
    upstream_reports: dict[str, dict[str, Any]],
    design_comparison: dict[str, Any],
) -> str:
    claim_id = claim["claim_id"]
    primary_claim_allowed = upstream_reports["ipw_aipw"]["summary"]["allowed_effect_claim"]
    if claim_id == "observational_aipw_strong_claim":
        if falsification_failures or not primary_claim_allowed:
            return "blocked_by_falsification"
        return "claimable_with_assumptions"
    if claim_id == "did_limited_rollout_claim":
        return "limited_design_specific_with_warnings"
    if claim_id == "iv_late_claim":
        return "limited_late_with_unverifiable_assumptions"
    if claim_id == "pooled_average_effect_claim":
        if not design_comparison["pooling_allowed"]:
            return "invalid_mixed_estimands"
        return "claimable_with_assumptions"
    return "unknown_claim"


def audit_candidate_claims(
    spec: dict[str, Any],
    checks: list[dict[str, Any]],
    *,
    falsification_failures: list[str],
    upstream_reports: dict[str, dict[str, Any]],
    design_comparison: dict[str, Any],
) -> list[dict[str, Any]]:
    rows = []
    for claim in spec["candidate_claims"]:
        calculated = calculated_claim_status(
            claim,
            falsification_failures=falsification_failures,
            upstream_reports=upstream_reports,
            design_comparison=design_comparison,
        )
        rows.append(
            {
                "claim_id": claim["claim_id"],
                "declared_status": claim["declared_status"],
                "calculated_status": calculated,
            }
        )
    mismatches = [row for row in rows if row["declared_status"] != row["calculated_status"]]
    add_check(
        checks,
        "candidate_claim_statuses_match_policy",
        not mismatches,
        sample=mismatches or None,
        message="Claim candidates must be labeled by the refutation policy.",
    )
    return rows


def audit_claim_policy(
    spec: dict[str, Any],
    checks: list[dict[str, Any]],
    *,
    upstream_reports: dict[str, dict[str, Any]],
    falsification_failures: list[str],
    design_comparison: dict[str, Any],
) -> dict[str, Any]:
    reasons: list[str] = []
    policy = spec["claim_policy"]
    if policy["block_if_any_falsification_fails"] and falsification_failures:
        reasons.append("falsification_checks_failed")
    if (
        policy["block_if_upstream_primary_disallows_claim"]
        and not upstream_reports["ipw_aipw"]["summary"]["allowed_effect_claim"]
    ):
        reasons.append("upstream_primary_claim_disallowed")
    if (
        policy["block_if_design_estimates_have_opposite_signs"]
        and len([sign for sign in design_comparison["signs"] if sign != 0]) > 1
    ):
        reasons.append("design_estimates_have_opposite_signs")
    if policy["never_pool_different_estimands"] and not design_comparison["pooling_allowed"]:
        reasons.append("different_estimands_not_poolable")
    allowed = not reasons
    add_check(
        checks,
        "claim_policy_blocks_strong_causal_effect_statement",
        not allowed,
        severity="warning",
        sample={"reasons": reasons},
        message="The suite should block a strong one-number causal claim when refutations fail.",
    )
    return {
        "allowed_effect_claim": allowed,
        "blocking_reasons": reasons,
        "recommended_wording": (
            "Do not ship a single strong causal effect claim. Report design-specific evidence: "
            "observational AIPW is fragile under falsification, DiD is rollout-specific, "
            "RDD is local/diagnostic on tiny data, and IV is LATE for compliers under "
            "unverifiable exclusion and monotonicity assumptions."
        )
        if not allowed
        else "Effect claim may be stated under the documented assumptions.",
    }


def audit_sensitivity(data_dir: Path, spec: dict[str, Any]) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    tables = load_tables(data_dir)
    audit_source_grain(tables, checks)
    cohort = build_cohort(tables, spec)
    add_check(
        checks,
        "target_population_is_non_empty",
        len(cohort) > 0,
        sample={"cohort_n": int(len(cohort))},
        message="Sensitivity suite needs the same target population as previous estimators.",
    )
    upstream_reports = load_upstream_reports(spec, checks)
    if blocking_checks(checks):
        summary = {
            "spec_id": spec["spec_id"],
            "cohort_n": int(len(cohort)),
            "allowed_effect_claim": False,
            "blocking_checks": blocking_checks(checks),
            "warning_checks": warning_checks(checks),
        }
        return {
            "valid": False,
            "summary": summary,
            "checks": checks,
        }

    falsification = run_falsification_checks(cohort, spec, upstream_reports, checks)
    falsification_failures = [row["check_id"] for row in falsification if not row["passes"]]
    estimate_table = extract_estimate_table(upstream_reports)
    design_comparison = compare_design_estimates(estimate_table, checks)
    primary_estimate = next(
        row["estimate"]
        for row in estimate_table
        if row["estimate_id"] == spec["primary_effect"]["estimate_id"]
        and row["source"] == spec["primary_effect"]["source"]
    )
    sensitivity = omitted_confounding_grid(float(primary_estimate), spec)
    add_check(
        checks,
        "omitted_confounding_grid_contains_nulling_scenario",
        sensitivity["first_nulling_scenario"] is not None,
        severity="warning",
        sample=sensitivity["first_nulling_scenario"],
        message="Sensitivity grid should show how strong an omitted confounder must be.",
    )
    candidate_claims = audit_candidate_claims(
        spec,
        checks,
        falsification_failures=falsification_failures,
        upstream_reports=upstream_reports,
        design_comparison=design_comparison,
    )
    claim_policy = audit_claim_policy(
        spec,
        checks,
        upstream_reports=upstream_reports,
        falsification_failures=falsification_failures,
        design_comparison=design_comparison,
    )
    summary = {
        "spec_id": spec["spec_id"],
        "cohort_n": int(len(cohort)),
        "primary_effect_id": spec["primary_effect"]["estimate_id"],
        "primary_effect": float(primary_estimate),
        "falsification_failures": falsification_failures,
        "required_bias_to_reach_null": sensitivity["required_bias_to_reach_null"],
        "first_nulling_bias": (
            sensitivity["first_nulling_scenario"]["bias_toward_zero"]
            if sensitivity["first_nulling_scenario"]
            else None
        ),
        "design_estimate_min": design_comparison["min_estimate"],
        "design_estimate_max": design_comparison["max_estimate"],
        "design_estimate_range": design_comparison["range"],
        "allowed_effect_claim": claim_policy["allowed_effect_claim"],
        "claim_blocking_reasons": claim_policy["blocking_reasons"],
        "blocking_checks": blocking_checks(checks),
        "warning_checks": warning_checks(checks),
    }
    return {
        "valid": not blocking_checks(checks),
        "summary": summary,
        "falsification_checks": falsification,
        "estimate_comparison": {
            "rows": estimate_table,
            "comparison": design_comparison,
        },
        "omitted_confounding_sensitivity": sensitivity,
        "candidate_claims": candidate_claims,
        "claim_policy": claim_policy,
        "checks": checks,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run placebo, negative-control and omitted-confounding sensitivity checks."
    )
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--fail-on-invalid", action="store_true")
    args = parser.parse_args()

    report = audit_sensitivity(args.data_dir, read_json(args.spec))
    write_json(args.output, report)
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    if args.fail_on_invalid and not report["valid"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
