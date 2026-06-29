from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy.special import expit


def read_json(path: str | Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as source:
        return json.load(source)


def write_json(path: str | Path, payload: dict[str, Any]) -> None:
    Path(path).write_text(
        json.dumps(to_jsonable(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def to_jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [to_jsonable(item) for item in value]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if pd.isna(value):
        return None
    return value


def make_check(
    check_id: str,
    valid: bool,
    message: str,
    *,
    severity: str = "error",
    sample: Any | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": check_id,
        "valid": valid,
        "severity": severity,
        "message": message,
    }
    if sample is not None:
        payload["sample"] = sample
    return payload


def invalid_report(checks: list[dict[str, Any]]) -> dict[str, Any]:
    blocking = [
        check["id"] for check in checks if check["severity"] == "error" and not check["valid"]
    ]
    warnings = [
        check["id"] for check in checks if check["severity"] == "warning" and not check["valid"]
    ]
    return {
        "valid": not blocking,
        "summary": {
            "blocking_checks": blocking,
            "warning_checks": warnings,
        },
        "checks": checks,
    }


def as_bool(series: pd.Series) -> pd.Series:
    if series.dtype == bool:
        return series
    return series.astype(str).str.lower().isin({"true", "1", "yes"})


def load_source_tables(data_dir: str | Path) -> dict[str, pd.DataFrame]:
    root = Path(data_dir)
    return {
        "users": pd.read_csv(root / "users.csv"),
        "pre_treatment_behavior": pd.read_csv(root / "pre_treatment_behavior.csv"),
        "onboarding_assistance": pd.read_csv(root / "onboarding_assistance.csv"),
        "outcomes": pd.read_csv(root / "outcomes.csv"),
    }


def validate_table_grains(tables: dict[str, pd.DataFrame]) -> list[dict[str, Any]]:
    key_specs = {
        "users": ["user_id"],
        "pre_treatment_behavior": ["user_id"],
        "onboarding_assistance": ["program_id", "user_id"],
        "outcomes": ["user_id"],
    }
    errors = []
    for table_name, keys in key_specs.items():
        table = tables[table_name]
        missing = [key for key in keys if key not in table.columns]
        if missing:
            errors.append({"table": table_name, "missing_keys": missing})
            continue
        duplicates = table[table.duplicated(keys, keep=False)][keys].to_dict("records")
        if duplicates:
            errors.append({"table": table_name, "duplicate_keys": duplicates[:10]})
    return [
        make_check(
            "source_tables_preserve_declared_grain",
            not errors,
            "Source tables preserve user/program grain before joining the IPW/AIPW cohort.",
            sample=errors or None,
        )
    ]


def build_analysis_cohort(
    tables: dict[str, pd.DataFrame],
    target_trial: dict[str, Any],
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    users = tables["users"].copy()
    pre = tables["pre_treatment_behavior"].copy()
    assistance = tables["onboarding_assistance"].copy()
    outcomes = tables["outcomes"].copy()

    for frame, columns in [
        (users, ["is_test_user", "eligible_for_program"]),
        (pre, ["activation_14d_pre"]),
        (assistance, ["received_assistance", "offered_assistance"]),
        (outcomes, ["activation_14d", "telemetry_complete_30d"]),
    ]:
        for column in columns:
            if column in frame:
                frame[column] = as_bool(frame[column])

    assistance_subset = assistance[
        [
            "user_id",
            "program_id",
            "received_assistance",
            "offered_assistance",
            "started_at",
            "offered_at",
            "assignment_reason",
        ]
    ].copy()

    cohort = (
        users.merge(pre, on="user_id", how="inner", validate="one_to_one")
        .merge(assistance_subset, on="user_id", how="inner", validate="one_to_one")
        .merge(outcomes, on="user_id", how="inner", validate="one_to_one")
    )

    mask = pd.Series(True, index=cohort.index)
    criteria_errors = []
    for criterion in target_trial.get("target_population", {}).get("criteria", []):
        field = criterion.get("field")
        operator = criterion.get("operator")
        value = criterion.get("value")
        if field not in cohort:
            criteria_errors.append({"field": field, "reason": "missing from joined cohort"})
            continue
        column = cohort[field]
        if column.dtype == bool:
            value = bool(value)
        if operator == "==":
            mask &= column == value
        elif operator == ">=":
            mask &= pd.to_numeric(column) >= float(value)
        else:
            criteria_errors.append({"field": field, "operator": operator})

    cohort = cohort[mask].copy()
    cohort["time_zero_ts"] = pd.to_datetime(cohort["time_zero"], utc=True)
    cohort["started_at_ts"] = pd.to_datetime(cohort["started_at"], utc=True, errors="coerce")
    grace_hours = target_trial.get("treatment", {}).get("grace_period_hours", 24)
    start_delay_hours = (cohort["started_at_ts"] - cohort["time_zero_ts"]).dt.total_seconds() / 3600
    cohort["assisted_within_24h"] = (
        cohort["received_assistance"]
        & cohort["started_at_ts"].notna()
        & (start_delay_hours >= 0)
        & (start_delay_hours <= grace_hours)
    )
    cohort["treatment"] = cohort["assisted_within_24h"].astype(int)
    cohort["outcome"] = cohort["activation_14d"].astype(int)
    cohort["followup_end_ts"] = pd.to_datetime(cohort["followup_end_at"], utc=True)
    cohort["followup_days"] = (
        cohort["followup_end_ts"] - cohort["time_zero_ts"]
    ).dt.total_seconds() / 86400

    timing_errors = []
    treated = cohort[cohort["received_assistance"]]
    for _, row in treated.iterrows():
        if pd.isna(row["started_at_ts"]):
            timing_errors.append({"user_id": row["user_id"], "reason": "missing started_at"})
        elif row["started_at_ts"] < row["time_zero_ts"]:
            timing_errors.append({"user_id": row["user_id"], "reason": "starts before time zero"})
        elif row["treatment"] != 1:
            timing_errors.append({"user_id": row["user_id"], "reason": "outside grace period"})

    followup_errors = cohort[cohort["followup_days"] < 14][["user_id", "followup_days"]].to_dict(
        "records"
    )

    checks = [
        make_check(
            "target_population_criteria_are_supported",
            not criteria_errors,
            "Target-population criteria are applied from target_trial_spec.json.",
            sample=criteria_errors or None,
        ),
        make_check(
            "analysis_cohort_has_expected_treated_and_comparator_units",
            len(cohort) > 0
            and int(cohort["treatment"].sum()) > 0
            and int((1 - cohort["treatment"]).sum()) > 0,
            "Analysis cohort contains both treatment strategies.",
            sample={
                "n": len(cohort),
                "treated": int(cohort["treatment"].sum()),
                "comparator": int((1 - cohort["treatment"]).sum()),
            },
        ),
        make_check(
            "treatment_timing_respects_grace_period",
            not timing_errors,
            "Observed treatment starts after time zero and within the declared grace period.",
            sample=timing_errors or None,
        ),
        make_check(
            "primary_outcome_followup_is_complete",
            not followup_errors,
            "Every analysis unit has enough follow-up for activation_14d.",
            sample=followup_errors or None,
        ),
    ]
    return cohort.reset_index(drop=True), checks


def component_values(frame: pd.DataFrame, component: dict[str, Any]) -> pd.Series:
    kind = component["type"]
    field = component["field"]
    if field not in frame:
        raise KeyError(f"Missing source field for derived feature: {field}")
    if kind == "scaled_numeric":
        return (
            (pd.to_numeric(frame[field]) - float(component["center"]))
            / float(component["scale"])
            * float(component["weight"])
        )
    if kind == "numeric":
        return pd.to_numeric(frame[field]) * float(component["weight"])
    if kind == "categorical_map":
        values = frame[field].map(component["values"])
        if values.isna().any():
            unknown = sorted(frame.loc[values.isna(), field].astype(str).unique())
            raise ValueError(f"Unknown categories for {field}: {unknown}")
        return values.astype(float)
    raise ValueError(f"Unknown derived feature component type: {kind}")


def add_derived_features(frame: pd.DataFrame, model_spec: dict[str, Any]) -> pd.DataFrame:
    result = frame.copy()
    for feature in model_spec.get("derived_features", []):
        values = pd.Series(0.0, index=result.index)
        for component in feature.get("components", []):
            values = values + component_values(result, component)
        result[feature["name"]] = values
    return result


def model_source_variables(model_spec: dict[str, Any]) -> set[str]:
    sources = {
        variable
        for variable in model_spec.get("direct_numeric_terms", [])
        if variable != "treatment"
    }
    for feature in model_spec.get("derived_features", []):
        sources.update(feature.get("source_variables", []))
    return sources


def allowed_action_from_gate(
    adjustment_gate: dict[str, Any], action_id: str
) -> dict[str, Any] | None:
    return next(
        (
            action
            for action in adjustment_gate.get("candidate_action_audits", [])
            if action.get("action_id") == action_id
        ),
        None,
    )


def candidate_status(
    candidate: dict[str, Any],
    *,
    required_sources: set[str],
    bad_controls: set[str],
) -> str:
    propensity_sources = set(candidate.get("propensity_source_variables", []))
    outcome_sources = set(candidate.get("outcome_source_variables", []))
    filter_variables = set(candidate.get("filter_variables", []))
    if (propensity_sources | outcome_sources | filter_variables) & bad_controls:
        return "invalid_bad_control"
    if not required_sources.issubset(propensity_sources) or not required_sources.issubset(
        outcome_sources
    ):
        return "invalid_omits_required_adjustment_sources"
    return "estimable_with_warnings"


def validate_estimator_spec(
    estimator_spec: dict[str, Any],
    target_trial: dict[str, Any],
    estimand: dict[str, Any],
    adjustment_gate: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    required = [
        "ipw_aipw_spec_id",
        "question_id",
        "estimand_id",
        "trial_id",
        "adjustment_gate_id",
        "adjustment_action_id",
        "primary_estimator_id",
        "treatment",
        "outcome",
        "propensity_model",
        "outcome_model",
        "diagnostics",
        "candidate_estimators",
        "claim_policy",
    ]
    missing = [field for field in required if field not in estimator_spec]
    checks = [
        make_check(
            "ipw_aipw_spec_required_fields",
            not missing,
            "IPW/AIPW spec contains required fields.",
            sample=missing or None,
        )
    ]

    alignment_errors = []
    expected = {
        "question_id": target_trial.get("question_id"),
        "estimand_id": estimand.get("estimand_id"),
        "trial_id": target_trial.get("trial_id"),
        "outcome": estimand.get("outcome_id"),
    }
    for field, expected_value in expected.items():
        if estimator_spec.get(field) != expected_value:
            alignment_errors.append(
                {"field": field, "expected": expected_value, "actual": estimator_spec.get(field)}
            )
    checks.append(
        make_check(
            "ipw_aipw_spec_aligns_with_target_trial_and_estimand",
            not alignment_errors,
            "Estimator spec aligns with target trial and ATE estimand.",
            sample=alignment_errors or None,
        )
    )

    action = allowed_action_from_gate(adjustment_gate, estimator_spec.get("adjustment_action_id"))
    bad_controls = set(adjustment_gate.get("summary", {}).get("bad_control_variables", []))
    required_sources = set(action.get("variables", [])) if action else set()
    checks.append(
        make_check(
            "adjustment_gate_allows_primary_observed_baseline_action",
            action is not None and action.get("allowed_for_estimation") is True,
            "Primary estimator reuses the allowed observed-baseline adjustment action from 13/04.",
            sample=None
            if action is not None
            else {"adjustment_action_id": estimator_spec.get("adjustment_action_id")},
        )
    )

    propensity_sources = model_source_variables(estimator_spec.get("propensity_model", {}))
    outcome_sources = model_source_variables(estimator_spec.get("outcome_model", {}))
    source_errors = {
        "propensity_bad_controls": sorted(propensity_sources & bad_controls),
        "outcome_bad_controls": sorted(outcome_sources & bad_controls),
    }
    checks.append(
        make_check(
            "primary_models_use_only_allowed_baseline_sources",
            not source_errors["propensity_bad_controls"]
            and not source_errors["outcome_bad_controls"],
            "Primary propensity and outcome models do not use mediators, colliders, "
            "selection variables or outcome leakage.",
            sample=source_errors if any(source_errors.values()) else None,
        )
    )

    coverage_errors = {
        "propensity_missing_sources": sorted(required_sources - propensity_sources),
        "outcome_missing_sources": sorted(required_sources - outcome_sources),
    }
    checks.append(
        make_check(
            "primary_models_cover_required_adjustment_sources",
            not coverage_errors["propensity_missing_sources"]
            and not coverage_errors["outcome_missing_sources"],
            "Primary propensity and outcome models cover the observed-baseline adjustment basis.",
            sample=coverage_errors if any(coverage_errors.values()) else None,
        )
    )

    diagnostics = estimator_spec.get("diagnostics", {})
    trim_thresholds = diagnostics.get("trim_thresholds", [])
    trim_errors = [
        threshold
        for threshold in trim_thresholds
        if not isinstance(threshold, int | float) or threshold < 0 or threshold >= 0.5
    ]
    checks.append(
        make_check(
            "trimming_thresholds_are_inside_probability_range",
            not trim_errors and len(trim_thresholds) > 0,
            "Trimming schedule uses symmetric thresholds inside [0, 0.5).",
            sample=trim_errors or None,
        )
    )

    candidate_audits = []
    status_errors = []
    for candidate in estimator_spec.get("candidate_estimators", []):
        calculated = candidate_status(
            candidate,
            required_sources=required_sources,
            bad_controls=bad_controls,
        )
        audit = {
            "estimator_id": candidate.get("estimator_id"),
            "declared_status": candidate.get("declared_status"),
            "calculated_status": calculated,
            "bad_control_variables": sorted(
                (
                    set(candidate.get("propensity_source_variables", []))
                    | set(candidate.get("outcome_source_variables", []))
                    | set(candidate.get("filter_variables", []))
                )
                & bad_controls
            ),
            "missing_propensity_sources": sorted(
                required_sources - set(candidate.get("propensity_source_variables", []))
            ),
            "missing_outcome_sources": sorted(
                required_sources - set(candidate.get("outcome_source_variables", []))
            ),
        }
        candidate_audits.append(audit)
        if audit["declared_status"] != calculated:
            status_errors.append(audit)
    checks.append(
        make_check(
            "candidate_estimator_statuses_match_policy",
            not status_errors,
            "Candidate estimator statuses match bad-control and source-coverage policy.",
            sample=status_errors or None,
        )
    )

    open_unmeasured = adjustment_gate.get("summary", {}).get(
        "primary_open_unmeasured_backdoor_paths"
    )
    claim_policy = estimator_spec.get("claim_policy", {})
    claim_errors = []
    if claim_policy.get("allowed_effect_claim") and open_unmeasured:
        claim_errors.append(
            {
                "field": "allowed_effect_claim",
                "reason": "unmeasured backdoor path remains open",
                "open_unmeasured_backdoor_paths": open_unmeasured,
            }
        )
    checks.append(
        make_check(
            "claim_policy_respects_unmeasured_confounding_limitation",
            not claim_errors,
            "Estimator may report model-based estimates but cannot claim a proven causal "
            "effect while unmeasured confounding remains.",
            sample=claim_errors or None,
        )
    )

    context = {
        "required_sources": sorted(required_sources),
        "bad_control_variables": sorted(bad_controls),
        "candidate_estimator_audits": candidate_audits,
    }
    return checks, context


def numeric_series(frame: pd.DataFrame, column: str) -> pd.Series:
    values = frame[column]
    if values.dtype == bool:
        return values.astype(int)
    return pd.to_numeric(values)


def propensity_design_matrix(
    frame: pd.DataFrame,
    model_spec: dict[str, Any],
) -> tuple[np.ndarray, list[dict[str, float | str]]]:
    terms = [term for term in model_spec["terms"] if term != "intercept"]
    columns = []
    standardization = []
    for term in terms:
        if term not in frame:
            raise KeyError(f"Missing propensity term: {term}")
        values = numeric_series(frame, term).astype(float)
        if model_spec.get("standardize_numeric_terms", True):
            mean = float(values.mean())
            std = float(values.std(ddof=0))
            if std == 0:
                std = 1.0
            transformed = (values - mean) / std
        else:
            mean = 0.0
            std = 1.0
            transformed = values
        standardization.append({"term": term, "mean": mean, "std": std})
        columns.append(transformed.to_numpy())
    return np.column_stack([np.ones(len(frame)), *columns]), standardization


def fit_ridge_logistic(
    design: np.ndarray,
    treatment: np.ndarray,
    *,
    alpha: float,
    max_iter: int = 100,
    tolerance: float = 1e-12,
) -> dict[str, Any]:
    beta = np.zeros(design.shape[1])
    penalty = np.eye(design.shape[1]) * alpha
    penalty[0, 0] = 0.0
    converged = False
    iterations = 0
    for iteration in range(1, max_iter + 1):
        iterations = iteration
        fitted = expit(design @ beta)
        weights = fitted * (1 - fitted)
        gradient = design.T @ (treatment - fitted) - penalty @ beta
        hessian = -((design.T * weights) @ design) - penalty
        try:
            step = np.linalg.solve(hessian, gradient)
        except np.linalg.LinAlgError:
            step = np.linalg.pinv(hessian) @ gradient
        candidate = beta - step
        if float(np.max(np.abs(candidate - beta))) < tolerance:
            beta = candidate
            converged = True
            break
        beta = candidate
    fitted = expit(design @ beta)
    gradient = design.T @ (treatment - fitted) - penalty @ beta
    return {
        "params": beta,
        "fitted": fitted,
        "iterations": iterations,
        "converged": converged,
        "max_abs_penalized_gradient": float(np.max(np.abs(gradient))),
    }


def outcome_design_matrix(
    frame: pd.DataFrame,
    model_spec: dict[str, Any],
) -> tuple[np.ndarray, list[str]]:
    terms = [term for term in model_spec["terms"] if term != "intercept"]
    columns = []
    for term in terms:
        if term not in frame:
            raise KeyError(f"Missing outcome term: {term}")
        columns.append(numeric_series(frame, term).astype(float).to_numpy())
    return np.column_stack([np.ones(len(frame)), *columns]), ["intercept", *terms]


def fit_outcome_ols(frame: pd.DataFrame, model_spec: dict[str, Any]) -> dict[str, Any]:
    design, terms = outcome_design_matrix(frame, model_spec)
    outcome = frame["outcome"].to_numpy(dtype=float)
    params = np.linalg.lstsq(design, outcome, rcond=None)[0]
    predictions = design @ params

    statsmodels_fit = sm.OLS(outcome, design).fit()
    statsmodels_predictions = statsmodels_fit.predict(design)
    max_param_diff = float(np.max(np.abs(params - statsmodels_fit.params)))
    max_prediction_diff = float(np.max(np.abs(predictions - statsmodels_predictions)))

    cf_predictions = {}
    treatment_term = model_spec["treatment_term"]
    for treatment_value in [1, 0]:
        counterfactual = frame.copy()
        counterfactual[treatment_term] = treatment_value
        cf_design, _ = outcome_design_matrix(counterfactual, model_spec)
        cf_predictions[str(treatment_value)] = cf_design @ params

    return {
        "terms": terms,
        "params": params,
        "predictions_observed": predictions,
        "m1": cf_predictions["1"],
        "m0": cf_predictions["0"],
        "manual_statsmodels_max_param_diff": max_param_diff,
        "manual_statsmodels_max_prediction_diff": max_prediction_diff,
    }


def effective_sample_size(weights: np.ndarray) -> float:
    total = float(weights.sum())
    squared = float(np.square(weights).sum())
    if squared == 0:
        return 0.0
    return total * total / squared


def ipw_and_aipw_estimates(
    treatment: np.ndarray,
    outcome: np.ndarray,
    propensity: np.ndarray,
    m1: np.ndarray,
    m0: np.ndarray,
) -> dict[str, float]:
    treated_weight = treatment / propensity
    control_weight = (1 - treatment) / (1 - propensity)
    mu1_ht = float(np.mean(treated_weight * outcome))
    mu0_ht = float(np.mean(control_weight * outcome))
    mu1_hajek = float(np.sum(treated_weight * outcome) / np.sum(treated_weight))
    mu0_hajek = float(np.sum(control_weight * outcome) / np.sum(control_weight))
    aipw = float(
        np.mean(
            (m1 - m0)
            + treatment * (outcome - m1) / propensity
            - (1 - treatment) * (outcome - m0) / (1 - propensity)
        )
    )
    return {
        "ipw_ht_mu1": mu1_ht,
        "ipw_ht_mu0": mu0_ht,
        "ipw_ht_ate": mu1_ht - mu0_ht,
        "ipw_hajek_mu1": mu1_hajek,
        "ipw_hajek_mu0": mu0_hajek,
        "ipw_hajek_ate": mu1_hajek - mu0_hajek,
        "aipw_ate": aipw,
        "outcome_regression_ate": float(np.mean(m1 - m0)),
    }


def estimate_with_model_pair(
    cohort: pd.DataFrame,
    *,
    propensity_model: dict[str, Any],
    outcome_model: dict[str, Any],
    diagnostics: dict[str, Any],
    include_rows: bool = False,
) -> dict[str, Any]:
    propensity_frame = add_derived_features(cohort, propensity_model)
    propensity_design, standardization = propensity_design_matrix(
        propensity_frame, propensity_model
    )
    treatment = cohort["treatment"].to_numpy(dtype=float)
    outcome = cohort["outcome"].to_numpy(dtype=float)
    propensity_fit = fit_ridge_logistic(
        propensity_design,
        treatment,
        alpha=float(propensity_model.get("alpha", 0.0)),
    )
    raw_propensity = propensity_fit["fitted"]
    epsilon = float(propensity_model.get("clip_epsilon", 0.0))
    propensity = np.clip(raw_propensity, epsilon, 1 - epsilon)

    outcome_frame = add_derived_features(cohort, outcome_model)
    outcome_fit = fit_outcome_ols(outcome_frame, outcome_model)
    m1 = outcome_fit["m1"]
    m0 = outcome_fit["m0"]

    p_treated = float(treatment.mean())
    unstabilized_weights = np.where(treatment == 1, 1 / propensity, 1 / (1 - propensity))
    stabilized_weights = np.where(
        treatment == 1,
        p_treated / propensity,
        (1 - p_treated) / (1 - propensity),
    )

    estimates = ipw_and_aipw_estimates(treatment, outcome, propensity, m1, m0)
    estimates["naive_risk_difference"] = float(
        outcome[treatment == 1].mean() - outcome[treatment == 0].mean()
    )

    lower, upper = diagnostics["overlap_warning_bounds"]
    severe_lower, severe_upper = diagnostics["overlap_severe_bounds"]
    outside_warning = (propensity < lower) | (propensity > upper)
    outside_severe = (propensity < severe_lower) | (propensity > severe_upper)

    row_table = pd.DataFrame(
        {
            "user_id": cohort["user_id"],
            "treatment": cohort["treatment"],
            "outcome": cohort["outcome"],
            "propensity_score": propensity,
            "raw_propensity_score": raw_propensity,
            "stabilized_ate_weight": stabilized_weights,
            "unstabilized_ate_weight": unstabilized_weights,
            "m1": m1,
            "m0": m0,
        }
    )

    trimming = []
    for threshold in diagnostics["trim_thresholds"]:
        mask = (propensity >= threshold) & (propensity <= 1 - threshold)
        retained = row_table[mask].copy()
        removed = row_table[~mask].copy()
        retained_treated = int(retained["treatment"].sum())
        retained_control = int((1 - retained["treatment"]).sum())
        trimming_row: dict[str, Any] = {
            "threshold": threshold,
            "retained_n": int(mask.sum()),
            "removed_n": int((~mask).sum()),
            "retained_treated_n": retained_treated,
            "retained_control_n": retained_control,
            "removed_user_ids": removed["user_id"].tolist(),
        }
        if retained_treated > 0 and retained_control > 0:
            subset_estimates = ipw_and_aipw_estimates(
                treatment[mask],
                outcome[mask],
                propensity[mask],
                m1[mask],
                m0[mask],
            )
            trimming_row.update(
                {
                    "estimable": True,
                    "ipw_hajek_ate": subset_estimates["ipw_hajek_ate"],
                    "aipw_ate": subset_estimates["aipw_ate"],
                }
            )
        else:
            trimming_row.update({"estimable": False, "reason": "one_arm_removed_by_trimming"})
        trimming.append(trimming_row)

    result: dict[str, Any] = {
        "propensity_model": {
            "model_id": propensity_model["model_id"],
            "terms": propensity_model["terms"],
            "alpha": propensity_model.get("alpha"),
            "params": dict(zip(propensity_model["terms"], propensity_fit["params"], strict=True)),
            "standardization": standardization,
            "converged": propensity_fit["converged"],
            "iterations": propensity_fit["iterations"],
            "max_abs_penalized_gradient": propensity_fit["max_abs_penalized_gradient"],
        },
        "outcome_model": {
            "model_id": outcome_model["model_id"],
            "terms": outcome_fit["terms"],
            "params": dict(zip(outcome_fit["terms"], outcome_fit["params"], strict=True)),
            "manual_statsmodels_max_param_diff": outcome_fit["manual_statsmodels_max_param_diff"],
            "manual_statsmodels_max_prediction_diff": outcome_fit[
                "manual_statsmodels_max_prediction_diff"
            ],
        },
        "estimates": estimates,
        "overlap": {
            "min_propensity": float(propensity.min()),
            "max_propensity": float(propensity.max()),
            "outside_warning_bounds_n": int(outside_warning.sum()),
            "outside_severe_bounds_n": int(outside_severe.sum()),
            "outside_warning_bounds": row_table.loc[
                outside_warning, ["user_id", "treatment", "propensity_score"]
            ].to_dict("records"),
            "outside_severe_bounds": row_table.loc[
                outside_severe, ["user_id", "treatment", "propensity_score"]
            ].to_dict("records"),
        },
        "weights": {
            "max_stabilized_weight": float(stabilized_weights.max()),
            "max_unstabilized_weight": float(unstabilized_weights.max()),
            "stabilized_effective_sample_size": effective_sample_size(stabilized_weights),
            "unstabilized_effective_sample_size": effective_sample_size(unstabilized_weights),
            "treated_unstabilized_effective_sample_size": effective_sample_size(
                unstabilized_weights[treatment == 1]
            ),
            "control_unstabilized_effective_sample_size": effective_sample_size(
                unstabilized_weights[treatment == 0]
            ),
        },
        "trimming_sensitivity": trimming,
        "outcome_prediction_range": {
            "m1_min": float(m1.min()),
            "m1_max": float(m1.max()),
            "m0_min": float(m0.min()),
            "m0_max": float(m0.max()),
        },
    }
    if include_rows:
        result["unit_scores"] = row_table.to_dict("records")
    return result


def diagnostic_checks(
    model_result: dict[str, Any], diagnostics: dict[str, Any]
) -> list[dict[str, Any]]:
    overlap = model_result["overlap"]
    weights = model_result["weights"]
    prediction_range = model_result["outcome_prediction_range"]
    probability_lower, probability_upper = diagnostics["probability_bounds"]

    material_trim_rows = [
        row
        for row in model_result["trimming_sensitivity"]
        if row["removed_n"] / (row["retained_n"] + row["removed_n"])
        > diagnostics["material_retention_loss_fraction"]
    ]

    prediction_outside_bounds = [
        {"field": key, "value": value}
        for key, value in prediction_range.items()
        if value < probability_lower or value > probability_upper
    ]

    return [
        make_check(
            "ridge_propensity_solver_converged",
            model_result["propensity_model"]["converged"],
            "Manual ridge logistic propensity solver converged.",
            sample={
                "iterations": model_result["propensity_model"]["iterations"],
                "max_abs_penalized_gradient": model_result["propensity_model"][
                    "max_abs_penalized_gradient"
                ],
            },
        ),
        make_check(
            "propensity_scores_within_open_unit_interval",
            overlap["min_propensity"] > 0 and overlap["max_propensity"] < 1,
            "Propensity scores are finite and strictly inside (0, 1).",
            sample={
                "min_propensity": overlap["min_propensity"],
                "max_propensity": overlap["max_propensity"],
            },
        ),
        make_check(
            "propensity_overlap_has_tail_units",
            overlap["outside_warning_bounds_n"] == 0,
            "No units fall outside configured overlap warning bounds.",
            severity="warning",
            sample=overlap["outside_warning_bounds"] or None,
        ),
        make_check(
            "propensity_overlap_has_no_severe_tail_units",
            overlap["outside_severe_bounds_n"] == 0,
            "No units fall outside configured severe overlap bounds.",
            severity="warning",
            sample=overlap["outside_severe_bounds"] or None,
        ),
        make_check(
            "stabilized_weights_within_configured_limit",
            weights["max_stabilized_weight"] <= diagnostics["max_stabilized_weight_warning"],
            "Stabilized ATE weights stay under the configured warning threshold.",
            severity="warning",
            sample={
                "max_stabilized_weight": weights["max_stabilized_weight"],
                "threshold": diagnostics["max_stabilized_weight_warning"],
            },
        ),
        make_check(
            "unstabilized_weights_within_configured_limit",
            weights["max_unstabilized_weight"] <= diagnostics["max_unstabilized_weight_warning"],
            "Unstabilized ATE weights stay under the configured warning threshold.",
            severity="warning",
            sample={
                "max_unstabilized_weight": weights["max_unstabilized_weight"],
                "threshold": diagnostics["max_unstabilized_weight_warning"],
            },
        ),
        make_check(
            "effective_sample_size_above_minimum",
            weights["stabilized_effective_sample_size"] >= diagnostics["min_effective_sample_size"],
            "Stabilized weights keep enough effective sample size for the tiny teaching cohort.",
            severity="warning",
            sample={
                "effective_sample_size": weights["stabilized_effective_sample_size"],
                "minimum": diagnostics["min_effective_sample_size"],
            },
        ),
        make_check(
            "trimming_sensitivity_keeps_both_arms",
            all(row["estimable"] for row in model_result["trimming_sensitivity"]),
            "Every configured trimming threshold retains at least one treated and one "
            "comparator unit.",
            severity="warning",
            sample=[row for row in model_result["trimming_sensitivity"] if not row["estimable"]]
            or None,
        ),
        make_check(
            "trimming_changes_target_population_materially",
            not material_trim_rows,
            "Configured trimming thresholds do not remove a material fraction of the "
            "target population.",
            severity="warning",
            sample=material_trim_rows or None,
        ),
        make_check(
            "manual_outcome_ols_matches_statsmodels",
            model_result["outcome_model"]["manual_statsmodels_max_param_diff"] < 1e-10
            and model_result["outcome_model"]["manual_statsmodels_max_prediction_diff"] < 1e-10,
            "Manual matrix OLS and statsmodels.OLS agree for the outcome regression used by AIPW.",
            sample={
                "max_param_diff": model_result["outcome_model"][
                    "manual_statsmodels_max_param_diff"
                ],
                "max_prediction_diff": model_result["outcome_model"][
                    "manual_statsmodels_max_prediction_diff"
                ],
            },
        ),
        make_check(
            "outcome_lpm_predictions_inside_probability_bounds",
            not prediction_outside_bounds,
            "Linear probability outcome predictions stay inside probability bounds.",
            severity="warning",
            sample=prediction_outside_bounds or None,
        ),
    ]


def estimate_ipw_aipw(
    data_dir: str | Path,
    target_trial: dict[str, Any],
    estimand: dict[str, Any],
    adjustment_gate: dict[str, Any],
    estimator_spec: dict[str, Any],
) -> dict[str, Any]:
    tables = load_source_tables(data_dir)
    checks = validate_table_grains(tables)
    if any(check["severity"] == "error" and not check["valid"] for check in checks):
        return invalid_report(checks)

    cohort, cohort_checks = build_analysis_cohort(tables, target_trial)
    checks.extend(cohort_checks)
    if any(check["severity"] == "error" and not check["valid"] for check in checks):
        return invalid_report(checks)

    spec_checks, policy_context = validate_estimator_spec(
        estimator_spec,
        target_trial,
        estimand,
        adjustment_gate,
    )
    checks.extend(spec_checks)
    if any(check["severity"] == "error" and not check["valid"] for check in checks):
        return invalid_report(checks)

    primary = estimate_with_model_pair(
        cohort,
        propensity_model=estimator_spec["propensity_model"],
        outcome_model=estimator_spec["outcome_model"],
        diagnostics=estimator_spec["diagnostics"],
        include_rows=True,
    )
    checks.extend(diagnostic_checks(primary, estimator_spec["diagnostics"]))

    stress_tests = []
    for stress_spec in estimator_spec.get("stress_tests", []):
        propensity_model = (
            estimator_spec["propensity_model"]
            if stress_spec["propensity_model"] == "primary"
            else stress_spec["propensity_model"]
        )
        outcome_model = (
            estimator_spec["outcome_model"]
            if stress_spec["outcome_model"] == "primary"
            else stress_spec["outcome_model"]
        )
        stress_result = estimate_with_model_pair(
            cohort,
            propensity_model=propensity_model,
            outcome_model=outcome_model,
            diagnostics=estimator_spec["diagnostics"],
            include_rows=False,
        )
        stress_tests.append(
            {
                "stress_test_id": stress_spec["stress_test_id"],
                "label": stress_spec["label"],
                "interpretation": stress_spec["interpretation"],
                "propensity_model_id": stress_result["propensity_model"]["model_id"],
                "outcome_model_id": stress_result["outcome_model"]["model_id"],
                "estimates": stress_result["estimates"],
                "overlap": stress_result["overlap"],
                "weights": stress_result["weights"],
            }
        )

    blocking = [
        check["id"] for check in checks if check["severity"] == "error" and not check["valid"]
    ]
    warnings = [
        check["id"] for check in checks if check["severity"] == "warning" and not check["valid"]
    ]
    estimates = primary["estimates"]

    return {
        "valid": not blocking,
        "summary": {
            "spec_id": estimator_spec["ipw_aipw_spec_id"],
            "primary_estimator_id": estimator_spec["primary_estimator_id"],
            "cohort_n": int(len(cohort)),
            "treated_n": int(cohort["treatment"].sum()),
            "comparator_n": int((1 - cohort["treatment"]).sum()),
            "treated_risk": float(cohort.loc[cohort["treatment"] == 1, "outcome"].mean()),
            "comparator_risk": float(cohort.loc[cohort["treatment"] == 0, "outcome"].mean()),
            "naive_risk_difference": estimates["naive_risk_difference"],
            "ipw_hajek_ate": estimates["ipw_hajek_ate"],
            "ipw_ht_ate": estimates["ipw_ht_ate"],
            "aipw_ate": estimates["aipw_ate"],
            "outcome_regression_ate": estimates["outcome_regression_ate"],
            "min_propensity": primary["overlap"]["min_propensity"],
            "max_propensity": primary["overlap"]["max_propensity"],
            "max_stabilized_weight": primary["weights"]["max_stabilized_weight"],
            "max_unstabilized_weight": primary["weights"]["max_unstabilized_weight"],
            "stabilized_effective_sample_size": primary["weights"][
                "stabilized_effective_sample_size"
            ],
            "allowed_effect_claim": estimator_spec["claim_policy"]["allowed_effect_claim"],
            "blocking_checks": blocking,
            "warning_checks": warnings,
        },
        "primary_estimator": primary,
        "stress_tests": stress_tests,
        "policy_context": policy_context,
        "claim_policy": estimator_spec["claim_policy"],
        "checks": checks,
    }


def default_paths() -> dict[str, Path]:
    lesson_root = Path(__file__).resolve().parents[1]
    phase_root = lesson_root.parent
    return {
        "data_dir": phase_root / "data" / "tiny",
        "target_trial": phase_root
        / "01-causal-question-and-estimand"
        / "outputs"
        / "target_trial_spec.json",
        "estimand": phase_root / "01-causal-question-and-estimand" / "outputs" / "estimand.json",
        "adjustment_gate": phase_root
        / "04-colliders"
        / "outputs"
        / "bad_control_selection_audit.json",
        "spec": lesson_root / "outputs" / "ipw_aipw_spec.json",
        "output": lesson_root / "outputs" / "ipw_aipw_report.json",
    }


def build_arg_parser() -> argparse.ArgumentParser:
    paths = default_paths()
    parser = argparse.ArgumentParser(
        description="Estimate stabilized IPW and AIPW with overlap, weight and ESS diagnostics.",
    )
    parser.add_argument("--data-dir", type=Path, default=paths["data_dir"])
    parser.add_argument("--target-trial", type=Path, default=paths["target_trial"])
    parser.add_argument("--estimand", type=Path, default=paths["estimand"])
    parser.add_argument("--adjustment-gate", type=Path, default=paths["adjustment_gate"])
    parser.add_argument("--spec", type=Path, default=paths["spec"])
    parser.add_argument("--output", type=Path, default=paths["output"])
    parser.add_argument(
        "--fail-on-invalid",
        action="store_true",
        help="Exit with code 1 when blocking checks fail.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    report = estimate_ipw_aipw(
        args.data_dir,
        read_json(args.target_trial),
        read_json(args.estimand),
        read_json(args.adjustment_gate),
        read_json(args.spec),
    )
    write_json(args.output, report)
    print(json.dumps(to_jsonable(report["summary"]), ensure_ascii=False, indent=2))
    if args.fail_on_invalid and not report["valid"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
