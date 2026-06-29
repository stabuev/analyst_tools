from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import statsmodels.api as sm


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
            "Source tables preserve user/program grain before joining the analysis cohort.",
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


def model_source_variables(model_spec: dict[str, Any]) -> set[str]:
    estimator = model_spec["estimator"]
    sources = set(estimator.get("direct_numeric_terms", []))
    for feature in estimator.get("derived_features", []):
        sources.update(feature.get("source_variables", []))
    return sources


def variant_status(
    variant: dict[str, Any],
    *,
    required_sources: set[str],
    bad_controls: set[str],
) -> str:
    sources = set(variant.get("source_variables", []))
    filters = set(variant.get("filter_variables", []))
    if (sources | filters) & bad_controls:
        return "invalid_bad_control"
    if not required_sources.issubset(sources):
        return "invalid_omits_required_adjustment_sources"
    return "estimable_with_warnings"


def validate_model_spec(
    model_spec: dict[str, Any],
    target_trial: dict[str, Any],
    estimand: dict[str, Any],
    adjustment_gate: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    required = [
        "g_formula_spec_id",
        "question_id",
        "estimand_id",
        "trial_id",
        "adjustment_gate_id",
        "adjustment_action_id",
        "treatment",
        "outcome",
        "estimator",
        "candidate_model_variants",
        "claim_policy",
    ]
    missing = [field for field in required if field not in model_spec]
    checks = [
        make_check(
            "g_formula_spec_required_fields",
            not missing,
            "G-formula spec contains required fields.",
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
        if model_spec.get(field) != expected_value:
            alignment_errors.append(
                {"field": field, "expected": expected_value, "actual": model_spec.get(field)}
            )
    checks.append(
        make_check(
            "g_formula_spec_aligns_with_question_and_estimand",
            not alignment_errors,
            "Estimator spec aligns with target trial and estimand.",
            sample=alignment_errors or None,
        )
    )

    action_id = model_spec.get("adjustment_action_id")
    gate_action = allowed_action_from_gate(adjustment_gate, action_id)
    gate_errors = []
    if not adjustment_gate.get("valid"):
        gate_errors.append({"reason": "adjustment gate report is not valid"})
    if gate_action is None:
        gate_errors.append(
            {"reason": "adjustment action is absent from gate", "action_id": action_id}
        )
    elif not gate_action.get("allowed_for_estimation"):
        gate_errors.append({"reason": "adjustment action is not allowed", "action_id": action_id})
    checks.append(
        make_check(
            "adjustment_gate_allows_estimator_handoff",
            not gate_errors,
            "Estimator consumes only the action allowed by 13/04 bad-control gate.",
            sample=gate_errors or None,
        )
    )

    allowed_sources = set(gate_action.get("conditioning_variables", [])) if gate_action else set()
    bad_controls = set(adjustment_gate.get("summary", {}).get("bad_control_variables", []))
    sources = model_source_variables(model_spec)
    source_errors = sorted(sources - allowed_sources)
    missing_sources = sorted(allowed_sources - sources)
    checks.append(
        make_check(
            "model_uses_only_allowed_baseline_sources",
            not source_errors,
            "Outcome model basis is built only from allowed observed baseline controls.",
            sample=source_errors or None,
        )
    )
    checks.append(
        make_check(
            "model_source_basis_covers_allowed_adjustment_sources",
            not missing_sources,
            "Compact model basis accounts for every source variable "
            "allowed by the adjustment gate.",
            sample=missing_sources or None,
        )
    )

    variant_audits = []
    status_errors = []
    for variant in model_spec.get("candidate_model_variants", []):
        calculated = variant_status(
            variant,
            required_sources=allowed_sources,
            bad_controls=bad_controls,
        )
        audit = {
            "model_id": variant.get("model_id"),
            "declared_status": variant.get("declared_status"),
            "calculated_status": calculated,
            "source_variables": variant.get("source_variables", []),
            "filter_variables": variant.get("filter_variables", []),
            "bad_control_variables": sorted(
                (
                    set(variant.get("source_variables", []))
                    | set(variant.get("filter_variables", []))
                )
                & bad_controls
            ),
            "omitted_allowed_sources": sorted(
                allowed_sources - set(variant.get("source_variables", []))
            ),
        }
        variant_audits.append(audit)
        if audit["declared_status"] != calculated:
            status_errors.append(audit)
    checks.append(
        make_check(
            "candidate_model_statuses_match_policy",
            not status_errors,
            "Candidate model statuses match bad-control and adjustment-source policy.",
            sample=status_errors or None,
        )
    )

    claim_errors = []
    primary_unmeasured_paths = (
        gate_action.get("open_unmeasured_backdoor_paths") if gate_action else None
    )
    if primary_unmeasured_paths and model_spec.get("claim_policy", {}).get("allowed_effect_claim"):
        claim_errors.append(
            {
                "field": "allowed_effect_claim",
                "reason": "unmeasured backdoor path remains after observed adjustment",
            }
        )
    checks.append(
        make_check(
            "claim_policy_respects_unmeasured_confounding_limitation",
            not claim_errors,
            "G-computation estimate is not promoted to an unrestricted causal effect claim.",
            sample=claim_errors or None,
        )
    )

    context = {
        "allowed_sources": sorted(allowed_sources),
        "bad_controls": sorted(bad_controls),
        "candidate_model_audits": variant_audits,
        "primary_unmeasured_paths": primary_unmeasured_paths,
    }
    return checks, context


def component_values(cohort: pd.DataFrame, component: dict[str, Any]) -> pd.Series:
    field = component["field"]
    if field not in cohort:
        raise ValueError(f"missing feature source field: {field}")
    if component["type"] == "numeric":
        return pd.to_numeric(cohort[field]) * float(component.get("weight", 1.0))
    if component["type"] == "scaled_numeric":
        values = (pd.to_numeric(cohort[field]) - float(component["center"])) / float(
            component["scale"]
        )
        return values * float(component.get("weight", 1.0))
    if component["type"] == "categorical_map":
        mapped = cohort[field].map(component["values"])
        if mapped.isna().any():
            unknown = sorted(cohort.loc[mapped.isna(), field].astype(str).unique())
            raise ValueError(f"unknown categories for {field}: {unknown}")
        return mapped.astype(float)
    raise ValueError(f"unsupported derived feature component: {component['type']}")


def add_model_features(cohort: pd.DataFrame, model_spec: dict[str, Any]) -> pd.DataFrame:
    frame = cohort.copy()
    for feature in model_spec["estimator"].get("derived_features", []):
        total = pd.Series(0.0, index=frame.index)
        for component in feature.get("components", []):
            total = total + component_values(frame, component)
        frame[feature["name"]] = total.astype(float)
    for term in model_spec["estimator"].get("direct_numeric_terms", []):
        frame[term] = pd.to_numeric(frame[term]).astype(float)
    return frame


def design_matrix(
    frame: pd.DataFrame,
    model_spec: dict[str, Any],
    *,
    treatment_value: int | None = None,
) -> pd.DataFrame:
    estimator = model_spec["estimator"]
    terms = estimator["terms"]
    columns: dict[str, Any] = {}
    if "intercept" in terms:
        columns["intercept"] = np.ones(len(frame), dtype=float)
    treatment = (
        frame["treatment"].astype(float) if treatment_value is None else float(treatment_value)
    )
    if "treatment" in terms:
        columns["treatment"] = treatment
    for feature in estimator.get("derived_features", []):
        name = feature["name"]
        if name in terms:
            columns[name] = frame[name].astype(float)
    for term in estimator.get("direct_numeric_terms", []):
        if term in terms:
            columns[term] = frame[term].astype(float)
    matrix = pd.DataFrame(columns)
    return matrix[terms]


def fit_manual_ols(x: pd.DataFrame, y: pd.Series) -> dict[str, Any]:
    x_values = x.to_numpy(dtype=float)
    y_values = y.to_numpy(dtype=float)
    coefficients, residuals, rank, singular_values = np.linalg.lstsq(x_values, y_values, rcond=None)
    fitted = x_values @ coefficients
    return {
        "coefficients": dict(zip(x.columns, coefficients, strict=True)),
        "fitted": fitted,
        "residuals": y_values - fitted,
        "rank": int(rank),
        "condition_number": float(np.linalg.cond(x_values)),
        "singular_values": singular_values.tolist(),
        "residual_rmse": float(np.sqrt(np.mean((y_values - fitted) ** 2))),
        "residual_sum_squares": float(np.sum((y_values - fitted) ** 2)),
    }


def fit_statsmodels_ols(x: pd.DataFrame, y: pd.Series) -> dict[str, Any]:
    result = sm.OLS(y.astype(float), x.astype(float)).fit(cov_type="HC1")
    return {
        "coefficients": result.params.to_dict(),
        "robust_standard_errors": result.bse.to_dict(),
        "fitted": result.predict(x).to_numpy(),
        "nobs": int(result.nobs),
        "df_resid": float(result.df_resid),
        "rsquared": float(result.rsquared),
    }


def predict_from_coefficients(x: pd.DataFrame, coefficients: dict[str, float]) -> np.ndarray:
    beta = np.array([coefficients[column] for column in x.columns], dtype=float)
    return x.to_numpy(dtype=float) @ beta


def standardized_estimates(
    frame: pd.DataFrame,
    model_spec: dict[str, Any],
    coefficients: dict[str, float],
) -> dict[str, Any]:
    x1 = design_matrix(frame, model_spec, treatment_value=1)
    x0 = design_matrix(frame, model_spec, treatment_value=0)
    y1 = predict_from_coefficients(x1, coefficients)
    y0 = predict_from_coefficients(x0, coefficients)
    delta = y1 - y0
    treated_mask = frame["treatment"].to_numpy(dtype=bool)
    standardized_rows = []
    for index, row in frame.iterrows():
        standardized_rows.append(
            {
                "user_id": row["user_id"],
                "observed_treatment": int(row["treatment"]),
                "observed_outcome": int(row["outcome"]),
                "baseline_risk_score": float(row["baseline_risk_score"]),
                "predicted_y_if_treated": float(y1[index]),
                "predicted_y_if_comparator": float(y0[index]),
                "individual_contrast": float(delta[index]),
            }
        )
    return {
        "potential_outcome_means": {
            "mean_y_if_treated": float(np.mean(y1)),
            "mean_y_if_comparator": float(np.mean(y0)),
        },
        "effects": {
            "ATE": float(np.mean(delta)),
            "ATT": float(np.mean(delta[treated_mask])),
        },
        "standardized_rows": standardized_rows,
        "predicted_y_if_treated": y1,
        "predicted_y_if_comparator": y0,
        "individual_contrast": delta,
    }


def naive_difference(cohort: pd.DataFrame) -> dict[str, Any]:
    treated = cohort[cohort["treatment"] == 1]
    comparator = cohort[cohort["treatment"] == 0]
    treated_risk = float(treated["outcome"].mean())
    comparator_risk = float(comparator["outcome"].mean())
    return {
        "treated_risk": treated_risk,
        "comparator_risk": comparator_risk,
        "risk_difference": treated_risk - comparator_risk,
        "treated_n": int(len(treated)),
        "comparator_n": int(len(comparator)),
    }


def prediction_bounds_check(
    standardized: dict[str, Any],
    bounds: list[float],
) -> dict[str, Any]:
    lower, upper = bounds
    rows = []
    for row in standardized["standardized_rows"]:
        for field in ["predicted_y_if_treated", "predicted_y_if_comparator"]:
            value = row[field]
            if value < lower or value > upper:
                rows.append(
                    {
                        "user_id": row["user_id"],
                        "field": field,
                        "value": value,
                        "bounds": bounds,
                    }
                )
    return make_check(
        "linear_probability_predictions_within_probability_bounds",
        not rows,
        "Linear probability predictions stay inside [0, 1].",
        severity="warning",
        sample=rows[:10] or None,
    )


def overlap_support_check(
    frame: pd.DataFrame,
    model_spec: dict[str, Any],
) -> dict[str, Any]:
    features = model_spec["estimator"].get("diagnostics", {}).get("overlap_features", [])
    rows = []
    for feature in features:
        for treatment_value in [0, 1]:
            observed = frame.loc[frame["treatment"] == treatment_value, feature]
            min_value = float(observed.min())
            max_value = float(observed.max())
            counterfactual_rows = frame[~frame[feature].between(min_value, max_value)]
            for _, row in counterfactual_rows.iterrows():
                rows.append(
                    {
                        "user_id": row["user_id"],
                        "counterfactual_treatment": treatment_value,
                        "feature": feature,
                        "value": float(row[feature]),
                        "observed_support_min": min_value,
                        "observed_support_max": max_value,
                    }
                )
    return make_check(
        "counterfactual_predictions_stay_within_observed_support",
        not rows,
        "Counterfactual predictions are made inside observed treatment-specific support.",
        severity="warning",
        sample=rows[:12] or None,
    )


def model_matrix_check(
    x: pd.DataFrame, rows_per_parameter_threshold: float
) -> list[dict[str, Any]]:
    parameter_count = x.shape[1]
    row_count = x.shape[0]
    rank = int(np.linalg.matrix_rank(x.to_numpy(dtype=float)))
    return [
        make_check(
            "outcome_model_matrix_is_full_rank",
            rank == parameter_count,
            "Outcome model design matrix has full column rank.",
            sample={"rank": rank, "parameter_count": parameter_count}
            if rank != parameter_count
            else None,
        ),
        make_check(
            "outcome_model_has_enough_rows_per_parameter",
            row_count / parameter_count >= rows_per_parameter_threshold,
            "Outcome model has enough rows per fitted parameter for a teaching estimate.",
            severity="warning",
            sample={
                "rows": row_count,
                "parameters": parameter_count,
                "rows_per_parameter": row_count / parameter_count,
                "threshold": rows_per_parameter_threshold,
            }
            if row_count / parameter_count < rows_per_parameter_threshold
            else None,
        ),
    ]


def compare_manual_and_statsmodels(
    manual: dict[str, Any],
    statsmodels_result: dict[str, Any],
    manual_standardized: dict[str, Any],
    statsmodels_standardized: dict[str, Any],
) -> dict[str, Any]:
    coefficient_diffs = {
        term: abs(manual["coefficients"][term] - statsmodels_result["coefficients"][term])
        for term in manual["coefficients"]
    }
    effect_diffs = {
        effect: abs(
            manual_standardized["effects"][effect] - statsmodels_standardized["effects"][effect]
        )
        for effect in manual_standardized["effects"]
    }
    max_diff = max([*coefficient_diffs.values(), *effect_diffs.values()], default=0.0)
    return make_check(
        "manual_ols_matches_statsmodels_ols",
        max_diff < 1e-10,
        "Manual least-squares g-computation matches statsmodels OLS.",
        sample={
            "max_abs_diff": max_diff,
            "coefficient_diffs": coefficient_diffs,
            "effect_diffs": effect_diffs,
        }
        if max_diff >= 1e-10
        else None,
    )


def estimate_g_formula(
    data_dir: str | Path,
    target_trial: dict[str, Any],
    estimand: dict[str, Any],
    adjustment_gate: dict[str, Any],
    model_spec: dict[str, Any],
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    tables = load_source_tables(data_dir)
    checks.extend(validate_table_grains(tables))
    if any(not check["valid"] and check["severity"] == "error" for check in checks):
        blocking = [
            check["id"] for check in checks if not check["valid"] and check["severity"] == "error"
        ]
        return {
            "valid": False,
            "summary": {"blocking_checks": blocking},
            "checks": checks,
        }

    cohort, cohort_checks = build_analysis_cohort(tables, target_trial)
    checks.extend(cohort_checks)
    spec_checks, policy_context = validate_model_spec(
        model_spec,
        target_trial,
        estimand,
        adjustment_gate,
    )
    checks.extend(spec_checks)

    if any(not check["valid"] and check["severity"] == "error" for check in checks):
        blocking = [
            check["id"] for check in checks if not check["valid"] and check["severity"] == "error"
        ]
        return {
            "valid": False,
            "summary": {"blocking_checks": blocking},
            "checks": checks,
        }

    frame = add_model_features(cohort, model_spec)
    x = design_matrix(frame, model_spec)
    y = frame["outcome"].astype(float)
    rows_per_parameter = float(
        model_spec["estimator"]["diagnostics"].get("min_rows_per_parameter", 2.0)
    )
    checks.extend(model_matrix_check(x, rows_per_parameter))

    manual = fit_manual_ols(x, y)
    statsmodels_result = fit_statsmodels_ols(x, y)
    manual_standardized = standardized_estimates(frame, model_spec, manual["coefficients"])
    statsmodels_standardized = standardized_estimates(
        frame,
        model_spec,
        statsmodels_result["coefficients"],
    )

    checks.append(
        compare_manual_and_statsmodels(
            manual,
            statsmodels_result,
            manual_standardized,
            statsmodels_standardized,
        )
    )
    checks.append(
        prediction_bounds_check(
            manual_standardized,
            model_spec["estimator"]["diagnostics"].get("probability_bounds", [0.0, 1.0]),
        )
    )
    checks.append(overlap_support_check(frame, model_spec))

    warning_checks = [
        check["id"] for check in checks if not check["valid"] and check["severity"] == "warning"
    ]
    blocking_checks = [
        check["id"] for check in checks if not check["valid"] and check["severity"] == "error"
    ]
    naive = naive_difference(frame)
    max_manual_statsmodels_diff = max(
        abs(manual_standardized["effects"][effect] - statsmodels_standardized["effects"][effect])
        for effect in manual_standardized["effects"]
    )
    report = {
        "valid": not blocking_checks,
        "summary": {
            "g_formula_spec_id": model_spec.get("g_formula_spec_id"),
            "estimator_id": model_spec["estimator"].get("estimator_id"),
            "cohort_n": int(len(frame)),
            "treated_n": int(frame["treatment"].sum()),
            "comparator_n": int((1 - frame["treatment"]).sum()),
            "naive_risk_difference": naive["risk_difference"],
            "manual_ate": manual_standardized["effects"]["ATE"],
            "manual_att": manual_standardized["effects"]["ATT"],
            "statsmodels_ate": statsmodels_standardized["effects"]["ATE"],
            "statsmodels_att": statsmodels_standardized["effects"]["ATT"],
            "manual_statsmodels_max_effect_diff": max_manual_statsmodels_diff,
            "mean_y_if_treated": manual_standardized["potential_outcome_means"][
                "mean_y_if_treated"
            ],
            "mean_y_if_comparator": manual_standardized["potential_outcome_means"][
                "mean_y_if_comparator"
            ],
            "model_rank": manual["rank"],
            "model_parameter_count": int(x.shape[1]),
            "condition_number": manual["condition_number"],
            "residual_rmse": manual["residual_rmse"],
            "effect_claim_allowed": model_spec.get("claim_policy", {}).get("allowed_effect_claim"),
            "identification_status": model_spec.get("claim_policy", {}).get(
                "identification_status"
            ),
            "warning_checks": warning_checks,
            "blocking_checks": blocking_checks,
        },
        "cohort": {
            "user_ids": frame["user_id"].tolist(),
            "naive": naive,
        },
        "manual_ols": {
            "coefficients": manual["coefficients"],
            "rank": manual["rank"],
            "condition_number": manual["condition_number"],
            "residual_rmse": manual["residual_rmse"],
            "residual_sum_squares": manual["residual_sum_squares"],
        },
        "statsmodels_ols": {
            "coefficients": statsmodels_result["coefficients"],
            "robust_standard_errors": statsmodels_result["robust_standard_errors"],
            "nobs": statsmodels_result["nobs"],
            "df_resid": statsmodels_result["df_resid"],
            "rsquared": statsmodels_result["rsquared"],
        },
        "standardization": {
            "manual": {
                "potential_outcome_means": manual_standardized["potential_outcome_means"],
                "effects": manual_standardized["effects"],
                "standardized_rows": manual_standardized["standardized_rows"],
            },
            "statsmodels": {
                "potential_outcome_means": statsmodels_standardized["potential_outcome_means"],
                "effects": statsmodels_standardized["effects"],
            },
        },
        "policy_context": policy_context,
        "checks": checks,
    }
    return to_jsonable(report)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Estimate standardized potential outcomes with outcome-regression g-computation."
        )
    )
    parser.add_argument("--data-dir", required=True, help="Directory with phase tiny CSV files")
    parser.add_argument("--target-trial", required=True, help="Path to target_trial_spec.json")
    parser.add_argument("--estimand", required=True, help="Path to estimand.json")
    parser.add_argument(
        "--adjustment-gate",
        required=True,
        help="Path to 13/04 bad_control_selection_audit.json",
    )
    parser.add_argument("--model-spec", required=True, help="Path to g_formula_spec.json")
    parser.add_argument("--output", default=None, help="Optional JSON report path")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = estimate_g_formula(
        args.data_dir,
        read_json(args.target_trial),
        read_json(args.estimand),
        read_json(args.adjustment_gate),
        read_json(args.model_spec),
    )
    if args.output:
        write_json(args.output, report)
    print(json.dumps(to_jsonable(report), ensure_ascii=False, indent=2))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
