from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

LESSON_ROOT = Path(__file__).resolve().parents[1]
PHASE_ROOT = LESSON_ROOT.parent
DEFAULT_DATA_DIR = PHASE_ROOT / "data" / "tiny"
DEFAULT_SPEC = LESSON_ROOT / "outputs" / "quasi_experiment_spec.json"
DEFAULT_OUTPUT = LESSON_ROOT / "outputs" / "quasi_experiment_report.json"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def to_bool(series: pd.Series) -> pd.Series:
    return series.astype(str).str.lower().map({"true": True, "false": False})


def scalar(value: Any) -> Any:
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
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


@dataclass
class CheckBook:
    checks: list[dict[str, Any]]

    def add(
        self,
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
        self.checks.append(payload)

    @property
    def blocking(self) -> list[str]:
        return [
            check["id"]
            for check in self.checks
            if not check["valid"] and check["severity"] == "error"
        ]

    @property
    def warnings(self) -> list[str]:
        return [
            check["id"]
            for check in self.checks
            if not check["valid"] and check["severity"] == "warning"
        ]


def load_tables(data_dir: Path) -> dict[str, pd.DataFrame]:
    tables = {
        "causal_scenarios": pd.read_csv(data_dir / "causal_scenarios.csv"),
        "pre_treatment_behavior": pd.read_csv(data_dir / "pre_treatment_behavior.csv"),
        "onboarding_assistance": pd.read_csv(data_dir / "onboarding_assistance.csv"),
        "outcomes": pd.read_csv(data_dir / "outcomes.csv"),
        "encouragement_assignments": pd.read_csv(data_dir / "encouragement_assignments.csv"),
    }
    bool_columns = {
        "onboarding_assistance": ["offered_assistance", "received_assistance"],
        "outcomes": ["activation_14d"],
        "encouragement_assignments": ["encouraged"],
        "pre_treatment_behavior": ["activation_14d_pre"],
    }
    for table, columns in bool_columns.items():
        for column in columns:
            tables[table][column] = to_bool(tables[table][column])
    numeric_columns = {
        "onboarding_assistance": ["friction_score", "eligibility_cutoff", "specialist_capacity"],
        "pre_treatment_behavior": [
            "friction_score",
            "app_crashes_before_time_zero",
            "sessions_before_time_zero",
            "specialist_capacity",
        ],
    }
    for table, columns in numeric_columns.items():
        for column in columns:
            tables[table][column] = pd.to_numeric(tables[table][column])
    return tables


def duplicate_rows(frame: pd.DataFrame, keys: list[str]) -> list[dict[str, Any]]:
    duplicates = frame[frame.duplicated(keys, keep=False)].sort_values(keys)
    return records(duplicates[keys]) if not duplicates.empty else []


def mean_bool(series: pd.Series) -> float:
    return float(series.astype(int).mean())


def mean_numeric(series: pd.Series) -> float:
    return float(pd.to_numeric(series).mean())


def difference(right: float, left: float) -> float:
    return float(right - left)


def scenario_map(scenarios: pd.DataFrame) -> dict[str, dict[str, Any]]:
    return {
        str(row["scenario_id"]): {key: scalar(value) for key, value in row.items()}
        for row in scenarios.to_dict(orient="records")
    }


def audit_grain(tables: dict[str, pd.DataFrame], checks: CheckBook) -> None:
    grain_specs = {
        "pre_treatment_behavior": ["user_id"],
        "onboarding_assistance": ["program_id", "user_id"],
        "outcomes": ["user_id"],
        "encouragement_assignments": ["encouragement_id"],
        "causal_scenarios": ["scenario_id"],
    }
    failures = [
        {"table": table, "keys": keys, "duplicates": duplicates}
        for table, keys in grain_specs.items()
        if (duplicates := duplicate_rows(tables[table], keys))
    ]
    checks.add(
        "source_tables_preserve_declared_grain",
        not failures,
        sample=failures or None,
        message="Each source table must keep the grain declared in phase data contract.",
    )


def audit_scenarios(
    scenarios: pd.DataFrame,
    spec: dict[str, Any],
    checks: CheckBook,
) -> dict[str, dict[str, Any]]:
    by_id = scenario_map(scenarios)
    required = {
        spec["rdd"]["scenario_id"]: "regression_discontinuity",
        spec["iv"]["scenario_id"]: "instrumental_variables",
    }
    missing_or_wrong = [
        {
            "scenario_id": scenario_id,
            "expected_design": expected_design,
            "actual": by_id.get(scenario_id),
        }
        for scenario_id, expected_design in required.items()
        if scenario_id not in by_id or by_id[scenario_id].get("design") != expected_design
    ]
    checks.add(
        "quasi_experiment_specs_match_scenario_registry",
        not missing_or_wrong,
        sample=missing_or_wrong or None,
        message="RDD and IV specs must point to causal_scenarios rows with matching design.",
    )
    return by_id


def build_user_level_frame(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    assistance = tables["onboarding_assistance"]
    baseline = tables["pre_treatment_behavior"]
    outcomes = tables["outcomes"]
    return (
        assistance.merge(baseline, on="user_id", suffixes=("", "_baseline"))
        .merge(outcomes, on="user_id")
        .sort_values("user_id")
        .reset_index(drop=True)
    )


def audit_rdd(
    user_frame: pd.DataFrame,
    scenarios: dict[str, dict[str, Any]],
    spec: dict[str, Any],
    checks: CheckBook,
) -> dict[str, Any]:
    rdd = spec["rdd"]
    score = rdd["running_variable"]
    cutoff = float(rdd["cutoff"])
    bandwidth = float(rdd["bandwidth"])
    treatment = rdd["treatment"]
    outcome = rdd["outcome"]
    local = user_frame[(user_frame[score] - cutoff).abs() <= bandwidth].copy()
    local["side"] = local[score].map(lambda value: "right" if value >= cutoff else "left")
    local["distance_to_cutoff"] = local[score] - cutoff

    side_counts = local["side"].value_counts().to_dict()
    minimum_each_side = int(rdd["minimum_each_side_n"])
    checks.add(
        "rdd_has_observations_on_both_sides_inside_bandwidth",
        side_counts.get("left", 0) >= minimum_each_side
        and side_counts.get("right", 0) >= minimum_each_side,
        sample={"side_counts": side_counts, "minimum_each_side_n": minimum_each_side},
        message="A local cutoff design needs enough rows on both sides of the cutoff.",
    )

    scenario = scenarios.get(rdd["scenario_id"], {})
    checks.add(
        "rdd_local_estimand_contract_is_explicit",
        scenario.get("estimand") == rdd["declared_estimand"]
        and rdd["declared_estimand"].startswith("local"),
        sample={
            "scenario_estimand": scenario.get("estimand"),
            "declared_estimand": rdd["declared_estimand"],
        },
        message="RDD may support a local estimand at the cutoff, not a population ATE.",
    )

    right = local[local["side"] == "right"]
    left = local[local["side"] == "left"]
    right_treatment_rate = mean_bool(right[treatment]) if not right.empty else 0.0
    left_treatment_rate = mean_bool(left[treatment]) if not left.empty else 0.0
    first_stage = difference(right_treatment_rate, left_treatment_rate)
    right_outcome_rate = mean_bool(right[outcome]) if not right.empty else 0.0
    left_outcome_rate = mean_bool(left[outcome]) if not left.empty else 0.0
    reduced_form = difference(right_outcome_rate, left_outcome_rate)
    wald = reduced_form / first_stage if abs(first_stage) > 1e-12 else None

    sharp_violations = local[
        ((local[score] >= cutoff) & (~local[treatment]))
        | ((local[score] < cutoff) & (local[treatment]))
    ][["user_id", score, treatment, "assignment_reason", "distance_to_cutoff"]]
    calculated_type = "fuzzy_rdd" if not sharp_violations.empty else "sharp_rdd"
    checks.add(
        "rdd_assignment_is_fuzzy_not_sharp",
        calculated_type == rdd["declared_design_type"],
        severity="warning",
        sample=records(sharp_violations) or None,
        message="Cutoff assignment is not deterministic; estimate must be framed as fuzzy RDD.",
    )

    lower = int(cutoff - bandwidth)
    upper = int(cutoff + bandwidth)
    density_ratio = (
        max(side_counts.get("left", 0), side_counts.get("right", 0))
        / max(1, min(side_counts.get("left", 0), side_counts.get("right", 0)))
    )
    checks.add(
        "rdd_no_visible_running_variable_bunching_inside_bandwidth",
        density_ratio <= float(rdd["max_density_ratio"]),
        sample={
            "window": [lower, upper],
            "side_counts": side_counts,
            "density_ratio": density_ratio,
        },
        message="A simple McCrary-style screen should not show strong bunching at cutoff.",
    )

    continuity_rows: list[dict[str, Any]] = []
    for covariate in rdd["continuity_covariates"]:
        right_mean = mean_numeric(right[covariate]) if not right.empty else 0.0
        left_mean = mean_numeric(left[covariate]) if not left.empty else 0.0
        continuity_rows.append(
            {
                "covariate": covariate,
                "left_mean": left_mean,
                "right_mean": right_mean,
                "difference": difference(right_mean, left_mean),
            }
        )
    max_abs_covariate_diff = max(abs(row["difference"]) for row in continuity_rows)
    checks.add(
        "rdd_observed_covariates_are_continuous_at_cutoff",
        max_abs_covariate_diff <= float(rdd["max_covariate_mean_diff"]),
        sample=continuity_rows,
        message="Pre-treatment covariates should not jump at the cutoff.",
    )

    local_rows = local[
        ["user_id", score, "distance_to_cutoff", "side", treatment, outcome, "assignment_reason"]
    ].sort_values([score, "user_id"])

    rdd_audit = {
        "design_id": rdd["design_id"],
        "scenario_id": rdd["scenario_id"],
        "declared_design_type": rdd["declared_design_type"],
        "calculated_design_type": calculated_type,
        "cutoff": cutoff,
        "bandwidth": bandwidth,
        "local_window": [lower, upper],
        "local_rows_n": int(len(local)),
        "side_counts": {key: int(value) for key, value in side_counts.items()},
        "local_rows": records(local_rows),
        "first_stage": {
            "right_treatment_rate": right_treatment_rate,
            "left_treatment_rate": left_treatment_rate,
            "discontinuity": first_stage,
        },
        "reduced_form": {
            "right_outcome_rate": right_outcome_rate,
            "left_outcome_rate": left_outcome_rate,
            "discontinuity": reduced_form,
        },
        "wald_local_effect_diagnostic": wald,
        "sharp_assignment_violations": records(sharp_violations),
        "density_screen": {
            "side_counts": {key: int(value) for key, value in side_counts.items()},
            "density_ratio": density_ratio,
            "max_density_ratio": rdd["max_density_ratio"],
        },
        "continuity_checks": continuity_rows,
    }
    checks.add(
        "rdd_effect_estimate_is_labeled_local_and_diagnostic",
        True,
        sample={
            "estimand": rdd["declared_estimand"],
            "wald_local_effect_diagnostic": wald,
        },
        message="The tiny-data Wald number is a design diagnostic, not a general ATE.",
    )
    checks.add(
        "rdd_tiny_wald_estimate_is_diagnostic_only",
        False,
        severity="warning",
        sample={
            "local_rows_n": int(len(local)),
            "wald_local_effect_diagnostic": wald,
        },
        message="Tiny local windows are useful for hand checks, not for stable effect claims.",
    )
    return rdd_audit


def audit_iv(
    tables: dict[str, pd.DataFrame],
    scenarios: dict[str, dict[str, Any]],
    spec: dict[str, Any],
    checks: CheckBook,
) -> dict[str, Any]:
    iv = spec["iv"]
    instrument = iv["instrument"]
    treatment = iv["treatment"]
    outcome = iv["outcome"]
    frame = (
        tables["encouragement_assignments"]
        .merge(tables["onboarding_assistance"], on="user_id")
        .merge(tables["outcomes"], on="user_id")
        .merge(tables["pre_treatment_behavior"], on="user_id", suffixes=("", "_baseline"))
        .sort_values("user_id")
        .reset_index(drop=True)
    )
    frame["instrument_group"] = frame[instrument].map(
        lambda value: "encouraged" if value else "not_encouraged"
    )

    encouraged = frame[frame[instrument]]
    not_encouraged = frame[~frame[instrument]]
    z_counts = frame["instrument_group"].value_counts().to_dict()
    treatment_rate_z1 = mean_bool(encouraged[treatment])
    treatment_rate_z0 = mean_bool(not_encouraged[treatment])
    first_stage = difference(treatment_rate_z1, treatment_rate_z0)
    outcome_rate_z1 = mean_bool(encouraged[outcome])
    outcome_rate_z0 = mean_bool(not_encouraged[outcome])
    reduced_form = difference(outcome_rate_z1, outcome_rate_z0)
    wald_late = reduced_form / first_stage if abs(first_stage) > 1e-12 else None

    checks.add(
        "iv_first_stage_is_relevant_enough_for_tiny_design",
        abs(first_stage) >= float(iv["minimum_first_stage"]),
        sample={
            "treatment_rate_z1": treatment_rate_z1,
            "treatment_rate_z0": treatment_rate_z0,
            "first_stage": first_stage,
            "minimum_first_stage": iv["minimum_first_stage"],
        },
        message="The instrument must move treatment take-up before any IV estimate is meaningful.",
    )

    scenario = scenarios.get(iv["scenario_id"], {})
    checks.add(
        "iv_estimand_contract_is_late_not_ate",
        scenario.get("estimand") == iv["declared_estimand"] == "LATE",
        sample={
            "scenario_estimand": scenario.get("estimand"),
            "declared_estimand": iv["declared_estimand"],
        },
        message="An IV design identifies LATE for compliers under assumptions, not ATE.",
    )

    balance_rows: list[dict[str, Any]] = []
    for covariate in iv["balance_covariates"]:
        if frame[covariate].dtype == bool:
            z1_mean = mean_bool(encouraged[covariate])
            z0_mean = mean_bool(not_encouraged[covariate])
        else:
            z1_mean = mean_numeric(encouraged[covariate])
            z0_mean = mean_numeric(not_encouraged[covariate])
        balance_rows.append(
            {
                "covariate": covariate,
                "encouraged_mean": z1_mean,
                "not_encouraged_mean": z0_mean,
                "difference": difference(z1_mean, z0_mean),
            }
        )
    max_abs_balance_diff = max(abs(row["difference"]) for row in balance_rows)
    checks.add(
        "iv_observed_pre_treatment_balance_is_plausible",
        max_abs_balance_diff <= float(iv["max_balance_abs_diff"]),
        sample=balance_rows,
        message="Instrument groups should look similar on pre-treatment covariates.",
    )

    assumptions_recorded = all(
        iv["assumptions"].get(key) for key in ("exclusion_restriction", "monotonicity")
    )
    checks.add(
        "iv_exclusion_and_monotonicity_are_recorded_as_assumptions",
        assumptions_recorded,
        sample=iv["assumptions"],
        message="Exclusion and monotonicity must be documented before IV estimation.",
    )
    checks.add(
        "iv_exclusion_and_monotonicity_cannot_be_proven_from_observed_data",
        False,
        severity="warning",
        sample=iv["assumptions"],
        message=(
            "Observed data can falsify some IV assumptions, but cannot prove exclusion "
            "or monotonicity."
        ),
    )

    iv_rows = frame[
        [
            "user_id",
            instrument,
            treatment,
            outcome,
            "instrument_version",
            "assignment_reason",
            "friction_score",
        ]
    ].sort_values(["encouraged", "user_id"], ascending=[False, True])
    return {
        "design_id": iv["design_id"],
        "scenario_id": iv["scenario_id"],
        "declared_estimand": iv["declared_estimand"],
        "rows_n": int(len(frame)),
        "instrument_counts": {key: int(value) for key, value in z_counts.items()},
        "first_stage": {
            "treatment_rate_z1": treatment_rate_z1,
            "treatment_rate_z0": treatment_rate_z0,
            "first_stage": first_stage,
            "minimum_first_stage": iv["minimum_first_stage"],
        },
        "reduced_form": {
            "outcome_rate_z1": outcome_rate_z1,
            "outcome_rate_z0": outcome_rate_z0,
            "reduced_form": reduced_form,
        },
        "wald_late": wald_late,
        "balance_checks": balance_rows,
        "assumptions": iv["assumptions"],
        "rows": records(iv_rows),
    }


def calculated_candidate_status(
    candidate: dict[str, Any],
    *,
    rdd_audit: dict[str, Any],
    iv_audit: dict[str, Any],
    spec: dict[str, Any],
) -> str:
    design_id = candidate["design_id"]
    if design_id == "primary_fuzzy_score_rdd":
        if rdd_audit["calculated_design_type"] != "fuzzy_rdd":
            return "invalid_not_fuzzy_rdd"
        return "estimable_local_with_assumptions"
    if design_id == "sharp_score_cutoff_offer":
        if rdd_audit["sharp_assignment_violations"]:
            return "invalid_requires_fuzzy_rdd"
        return "estimable_sharp_rdd"
    if design_id == "wide_bandwidth_ignores_locality":
        if float(candidate["bandwidth"]) > float(spec["rdd"]["bandwidth"]):
            return "invalid_not_local"
        return "estimable_local_with_assumptions"
    if design_id == "capacity_encouragement_late":
        if abs(iv_audit["first_stage"]["first_stage"]) >= float(spec["iv"]["minimum_first_stage"]):
            return "estimable_late_with_assumptions"
        return "invalid_weak_instrument"
    if design_id == "encouragement_claims_ate":
        if candidate.get("claimed_estimand") == "ATE":
            return "invalid_late_generalized_to_ate"
        return "estimable_late_with_assumptions"
    if design_id == "weak_encouragement_variant":
        threshold = float(candidate["minimum_first_stage"])
        if abs(iv_audit["first_stage"]["first_stage"]) < threshold:
            return "invalid_weak_instrument"
        return "estimable_late_with_assumptions"
    return "unknown_candidate_design"


def audit_candidates(
    spec: dict[str, Any],
    checks: CheckBook,
    *,
    rdd_audit: dict[str, Any],
    iv_audit: dict[str, Any],
) -> list[dict[str, Any]]:
    candidate_rows: list[dict[str, Any]] = []
    for section in ("rdd", "iv"):
        for candidate in spec[section]["candidate_designs"]:
            calculated = calculated_candidate_status(
                candidate,
                rdd_audit=rdd_audit,
                iv_audit=iv_audit,
                spec=spec,
            )
            candidate_rows.append(
                {
                    "design_id": candidate["design_id"],
                    "family": section,
                    "declared_status": candidate["declared_status"],
                    "calculated_status": calculated,
                }
            )
    mismatches = [
        row
        for row in candidate_rows
        if row["declared_status"] != row["calculated_status"]
    ]
    checks.add(
        "candidate_design_statuses_match_policy",
        not mismatches,
        sample=mismatches or None,
        message="Candidate quasi-experimental designs must be labeled by the audit policy.",
    )
    return candidate_rows


def audit_claim_policy(
    checks: CheckBook,
    *,
    spec: dict[str, Any],
    rdd_audit: dict[str, Any],
    iv_audit: dict[str, Any],
) -> dict[str, Any]:
    required_for_local_claim = [
        "rdd_has_observations_on_both_sides_inside_bandwidth",
        "rdd_local_estimand_contract_is_explicit",
        "rdd_no_visible_running_variable_bunching_inside_bandwidth",
        "rdd_observed_covariates_are_continuous_at_cutoff",
        "iv_first_stage_is_relevant_enough_for_tiny_design",
        "iv_estimand_contract_is_late_not_ate",
        "iv_observed_pre_treatment_balance_is_plausible",
        "candidate_design_statuses_match_policy",
    ]
    by_id = {check["id"]: check for check in checks.checks}
    failed = [
        check_id
        for check_id in required_for_local_claim
        if check_id not in by_id or not by_id[check_id]["valid"]
    ]
    claimed_estimands = {
        spec["rdd"]["design_id"]: spec["rdd"]["declared_estimand"],
        spec["iv"]["design_id"]: spec["iv"]["declared_estimand"],
    }
    overgeneralized = [
        estimand
        for estimand in claimed_estimands.values()
        if estimand == "ATE"
    ]
    allowed = not failed and not overgeneralized
    checks.add(
        "claim_policy_allows_only_local_rdd_and_late_wording",
        allowed,
        sample={
            "failed_required_checks": failed,
            "claimed_estimands": claimed_estimands,
            "overgeneralized_estimands": overgeneralized,
        },
        message="The handoff may use local RDD/LATE wording only if design diagnostics pass.",
    )
    return {
        "allowed_local_claim": allowed,
        "required_checks": required_for_local_claim,
        "failed_required_checks": failed,
        "wording": (
            "Under stated assumptions, the RDD evidence is local to the friction-score cutoff "
            "and the IV evidence is LATE for compliers, not a population ATE."
            if allowed
            else "Do not make a causal quasi-experimental claim until blocking diagnostics pass."
        ),
    }


def audit_quasi_experiments(data_dir: Path, spec: dict[str, Any]) -> dict[str, Any]:
    checks = CheckBook([])
    tables = load_tables(data_dir)
    audit_grain(tables, checks)
    scenarios = audit_scenarios(tables["causal_scenarios"], spec, checks)
    user_frame = build_user_level_frame(tables)
    rdd_audit = audit_rdd(user_frame, scenarios, spec, checks)
    iv_audit = audit_iv(tables, scenarios, spec, checks)
    candidate_audits = audit_candidates(
        spec,
        checks,
        rdd_audit=rdd_audit,
        iv_audit=iv_audit,
    )
    policy = audit_claim_policy(
        checks,
        spec=spec,
        rdd_audit=rdd_audit,
        iv_audit=iv_audit,
    )
    summary = {
        "spec_id": spec["spec_id"],
        "rdd_design_id": rdd_audit["design_id"],
        "iv_design_id": iv_audit["design_id"],
        "rdd_cutoff": rdd_audit["cutoff"],
        "rdd_bandwidth": rdd_audit["bandwidth"],
        "rdd_local_rows_n": rdd_audit["local_rows_n"],
        "rdd_first_stage": rdd_audit["first_stage"]["discontinuity"],
        "rdd_reduced_form": rdd_audit["reduced_form"]["discontinuity"],
        "rdd_wald_local_effect_diagnostic": rdd_audit["wald_local_effect_diagnostic"],
        "iv_rows_n": iv_audit["rows_n"],
        "iv_first_stage": iv_audit["first_stage"]["first_stage"],
        "iv_reduced_form": iv_audit["reduced_form"]["reduced_form"],
        "iv_wald_late": iv_audit["wald_late"],
        "allowed_local_claim": policy["allowed_local_claim"],
        "blocking_checks": checks.blocking,
        "warning_checks": checks.warnings,
    }
    return {
        "valid": not checks.blocking,
        "summary": summary,
        "rdd_design_audit": rdd_audit,
        "iv_design_audit": iv_audit,
        "candidate_design_audits": candidate_audits,
        "claim_policy": policy,
        "checks": checks.checks,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit RDD and instrumental-variable design before estimation."
    )
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--fail-on-invalid", action="store_true")
    args = parser.parse_args()

    report = audit_quasi_experiments(args.data_dir, read_json(args.spec))
    write_json(args.output, report)
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    if args.fail_on_invalid and not report["valid"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
