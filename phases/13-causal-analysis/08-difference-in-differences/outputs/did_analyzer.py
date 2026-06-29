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
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
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
        "region_week_panel": pd.read_csv(root / "region_week_panel.csv"),
        "rollout_calendar": pd.read_csv(root / "rollout_calendar.csv"),
        "causal_scenarios": pd.read_csv(root / "causal_scenarios.csv"),
    }


def validate_source_grain(tables: dict[str, pd.DataFrame]) -> list[dict[str, Any]]:
    key_specs = {
        "region_week_panel": ["region_id", "week_start"],
        "rollout_calendar": ["region_id"],
        "causal_scenarios": ["scenario_id"],
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
            "Region-week panel, rollout calendar and scenario registry preserve declared grain.",
            sample=errors or None,
        )
    ]


def build_panel(tables: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    panel = tables["region_week_panel"].copy()
    calendar = tables["rollout_calendar"].copy()
    panel["week_start"] = pd.to_datetime(panel["week_start"])
    panel["rollout_active"] = as_bool(panel["rollout_active"])
    calendar["rollout_start"] = pd.to_datetime(calendar["rollout_start"])
    calendar["rollout_end"] = pd.to_datetime(calendar["rollout_end"])

    merged = panel.merge(calendar, on="region_id", how="left", validate="many_to_one")
    calendar_errors = merged[merged["rollout_start"].isna()][["region_id"]].drop_duplicates()
    merged["expected_rollout_active"] = (merged["week_start"] >= merged["rollout_start"]) & (
        merged["week_start"] <= merged["rollout_end"]
    )
    active_mismatch = merged[merged["rollout_active"] != merged["expected_rollout_active"]][
        ["region_id", "week_start", "rollout_active", "expected_rollout_active"]
    ].to_dict("records")
    merged["event_time_weeks"] = (
        (merged["week_start"] - merged["rollout_start"]).dt.days // 7
    ).astype(int)
    merged["rollout_active_int"] = merged["rollout_active"].astype(int)
    merged = merged.sort_values(["region_id", "week_start"]).reset_index(drop=True)
    checks = [
        make_check(
            "rollout_calendar_covers_all_panel_regions",
            calendar_errors.empty,
            "Every panel region has a rollout calendar row.",
            sample=calendar_errors.to_dict("records") or None,
        ),
        make_check(
            "rollout_active_matches_calendar",
            not active_mismatch,
            "Observed rollout_active matches rollout_start and rollout_end calendar.",
            sample=active_mismatch or None,
        ),
    ]
    return merged, checks


def parse_window(window: dict[str, str]) -> tuple[pd.Timestamp, pd.Timestamp]:
    return pd.Timestamp(window["start"]), pd.Timestamp(window["end"])


def window_mask(frame: pd.DataFrame, window: dict[str, str]) -> pd.Series:
    start, end = parse_window(window)
    return (frame["week_start"] >= start) & (frame["week_start"] <= end)


def did_cells(
    panel: pd.DataFrame,
    *,
    treated_region: str,
    control_region: str,
    pre_window: dict[str, str],
    post_window: dict[str, str],
    outcome: str,
) -> dict[str, Any]:
    rows = []
    means = {}
    counts = {}
    for group, region in [("treated", treated_region), ("control", control_region)]:
        for period, mask in [
            ("pre", window_mask(panel, pre_window)),
            ("post", window_mask(panel, post_window)),
        ]:
            subset = panel[(panel["region_id"] == region) & mask].copy()
            key = (group, period)
            means[key] = float(subset[outcome].mean()) if len(subset) else np.nan
            counts[key] = int(len(subset))
            rows.append(
                {
                    "group": group,
                    "region_id": region,
                    "period": period,
                    "n_region_weeks": int(len(subset)),
                    "mean": means[key],
                    "week_starts": subset["week_start"].dt.date.astype(str).tolist(),
                    "rollout_active_values": sorted(subset["rollout_active"].unique().tolist()),
                }
            )
    treated_change = means[("treated", "post")] - means[("treated", "pre")]
    control_change = means[("control", "post")] - means[("control", "pre")]
    return {
        "cell_table": rows,
        "treated_pre_mean": means[("treated", "pre")],
        "treated_post_mean": means[("treated", "post")],
        "control_pre_mean": means[("control", "pre")],
        "control_post_mean": means[("control", "post")],
        "treated_change": treated_change,
        "control_change": control_change,
        "did_estimate": treated_change - control_change,
        "counts": {f"{group}_{period}": count for (group, period), count in counts.items()},
    }


def saturated_2x2_regression(
    panel: pd.DataFrame,
    *,
    treated_region: str,
    control_region: str,
    pre_window: dict[str, str],
    post_window: dict[str, str],
    outcome: str,
) -> dict[str, Any]:
    pre = window_mask(panel, pre_window)
    post = window_mask(panel, post_window)
    frame = panel[panel["region_id"].isin([treated_region, control_region]) & (pre | post)].copy()
    frame["treated_group"] = (frame["region_id"] == treated_region).astype(float)
    frame["post_period"] = post.loc[frame.index].astype(float)
    frame["interaction"] = frame["treated_group"] * frame["post_period"]
    design = np.column_stack(
        [
            np.ones(len(frame)),
            frame["treated_group"].to_numpy(),
            frame["post_period"].to_numpy(),
            frame["interaction"].to_numpy(),
        ]
    )
    params = np.linalg.lstsq(design, frame[outcome].to_numpy(dtype=float), rcond=None)[0]
    terms = ["intercept", "treated_group", "post_period", "interaction"]
    return {
        "terms": terms,
        "params": dict(zip(terms, params, strict=True)),
        "interaction_estimate": float(params[3]),
        "n": int(len(frame)),
    }


def manual_slope(x: np.ndarray, y: np.ndarray) -> float:
    centered_x = x - x.mean()
    centered_y = y - y.mean()
    denominator = float(np.square(centered_x).sum())
    if denominator == 0:
        return np.nan
    return float((centered_x * centered_y).sum() / denominator)


def pretrend_diagnostics(panel: pd.DataFrame, spec: dict[str, Any]) -> dict[str, Any]:
    check_spec = spec["pretrend_check"]
    subset = panel[window_mask(panel, check_spec["window"])].copy()
    first_week = subset["week_start"].min()
    subset["week_index"] = ((subset["week_start"] - first_week).dt.days // 7).astype(float)
    rows = []
    for region_id, group in subset.groupby("region_id", sort=True):
        slope = manual_slope(
            group["week_index"].to_numpy(dtype=float),
            group[spec["outcome"]].to_numpy(dtype=float),
        )
        rows.append(
            {
                "region_id": region_id,
                "n_pre_periods": int(len(group)),
                "slope_per_week": slope,
                "first_week": group["week_start"].min().date().isoformat(),
                "last_week": group["week_start"].max().date().isoformat(),
            }
        )
    slope_values = [row["slope_per_week"] for row in rows]
    slope_difference = float(max(slope_values) - min(slope_values)) if slope_values else np.nan
    minimum_periods = min((row["n_pre_periods"] for row in rows), default=0)
    return {
        "method": check_spec["method"],
        "rows": rows,
        "slope_difference": slope_difference,
        "max_abs_slope_difference": check_spec["max_abs_slope_difference"],
        "minimum_pre_periods_per_region": check_spec["minimum_pre_periods_per_region"],
        "passes": bool(
            minimum_periods >= check_spec["minimum_pre_periods_per_region"]
            and abs(slope_difference) <= check_spec["max_abs_slope_difference"]
        ),
    }


def placebo_diagnostics(panel: pd.DataFrame, spec: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for placebo in spec["placebo_checks"]:
        estimate = did_cells(
            panel,
            treated_region=placebo["treated_region"],
            control_region=placebo["control_region"],
            pre_window=placebo["pre_window"],
            post_window=placebo["post_window"],
            outcome=placebo["outcome"],
        )
        rows.append(
            {
                "check_id": placebo["check_id"],
                "label": placebo["label"],
                "outcome": placebo["outcome"],
                "did_estimate": estimate["did_estimate"],
                "max_abs_placebo_effect": placebo["max_abs_placebo_effect"],
                "passes": abs(estimate["did_estimate"]) <= placebo["max_abs_placebo_effect"],
                "cell_table": estimate["cell_table"],
            }
        )
    return rows


def event_study_table(panel: pd.DataFrame, spec: dict[str, Any]) -> dict[str, Any]:
    event_spec = spec["event_study"]
    subset = panel[
        (panel["event_time_weeks"] >= event_spec["event_time_min"])
        & (panel["event_time_weeks"] <= event_spec["event_time_max"])
    ].copy()
    rows = []
    for event_time, group in subset.groupby("event_time_weeks", sort=True):
        rows.append(
            {
                "event_time_weeks": int(event_time),
                "n_regions": int(group["region_id"].nunique()),
                "regions": sorted(group["region_id"].unique().tolist()),
                "mean_outcome": float(group[spec["outcome"]].mean()),
                "treated_share": float(group["rollout_active_int"].mean()),
                "week_starts": group["week_start"].dt.date.astype(str).tolist(),
            }
        )
    reference = next(
        (row for row in rows if row["event_time_weeks"] == event_spec["reference_event_time"]),
        None,
    )
    reference_mean = reference["mean_outcome"] if reference else np.nan
    for row in rows:
        row["relative_to_reference"] = row["mean_outcome"] - reference_mean
        row["sparse_tail"] = row["n_regions"] < event_spec["min_regions_per_event_time"]
    sparse_rows = [row for row in rows if row["sparse_tail"]]
    return {
        "reference_event_time": event_spec["reference_event_time"],
        "reference_mean": reference_mean,
        "preferred_balanced_window": event_spec["preferred_balanced_window"],
        "rows": rows,
        "sparse_event_times": [row["event_time_weeks"] for row in sparse_rows],
    }


def twfe_diagnostic(panel: pd.DataFrame, spec: dict[str, Any]) -> dict[str, Any]:
    outcome = panel[spec["outcome"]].to_numpy(dtype=float)
    region_dummies = pd.get_dummies(panel["region_id"], drop_first=True, dtype=float)
    week_dummies = pd.get_dummies(panel["week_start"].astype(str), drop_first=True, dtype=float)
    design = pd.concat(
        [
            pd.Series(1.0, index=panel.index, name="intercept"),
            panel["rollout_active_int"].astype(float).rename("rollout_active"),
            region_dummies,
            week_dummies,
        ],
        axis=1,
    )
    manual_params = np.linalg.lstsq(design.to_numpy(dtype=float), outcome, rcond=None)[0]
    statsmodels_fit = sm.OLS(outcome, design.to_numpy(dtype=float)).fit()
    rollout_index = list(design.columns).index("rollout_active")
    return {
        "status": spec["twfe_diagnostic"]["status"],
        "risk": spec["twfe_diagnostic"]["risk"],
        "coefficient": float(manual_params[rollout_index]),
        "statsmodels_coefficient": float(statsmodels_fit.params[rollout_index]),
        "manual_statsmodels_max_param_diff": float(
            np.max(np.abs(manual_params - statsmodels_fit.params))
        ),
        "design_columns": design.columns.tolist(),
        "n_rows": int(len(panel)),
    }


def calculated_candidate_status(panel: pd.DataFrame, candidate: dict[str, Any]) -> str:
    design_id = candidate["design_id"]
    if design_id == "naive_twfe_full_staggered_panel":
        return "diagnostic_only_staggered_risk"
    if design_id == "fake_pre_rollout_placebo":
        return "placebo_check"

    control_region = candidate["control_region"]
    pre_start = pd.Timestamp(candidate["pre_window"][0])
    post_start, post_end = (
        pd.Timestamp(candidate["post_window"][0]),
        pd.Timestamp(candidate["post_window"][1]),
    )
    control_window = panel[
        (panel["region_id"] == control_region)
        & (panel["week_start"] >= pre_start)
        & (panel["week_start"] <= post_end)
    ]
    control_treated_before_or_during_post = control_window[
        (control_window["week_start"] >= pre_start)
        & (control_window["week_start"] <= post_end)
        & control_window["rollout_active"]
    ]
    if not control_treated_before_or_during_post.empty:
        return "invalid_already_treated_control"

    treated_region = candidate["treated_region"]
    post_window = panel[
        (panel["region_id"] == treated_region)
        & (panel["week_start"] >= post_start)
        & (panel["week_start"] <= post_end)
    ]
    if post_window.empty or not post_window["rollout_active"].all():
        return "invalid_treated_region_not_active_in_post"
    return "estimable_with_assumptions"


def validate_spec(
    panel: pd.DataFrame,
    tables: dict[str, pd.DataFrame],
    spec: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    required = [
        "did_spec_id",
        "scenario_id",
        "design",
        "unit",
        "treatment",
        "outcome",
        "primary_2x2",
        "pretrend_check",
        "placebo_checks",
        "event_study",
        "candidate_designs",
        "claim_policy",
    ]
    missing = [field for field in required if field not in spec]
    checks = [
        make_check(
            "did_spec_required_fields",
            not missing,
            "DiD spec contains required fields.",
            sample=missing or None,
        )
    ]

    scenario_matches = tables["causal_scenarios"][
        tables["causal_scenarios"]["scenario_id"] == spec.get("scenario_id")
    ]
    scenario_errors = []
    if scenario_matches.empty:
        scenario_errors.append({"scenario_id": spec.get("scenario_id"), "reason": "missing"})
    else:
        scenario = scenario_matches.iloc[0].to_dict()
        for field in ["design", "unit", "outcome"]:
            if str(scenario.get(field)) != str(spec.get(field)):
                scenario_errors.append(
                    {"field": field, "expected": scenario.get(field), "actual": spec.get(field)}
                )
    checks.append(
        make_check(
            "did_spec_matches_scenario_registry",
            not scenario_errors,
            "DiD spec aligns with causal_scenarios.csv registry.",
            sample=scenario_errors or None,
        )
    )

    primary = spec["primary_2x2"]
    primary_pre_count = int(window_mask(panel, primary["pre_window"]).sum())
    primary_post_count = int(window_mask(panel, primary["post_window"]).sum())
    checks.append(
        make_check(
            "primary_2x2_windows_have_panel_rows",
            primary_pre_count > 0 and primary_post_count > 0,
            "Primary 2x2 pre and post windows have panel rows.",
            sample={"pre_rows": primary_pre_count, "post_rows": primary_post_count},
        )
    )

    control_post = panel[
        (panel["region_id"] == primary["control_region"])
        & window_mask(panel, primary["post_window"])
    ]
    treated_post = panel[
        (panel["region_id"] == primary["treated_region"])
        & window_mask(panel, primary["post_window"])
    ]
    control_errors = control_post[control_post["rollout_active"]][
        ["region_id", "week_start", "rollout_active"]
    ].to_dict("records")
    treated_errors = treated_post[~treated_post["rollout_active"]][
        ["region_id", "week_start", "rollout_active"]
    ].to_dict("records")
    checks.append(
        make_check(
            "primary_control_is_not_yet_treated_in_post_window",
            not control_errors and not treated_errors,
            "Primary contrast uses an active treated region and a not-yet-treated control region.",
            sample={"control_errors": control_errors, "treated_errors": treated_errors}
            if control_errors or treated_errors
            else None,
        )
    )

    candidate_audits = []
    status_errors = []
    for candidate in spec["candidate_designs"]:
        calculated = calculated_candidate_status(panel, candidate)
        audit = {
            "design_id": candidate["design_id"],
            "declared_status": candidate["declared_status"],
            "calculated_status": calculated,
        }
        candidate_audits.append(audit)
        if calculated != candidate["declared_status"]:
            status_errors.append(audit)
    checks.append(
        make_check(
            "candidate_design_statuses_match_policy",
            not status_errors,
            "Candidate DiD design statuses match not-yet-treated and staggered-adoption policy.",
            sample=status_errors or None,
        )
    )
    return checks, {"candidate_design_audits": candidate_audits}


def estimate_did(data_dir: str | Path, did_spec: dict[str, Any]) -> dict[str, Any]:
    tables = load_source_tables(data_dir)
    checks = validate_source_grain(tables)
    if any(check["severity"] == "error" and not check["valid"] for check in checks):
        return invalid_report(checks)

    panel, panel_checks = build_panel(tables)
    checks.extend(panel_checks)
    if any(check["severity"] == "error" and not check["valid"] for check in checks):
        return invalid_report(checks)

    spec_checks, policy_context = validate_spec(panel, tables, did_spec)
    checks.extend(spec_checks)
    if any(check["severity"] == "error" and not check["valid"] for check in checks):
        return invalid_report(checks)

    primary = did_spec["primary_2x2"]
    primary_estimate = did_cells(
        panel,
        treated_region=primary["treated_region"],
        control_region=primary["control_region"],
        pre_window=primary["pre_window"],
        post_window=primary["post_window"],
        outcome=did_spec["outcome"],
    )
    regression_2x2 = saturated_2x2_regression(
        panel,
        treated_region=primary["treated_region"],
        control_region=primary["control_region"],
        pre_window=primary["pre_window"],
        post_window=primary["post_window"],
        outcome=did_spec["outcome"],
    )
    pretrend = pretrend_diagnostics(panel, did_spec)
    placebo = placebo_diagnostics(panel, did_spec)
    event_study = event_study_table(panel, did_spec)
    twfe = twfe_diagnostic(panel, did_spec)

    checks.append(
        make_check(
            "manual_2x2_did_matches_saturated_regression",
            abs(primary_estimate["did_estimate"] - regression_2x2["interaction_estimate"]) < 1e-12,
            "Manual four-cell DiD equals the interaction coefficient in a saturated "
            "2x2 regression.",
            sample={
                "manual_did": primary_estimate["did_estimate"],
                "regression_interaction": regression_2x2["interaction_estimate"],
            },
        )
    )
    checks.append(
        make_check(
            "parallel_pretrend_slope_check_passes",
            pretrend["passes"],
            "Pre-period activation-rate slopes are parallel within configured tolerance.",
            sample=pretrend,
        )
    )
    for placebo_row in placebo:
        checks.append(
            make_check(
                f"placebo_{placebo_row['check_id']}_within_threshold",
                placebo_row["passes"],
                f"Placebo check {placebo_row['check_id']} stays within configured threshold.",
                sample=placebo_row,
            )
        )
    checks.append(
        make_check(
            "event_study_has_reference_period",
            not pd.isna(event_study["reference_mean"]),
            "Event-study table contains the configured reference event time.",
            sample={
                "reference_event_time": event_study["reference_event_time"],
                "reference_mean": event_study["reference_mean"],
            },
        )
    )
    checks.append(
        make_check(
            "event_study_sparse_tails_are_visible",
            not event_study["sparse_event_times"],
            "Event-study table has at least the configured number of regions at every event time.",
            severity="warning",
            sample=event_study["sparse_event_times"] or None,
        )
    )
    checks.append(
        make_check(
            "twfe_is_diagnostic_only_for_staggered_adoption",
            False,
            "Full-panel TWFE is reported for reconciliation but not used as the primary design.",
            severity="warning",
            sample={"status": twfe["status"], "risk": twfe["risk"]},
        )
    )
    checks.append(
        make_check(
            "manual_twfe_matches_statsmodels_ols",
            twfe["manual_statsmodels_max_param_diff"] < 1e-10,
            "Manual dummy-matrix TWFE coefficient matches statsmodels.OLS.",
            sample={"max_param_diff": twfe["manual_statsmodels_max_param_diff"]},
        )
    )

    assumption_failures = [
        check["id"]
        for check in checks
        if check["severity"] == "error"
        and not check["valid"]
        and check["id"]
        in {
            "primary_control_is_not_yet_treated_in_post_window",
            "parallel_pretrend_slope_check_passes",
            "placebo_fake_rollout_in_pre_period_within_threshold",
            "placebo_mean_friction_score_should_not_jump_within_threshold",
        }
    ]
    claim_policy = did_spec["claim_policy"]
    checks.append(
        make_check(
            "claim_policy_requires_passing_design_assumptions",
            not (claim_policy.get("allowed_effect_claim") and assumption_failures),
            "Limited causal wording is allowed only when primary DiD design checks pass.",
            sample=assumption_failures or None,
        )
    )

    blocking = [
        check["id"] for check in checks if check["severity"] == "error" and not check["valid"]
    ]
    warnings = [
        check["id"] for check in checks if check["severity"] == "warning" and not check["valid"]
    ]
    return {
        "valid": not blocking,
        "summary": {
            "spec_id": did_spec["did_spec_id"],
            "scenario_id": did_spec["scenario_id"],
            "cohort_unit": did_spec["unit"],
            "regions_n": int(panel["region_id"].nunique()),
            "weeks_n": int(panel["week_start"].nunique()),
            "panel_rows_n": int(len(panel)),
            "treated_region": primary["treated_region"],
            "control_region": primary["control_region"],
            "treated_pre_mean": primary_estimate["treated_pre_mean"],
            "treated_post_mean": primary_estimate["treated_post_mean"],
            "treated_change": primary_estimate["treated_change"],
            "control_pre_mean": primary_estimate["control_pre_mean"],
            "control_post_mean": primary_estimate["control_post_mean"],
            "control_change": primary_estimate["control_change"],
            "did_estimate": primary_estimate["did_estimate"],
            "twfe_coefficient": twfe["coefficient"],
            "fake_pre_placebo_did": next(
                row["did_estimate"]
                for row in placebo
                if row["check_id"] == "fake_rollout_in_pre_period"
            ),
            "pretrend_slope_difference": pretrend["slope_difference"],
            "sparse_event_times": event_study["sparse_event_times"],
            "allowed_effect_claim": claim_policy["allowed_effect_claim"],
            "blocking_checks": blocking,
            "warning_checks": warnings,
        },
        "primary_2x2": {
            "design": primary,
            "manual_estimate": primary_estimate,
            "saturated_regression": regression_2x2,
        },
        "pretrend_check": pretrend,
        "placebo_checks": placebo,
        "event_study": event_study,
        "twfe_diagnostic": twfe,
        "policy_context": policy_context,
        "claim_policy": claim_policy,
        "checks": checks,
    }


def default_paths() -> dict[str, Path]:
    lesson_root = Path(__file__).resolve().parents[1]
    phase_root = lesson_root.parent
    return {
        "data_dir": phase_root / "data" / "tiny",
        "spec": lesson_root / "outputs" / "did_spec.json",
        "output": lesson_root / "outputs" / "did_report.json",
    }


def build_arg_parser() -> argparse.ArgumentParser:
    paths = default_paths()
    parser = argparse.ArgumentParser(
        description=(
            "Analyze a regional Difference-in-Differences design with pre-trend, "
            "placebo and TWFE diagnostics."
        ),
    )
    parser.add_argument("--data-dir", type=Path, default=paths["data_dir"])
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
    report = estimate_did(args.data_dir, read_json(args.spec))
    write_json(args.output, report)
    print(json.dumps(to_jsonable(report["summary"]), ensure_ascii=False, indent=2))
    if args.fail_on_invalid and not report["valid"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
