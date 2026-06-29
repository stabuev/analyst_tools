from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.spatial.distance import cdist


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
            "Source tables preserve user/program grain before joining the matching cohort.",
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
        mapping = component["values"]
        values = frame[field].map(mapping)
        if values.isna().any():
            unknown = sorted(frame.loc[values.isna(), field].astype(str).unique())
            raise ValueError(f"Unknown categories for {field}: {unknown}")
        return values.astype(float)
    raise ValueError(f"Unsupported derived feature component type: {kind}")


def add_derived_features(cohort: pd.DataFrame, matching_spec: dict[str, Any]) -> pd.DataFrame:
    frame = cohort.copy()
    for feature in matching_spec.get("derived_features", []):
        total = pd.Series(0.0, index=frame.index)
        for component in feature.get("components", []):
            total = total + component_values(frame, component)
        frame[feature["name"]] = total.astype(float)
    return frame


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


def matching_source_variables(matching_spec: dict[str, Any]) -> set[str]:
    design = matching_spec["matching_design"]
    sources = set(design.get("source_variables", []))
    sources.update(design.get("distance_features", []))
    for feature in matching_spec.get("derived_features", []):
        sources.update(feature.get("source_variables", []))
    return sources


def validate_matching_spec(
    target_trial: dict[str, Any],
    estimand: dict[str, Any],
    adjustment_gate: dict[str, Any],
    matching_spec: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    action = allowed_action_from_gate(
        adjustment_gate, matching_spec.get("adjustment_action_id", "")
    )
    allowed_sources = set(action.get("variables", [])) if action else set()
    bad_controls = set(adjustment_gate.get("summary", {}).get("bad_control_variables", []))
    design = matching_spec.get("matching_design", {})
    design_sources = matching_source_variables(matching_spec)
    distance_features = set(design.get("distance_features", []))

    alignment_errors = []
    for field, expected in [
        ("trial_id", target_trial.get("trial_id")),
        ("question_id", estimand.get("question_id")),
        ("estimand_id", estimand.get("estimand_id")),
        ("population", target_trial.get("target_population", {}).get("population_id")),
    ]:
        if matching_spec.get(field) != expected:
            alignment_errors.append(
                {"field": field, "expected": expected, "actual": matching_spec.get(field)}
            )

    checks.extend(
        [
            make_check(
                "matching_spec_aligns_with_target_trial_and_estimand",
                not alignment_errors,
                "Matching spec points to the same trial, question, estimand and target population.",
                sample=alignment_errors or None,
            ),
            make_check(
                "adjustment_gate_allows_matching_handoff",
                bool(action and action.get("allowed_for_estimation")),
                "The selected bad-control gate action is allowed for downstream estimators.",
                sample=None
                if action
                else [{"action_id": matching_spec.get("adjustment_action_id")}],
            ),
        ]
    )

    disallowed_sources = sorted(design_sources - allowed_sources - {"activation_14d_pre"})
    bad_source_variables = sorted(
        (design_sources | set(design.get("filter_variables", []))) & bad_controls
    )
    omitted_allowed_sources = sorted(allowed_sources - set(design.get("source_variables", [])))
    checks.extend(
        [
            make_check(
                "matching_uses_only_allowed_baseline_sources",
                not disallowed_sources and not bad_source_variables,
                "Matching features, derived features and filters do not use bad controls.",
                sample={
                    "disallowed_sources": disallowed_sources,
                    "bad_control_variables": bad_source_variables,
                }
                if disallowed_sources or bad_source_variables
                else None,
            ),
            make_check(
                "matching_source_basis_covers_allowed_adjustment_sources",
                not omitted_allowed_sources,
                (
                    "The matching design documents coverage of the allowed "
                    "observed-baseline adjustment sources."
                ),
                sample=omitted_allowed_sources or None,
            ),
            make_check(
                "distance_features_are_declared_sources",
                distance_features.issubset(set(design.get("source_variables", []))),
                "Every distance feature is part of the declared matching source basis.",
                sample=sorted(distance_features - set(design.get("source_variables", []))) or None,
            ),
        ]
    )

    candidate_audits = audit_candidate_designs(
        matching_spec,
        required_sources=allowed_sources,
        bad_controls=bad_controls,
        treated_n=None,
        comparator_n=None,
    )
    mismatches = [
        {
            "design_id": audit["design_id"],
            "declared_status": audit["declared_status"],
            "calculated_status": audit["calculated_status"],
        }
        for audit in candidate_audits
        if audit["declared_status"] != audit["calculated_status"]
    ]
    checks.append(
        make_check(
            "candidate_matching_design_statuses_match_policy",
            not mismatches,
            "Candidate matching designs declare the same status as the policy audit calculates.",
            sample=mismatches or None,
        )
    )

    claim_policy = matching_spec.get("claim_policy", {})
    remaining_unmeasured = (
        adjustment_gate.get("summary", {}).get("primary_open_unmeasured_backdoor_paths", 0) > 0
    )
    claim_errors = []
    if remaining_unmeasured and claim_policy.get("allowed_effect_claim"):
        claim_errors.append(
            {
                "field": "allowed_effect_claim",
                "reason": "remaining unmeasured backdoor path from adjustment gate",
            }
        )
    if claim_policy.get("identification_status") != "not_identified_due_to_unmeasured_confounding":
        claim_errors.append(
            {
                "field": "identification_status",
                "actual": claim_policy.get("identification_status"),
            }
        )
    checks.append(
        make_check(
            "claim_policy_respects_unmeasured_confounding_limitation",
            not claim_errors,
            "Matching report cannot upgrade the evidence beyond the upstream identification gate.",
            sample=claim_errors or None,
        )
    )

    context = {
        "allowed_sources": sorted(allowed_sources),
        "bad_control_variables": sorted(bad_controls),
        "candidate_matching_design_audits": candidate_audits,
        "selected_adjustment_action": action,
    }
    return checks, context


def audit_candidate_designs(
    matching_spec: dict[str, Any],
    *,
    required_sources: set[str],
    bad_controls: set[str],
    treated_n: int | None,
    comparator_n: int | None,
) -> list[dict[str, Any]]:
    audits = []
    max_no_caliper_distance = matching_spec.get("common_support", {}).get(
        "max_allowed_nearest_distance_without_caliper", 1.5
    )
    for candidate in matching_spec.get("candidate_matching_designs", []):
        sources = set(candidate.get("source_variables", []))
        filters = set(candidate.get("filter_variables", []))
        bad_control_variables = sorted((sources | filters) & bad_controls)
        omitted_allowed_sources = sorted(required_sources - sources)
        if bad_control_variables:
            status = "invalid_bad_control"
        elif candidate.get("caliper") is None and not candidate.get(
            "allow_unmatched_treated",
            True,
        ):
            status = "invalid_common_support_policy"
        elif (
            treated_n is not None
            and comparator_n is not None
            and not candidate.get("replacement", True)
            and not candidate.get("allow_unmatched_treated", True)
            and treated_n > comparator_n
        ):
            status = "invalid_insufficient_controls_for_full_att"
        elif candidate.get("caliper") is None and max_no_caliper_distance is not None:
            status = "invalid_common_support_policy"
        else:
            status = "estimable_with_warnings"
        audits.append(
            {
                "design_id": candidate.get("design_id"),
                "declared_status": candidate.get("declared_status"),
                "calculated_status": status,
                "bad_control_variables": bad_control_variables,
                "omitted_allowed_sources": omitted_allowed_sources,
                "caliper": candidate.get("caliper"),
                "replacement": candidate.get("replacement"),
                "allow_unmatched_treated": candidate.get("allow_unmatched_treated"),
            }
        )
    return audits


def standardized_feature_matrix(
    frame: pd.DataFrame, features: list[str]
) -> tuple[pd.DataFrame, dict[str, dict[str, float]], list[dict[str, Any]]]:
    errors = []
    numeric = pd.DataFrame(index=frame.index)
    scalers: dict[str, dict[str, float]] = {}
    for feature in features:
        if feature not in frame:
            errors.append({"feature": feature, "reason": "missing"})
            continue
        values = pd.to_numeric(frame[feature], errors="coerce")
        if values.isna().any():
            errors.append({"feature": feature, "reason": "non_numeric_or_missing"})
            continue
        mean = float(values.mean())
        std = float(values.std(ddof=0))
        if std == 0.0:
            errors.append({"feature": feature, "reason": "zero_variance"})
            continue
        numeric[feature] = (values - mean) / std
        scalers[feature] = {"mean": mean, "std": std}
    return numeric, scalers, errors


def build_distance_matrix(
    cohort: pd.DataFrame, matching_spec: dict[str, Any]
) -> tuple[pd.DataFrame, dict[str, dict[str, float]], dict[str, Any]]:
    features = matching_spec["matching_design"]["distance_features"]
    standardized, scalers, errors = standardized_feature_matrix(cohort, features)
    if errors:
        return pd.DataFrame(), scalers, {"errors": errors, "manual_matches_scipy": False}

    treated = cohort[cohort["treatment"] == 1].sort_values("user_id").copy()
    controls = cohort[cohort["treatment"] == 0].sort_values("user_id").copy()
    treated_matrix = standardized.loc[treated.index, features].to_numpy(dtype=float)
    control_matrix = standardized.loc[controls.index, features].to_numpy(dtype=float)
    manual = np.sqrt(((treated_matrix[:, None, :] - control_matrix[None, :, :]) ** 2).sum(axis=2))
    scipy_distances = cdist(treated_matrix, control_matrix, metric="euclidean")
    rows = []
    for i, (_, treated_row) in enumerate(treated.iterrows()):
        for j, (_, control_row) in enumerate(controls.iterrows()):
            rows.append(
                {
                    "treated_user_id": treated_row["user_id"],
                    "control_user_id": control_row["user_id"],
                    "distance": float(manual[i, j]),
                    "scipy_distance": float(scipy_distances[i, j]),
                }
            )
    diagnostics = {
        "errors": [],
        "manual_matches_scipy": bool(np.allclose(manual, scipy_distances, atol=1e-12)),
        "max_manual_scipy_diff": float(np.max(np.abs(manual - scipy_distances)))
        if manual.size
        else 0.0,
    }
    return pd.DataFrame(rows), scalers, diagnostics


def match_nearest_neighbors(
    cohort: pd.DataFrame,
    distance_matrix: pd.DataFrame,
    matching_spec: dict[str, Any],
) -> dict[str, Any]:
    design = matching_spec["matching_design"]
    caliper = design.get("caliper")
    replacement = bool(design.get("replacement", True))
    allow_unmatched = bool(design.get("allow_unmatched_treated", True))
    used_controls: set[str] = set()
    matched_pairs = []
    unmatched = []
    cohort_by_user = cohort.set_index("user_id", drop=False)

    treated_ids = sorted(cohort.loc[cohort["treatment"] == 1, "user_id"].tolist())
    for treated_id in treated_ids:
        candidates = distance_matrix[distance_matrix["treated_user_id"] == treated_id].copy()
        if not replacement:
            candidates = candidates[~candidates["control_user_id"].isin(used_controls)]
        candidates = candidates.sort_values(["distance", "control_user_id"])
        if candidates.empty:
            unmatched.append({"treated_user_id": treated_id, "reason": "no_available_control"})
            continue
        best = candidates.iloc[0]
        distance = float(best["distance"])
        if caliper is not None and distance > float(caliper):
            unmatched.append(
                {
                    "treated_user_id": treated_id,
                    "nearest_control_user_id": best["control_user_id"],
                    "nearest_distance": distance,
                    "caliper": float(caliper),
                    "reason": "nearest_distance_above_caliper",
                }
            )
            if not allow_unmatched:
                continue
            continue
        control_id = str(best["control_user_id"])
        used_controls.add(control_id)
        treated_row = cohort_by_user.loc[treated_id]
        control_row = cohort_by_user.loc[control_id]
        matched_pairs.append(
            {
                "treated_user_id": treated_id,
                "control_user_id": control_id,
                "distance": distance,
                "treated_outcome": int(treated_row["outcome"]),
                "control_outcome": int(control_row["outcome"]),
                "pair_effect": int(treated_row["outcome"]) - int(control_row["outcome"]),
                "treated_friction_score": float(treated_row["friction_score"]),
                "control_friction_score": float(control_row["friction_score"]),
                "treated_specialist_capacity": float(treated_row["specialist_capacity"]),
                "control_specialist_capacity": float(control_row["specialist_capacity"]),
            }
        )

    reused = (
        pd.Series([pair["control_user_id"] for pair in matched_pairs]).value_counts().to_dict()
        if matched_pairs
        else {}
    )
    reused_controls = {
        control_id: int(count) for control_id, count in reused.items() if int(count) > 1
    }
    pair_effects = [pair["pair_effect"] for pair in matched_pairs]
    treated_outcomes = [pair["treated_outcome"] for pair in matched_pairs]
    control_outcomes = [pair["control_outcome"] for pair in matched_pairs]
    treated_total = len(treated_ids)
    unique_control_ids = sorted({pair["control_user_id"] for pair in matched_pairs})
    matched_user_ids = sorted(
        {pair["treated_user_id"] for pair in matched_pairs} | set(unique_control_ids)
    )
    return {
        "matched_pairs": matched_pairs,
        "unmatched_treated": unmatched,
        "summary": {
            "matched_treated_n": len(matched_pairs),
            "unmatched_treated_n": len(unmatched),
            "matched_treated_fraction": len(matched_pairs) / treated_total
            if treated_total
            else 0.0,
            "unique_controls_used_n": len(unique_control_ids),
            "unique_controls_used": unique_control_ids,
            "reused_controls": reused_controls,
            "matched_unit_ids": matched_user_ids,
            "matched_unique_units_n": len(matched_user_ids),
            "matched_treated_risk": float(np.mean(treated_outcomes)) if treated_outcomes else None,
            "matched_control_risk": float(np.mean(control_outcomes)) if control_outcomes else None,
            "matched_att": float(np.mean(pair_effects)) if pair_effects else None,
            "max_matched_distance": float(max(pair["distance"] for pair in matched_pairs))
            if matched_pairs
            else None,
            "min_unmatched_nearest_distance": float(
                min(item.get("nearest_distance", np.inf) for item in unmatched)
            )
            if unmatched
            else None,
        },
    }


def smd(left: pd.Series, right: pd.Series) -> float:
    x = pd.to_numeric(left, errors="coerce").astype(float).to_numpy()
    y = pd.to_numeric(right, errors="coerce").astype(float).to_numpy()
    if len(x) < 2 or len(y) < 2:
        return 0.0 if np.isclose(np.mean(x), np.mean(y)) else float("inf")
    pooled = np.sqrt((np.var(x, ddof=1) + np.var(y, ddof=1)) / 2)
    if np.isclose(pooled, 0.0):
        return 0.0 if np.isclose(np.mean(x), np.mean(y)) else float("inf")
    return float((np.mean(x) - np.mean(y)) / pooled)


def balance_table(
    cohort: pd.DataFrame,
    matching: dict[str, Any],
    matching_spec: dict[str, Any],
) -> dict[str, Any]:
    treated_full = cohort[cohort["treatment"] == 1]
    control_full = cohort[cohort["treatment"] == 0]
    cohort_by_user = cohort.set_index("user_id", drop=False)
    matched_treated = pd.DataFrame(
        [cohort_by_user.loc[pair["treated_user_id"]] for pair in matching["matched_pairs"]]
    )
    matched_controls = pd.DataFrame(
        [cohort_by_user.loc[pair["control_user_id"]] for pair in matching["matched_pairs"]]
    )
    rows = []
    for feature_spec in matching_spec["balance_diagnostics"]["features"]:
        feature = feature_spec["name"]
        threshold = float(feature_spec["threshold_abs_smd"])
        before = smd(treated_full[feature], control_full[feature])
        after = smd(matched_treated[feature], matched_controls[feature])
        rows.append(
            {
                "feature": feature,
                "type": feature_spec["type"],
                "treated_mean_before": float(pd.to_numeric(treated_full[feature]).mean()),
                "control_mean_before": float(pd.to_numeric(control_full[feature]).mean()),
                "treated_mean_after": float(pd.to_numeric(matched_treated[feature]).mean()),
                "control_mean_after": float(pd.to_numeric(matched_controls[feature]).mean()),
                "smd_before": before,
                "smd_after": after,
                "abs_smd_before": abs(before),
                "abs_smd_after": abs(after),
                "threshold_abs_smd": threshold,
                "status_after": "ok" if abs(after) <= threshold else "imbalanced",
                "worse_after_matching": abs(after) > abs(before) + 1e-12,
            }
        )
    features_above = [row["feature"] for row in rows if row["status_after"] != "ok"]
    features_worse = [row["feature"] for row in rows if row["worse_after_matching"]]
    return {
        "balance_table": rows,
        "love_plot_data": [
            {
                "feature": row["feature"],
                "smd_before": row["smd_before"],
                "smd_after": row["smd_after"],
                "abs_smd_before": row["abs_smd_before"],
                "abs_smd_after": row["abs_smd_after"],
                "status_after": row["status_after"],
            }
            for row in rows
        ],
        "summary": {
            "max_abs_smd_before": max(row["abs_smd_before"] for row in rows),
            "max_abs_smd_after": max(row["abs_smd_after"] for row in rows),
            "features_above_threshold_after": features_above,
            "features_worse_after_matching": features_worse,
        },
    }


def build_matching_checks(
    cohort: pd.DataFrame,
    distance_diagnostics: dict[str, Any],
    matching: dict[str, Any],
    balance: dict[str, Any],
    matching_spec: dict[str, Any],
) -> list[dict[str, Any]]:
    common_support = matching_spec["common_support"]
    summary = matching["summary"]
    matched_fraction = summary["matched_treated_fraction"]
    unmatched = matching["unmatched_treated"]
    reused_controls = summary["reused_controls"]
    unique_control_fraction = (
        summary["unique_controls_used_n"] / summary["matched_treated_n"]
        if summary["matched_treated_n"]
        else 0.0
    )
    checks = [
        make_check(
            "distance_features_are_numeric_and_scaled",
            not distance_diagnostics.get("errors"),
            "Distance features are numeric and have non-zero variance for standardization.",
            sample=distance_diagnostics.get("errors") or None,
        ),
        make_check(
            "manual_distance_matrix_matches_scipy_cdist",
            bool(distance_diagnostics.get("manual_matches_scipy")),
            "Manual standardized Euclidean distances match scipy.spatial.distance.cdist.",
            sample={"max_diff": distance_diagnostics.get("max_manual_scipy_diff")},
        ),
        make_check(
            "matched_treated_fraction_meets_minimum",
            matched_fraction >= float(common_support["minimum_matched_treated_fraction"]),
            "Enough treated users remain in the matched common-support subset.",
            sample={
                "matched_treated_fraction": matched_fraction,
                "minimum": common_support["minimum_matched_treated_fraction"],
            },
        ),
        make_check(
            "treated_units_without_common_support_match",
            len(unmatched) <= 0,
            "Some treated units have no control neighbor within the declared caliper.",
            severity="warning",
            sample=unmatched or None,
        ),
        make_check(
            "matched_controls_are_not_over_reused",
            unique_control_fraction
            >= float(common_support["warn_if_unique_control_fraction_below"]),
            "Control reuse is visible because replacement changes effective control diversity.",
            severity="warning",
            sample={
                "unique_control_fraction": unique_control_fraction,
                "reused_controls": reused_controls,
            }
            if reused_controls
            else None,
        ),
        make_check(
            "post_match_balance_within_threshold",
            not balance["summary"]["features_above_threshold_after"],
            "Post-match standardized mean differences are within declared thresholds.",
            severity="warning",
            sample=balance["summary"]["features_above_threshold_after"] or None,
        ),
        make_check(
            "matching_does_not_worsen_balance",
            not balance["summary"]["features_worse_after_matching"],
            "Matching does not worsen balance on audited pre-treatment features.",
            severity="warning",
            sample=balance["summary"]["features_worse_after_matching"] or None,
        ),
    ]
    if matching_spec["matching_design"].get("caliper") is not None:
        checks.append(
            make_check(
                "matched_pairs_respect_declared_caliper",
                all(
                    pair["distance"] <= float(matching_spec["matching_design"]["caliper"])
                    for pair in matching["matched_pairs"]
                ),
                "Every matched pair is inside the declared caliper.",
            )
        )
    return checks


def refresh_candidate_audits_with_counts(
    policy_context: dict[str, Any],
    matching_spec: dict[str, Any],
    treated_n: int,
    comparator_n: int,
) -> None:
    policy_context["candidate_matching_design_audits"] = audit_candidate_designs(
        matching_spec,
        required_sources=set(policy_context["allowed_sources"]),
        bad_controls=set(policy_context["bad_control_variables"]),
        treated_n=treated_n,
        comparator_n=comparator_n,
    )


def estimate_matching(
    data_dir: str | Path,
    target_trial: dict[str, Any],
    estimand: dict[str, Any],
    adjustment_gate: dict[str, Any],
    matching_spec: dict[str, Any],
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    tables = load_source_tables(data_dir)
    grain_checks = validate_table_grains(tables)
    checks.extend(grain_checks)
    if any(not check["valid"] and check["severity"] == "error" for check in grain_checks):
        return invalid_report(checks)

    cohort, cohort_checks = build_analysis_cohort(tables, target_trial)
    checks.extend(cohort_checks)
    cohort = add_derived_features(cohort, matching_spec)

    spec_checks, policy_context = validate_matching_spec(
        target_trial,
        estimand,
        adjustment_gate,
        matching_spec,
    )
    checks.extend(spec_checks)

    treated_n = int(cohort["treatment"].sum())
    comparator_n = int((1 - cohort["treatment"]).sum())
    refresh_candidate_audits_with_counts(policy_context, matching_spec, treated_n, comparator_n)
    candidate_mismatches = [
        {
            "design_id": audit["design_id"],
            "declared_status": audit["declared_status"],
            "calculated_status": audit["calculated_status"],
        }
        for audit in policy_context["candidate_matching_design_audits"]
        if audit["declared_status"] != audit["calculated_status"]
    ]
    for check in checks:
        if check["id"] == "candidate_matching_design_statuses_match_policy":
            check["valid"] = not candidate_mismatches
            if candidate_mismatches:
                check["sample"] = candidate_mismatches
            else:
                check.pop("sample", None)

    distance_matrix, scalers, distance_diagnostics = build_distance_matrix(cohort, matching_spec)
    if distance_diagnostics.get("errors"):
        checks.append(
            make_check(
                "distance_features_are_numeric_and_scaled",
                False,
                "Distance features are numeric and have non-zero variance for standardization.",
                sample=distance_diagnostics["errors"],
            )
        )
        return invalid_report(checks)

    matching = match_nearest_neighbors(cohort, distance_matrix, matching_spec)
    balance = balance_table(cohort, matching, matching_spec)
    checks.extend(
        build_matching_checks(
            cohort,
            distance_diagnostics,
            matching,
            balance,
            matching_spec,
        )
    )

    naive_treated_risk = float(cohort.loc[cohort["treatment"] == 1, "outcome"].mean())
    naive_control_risk = float(cohort.loc[cohort["treatment"] == 0, "outcome"].mean())
    summary = {
        "cohort_n": int(len(cohort)),
        "treated_n": treated_n,
        "comparator_n": comparator_n,
        "naive_treated_risk": naive_treated_risk,
        "naive_comparator_risk": naive_control_risk,
        "naive_risk_difference": naive_treated_risk - naive_control_risk,
        **matching["summary"],
        "max_abs_smd_before": balance["summary"]["max_abs_smd_before"],
        "max_abs_smd_after": balance["summary"]["max_abs_smd_after"],
        "features_above_threshold_after": balance["summary"]["features_above_threshold_after"],
        "features_worse_after_matching": balance["summary"]["features_worse_after_matching"],
    }
    blocking = [
        check["id"] for check in checks if check["severity"] == "error" and not check["valid"]
    ]
    warnings = [
        check["id"] for check in checks if check["severity"] == "warning" and not check["valid"]
    ]
    summary["blocking_checks"] = blocking
    summary["warning_checks"] = warnings
    report = {
        "valid": not blocking,
        "summary": summary,
        "cohort": {
            "user_ids": cohort["user_id"].tolist(),
            "treated_user_ids": cohort.loc[cohort["treatment"] == 1, "user_id"].tolist(),
            "comparator_user_ids": cohort.loc[cohort["treatment"] == 0, "user_id"].tolist(),
        },
        "distance": {
            "features": matching_spec["matching_design"]["distance_features"],
            "scalers": scalers,
            "matrix": distance_matrix.to_dict("records"),
            "manual_matches_scipy": distance_diagnostics["manual_matches_scipy"],
            "max_manual_scipy_diff": distance_diagnostics["max_manual_scipy_diff"],
        },
        "matching": matching,
        "balance": balance,
        "policy_context": policy_context,
        "claim_policy": matching_spec.get("claim_policy", {}),
        "checks": checks,
    }
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build matching balance and common-support audit.")
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--target-trial", required=True, type=Path)
    parser.add_argument("--estimand", required=True, type=Path)
    parser.add_argument("--adjustment-gate", required=True, type=Path)
    parser.add_argument("--matching-spec", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = estimate_matching(
        args.data_dir,
        read_json(args.target_trial),
        read_json(args.estimand),
        read_json(args.adjustment_gate),
        read_json(args.matching_spec),
    )
    write_json(args.output, report)
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
