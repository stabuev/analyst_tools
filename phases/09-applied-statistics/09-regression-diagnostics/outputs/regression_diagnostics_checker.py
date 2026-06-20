from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import statsmodels.api as sm
from scipy import stats
from statsmodels.stats.diagnostic import het_breuschpagan
from statsmodels.stats.outliers_influence import OLSInfluence, variance_inflation_factor


def passed(check_id: str, severity: str, observed: Any, expected: Any) -> dict[str, Any]:
    return {"id": check_id, "severity": severity, "valid": True, "observed": observed, "expected": expected, "sample": []}


def failed(
    check_id: str,
    severity: str,
    observed: Any,
    expected: Any,
    sample: list[Any] | None = None,
) -> dict[str, Any]:
    return {"id": check_id, "severity": severity, "valid": False, "observed": observed, "expected": expected, "sample": sample or []}


def read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as source:
        value = json.load(source)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def round_float(value: float | None, digits: int = 6) -> float | None:
    if value is None or not math.isfinite(float(value)):
        return None
    return round(float(value), digits)


def spec_checks(spec: dict[str, Any]) -> list[dict[str, Any]]:
    required = {"version", "diagnostic_id", "source_model_report", "checks", "known_limitations"}
    missing = sorted(required - set(spec))
    if missing:
        return [failed("diagnostic_spec_required_fields", "error", sorted(spec), sorted(required), missing)]
    return [passed("diagnostic_spec_required_fields", "error", sorted(required), sorted(required))]


def load_design(model_report: dict[str, Any]) -> tuple[np.ndarray, np.ndarray, list[str], list[dict[str, Any]]]:
    checks: list[dict[str, Any]] = []
    if model_report.get("valid") is not True:
        checks.append(failed("source_model_report_valid", "error", model_report.get("valid"), True))
        return np.empty((0, 0)), np.empty((0,)), [], checks
    checks.append(passed("source_model_report_valid", "error", True, True))
    design = model_report["design_matrix"]
    x = np.asarray(design["rows"], dtype=float)
    y = np.asarray(design["outcome"], dtype=float)
    names = list(design["columns"])
    if x.ndim != 2 or y.ndim != 1 or x.shape[0] != y.shape[0]:
        checks.append(failed("design_matrix_shape_valid", "error", {"x": x.shape, "y": y.shape}, "n rows match"))
    else:
        checks.append(passed("design_matrix_shape_valid", "error", {"x": list(x.shape), "y": list(y.shape)}, "n rows match"))
    return x, y, names, checks


def corr_or_none(x: np.ndarray, y: np.ndarray) -> float | None:
    if len(x) < 3 or len(set(x.tolist())) < 2 or len(set(y.tolist())) < 2:
        return None
    return float(stats.pearsonr(x, y).statistic)


def build_figure(path: Path, fitted: np.ndarray, residuals: np.ndarray, leverage: np.ndarray, cooks: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, 2, figsize=(8, 3.2), constrained_layout=True)
    axes[0].axhline(0, color="#555555", linewidth=1)
    axes[0].scatter(fitted, residuals, color="#2563eb")
    axes[0].set_xlabel("Fitted")
    axes[0].set_ylabel("Residual")
    axes[0].set_title("Residuals vs fitted")
    axes[1].scatter(leverage, cooks, color="#dc2626")
    axes[1].set_xlabel("Leverage")
    axes[1].set_ylabel("Cook distance")
    axes[1].set_title("Influence")
    fig.savefig(path, dpi=150)
    plt.close(fig)


def run(model_report_path: Path, spec_path: Path, figure_path: Path | None = None) -> dict[str, Any]:
    model_report = read_json(model_report_path)
    spec = read_json(spec_path)
    checks = spec_checks(spec)
    x, y, names, design_checks = load_design(model_report)
    checks.extend(design_checks)
    if any(not check["valid"] and check["severity"] == "error" for check in checks):
        error_count = sum(1 for check in checks if check["severity"] == "error" and not check["valid"])
        return {"valid": False, "summary": {"error_count": error_count, "warning_count": 0}, "diagnostics": {}, "checks": checks}

    result = sm.OLS(y, x, hasconst=True).fit()
    influence = OLSInfluence(result)
    residuals = np.asarray(result.resid, dtype=float)
    fitted = np.asarray(result.fittedvalues, dtype=float)
    leverage = np.asarray(influence.hat_matrix_diag, dtype=float)
    cooks = np.asarray(influence.cooks_distance[0], dtype=float)
    thresholds = spec["checks"]
    n, p = x.shape
    warning_flags: list[str] = []

    residual_mean = float(np.mean(residuals))
    tolerance = float(thresholds["residual_mean_abs_tolerance"])
    if abs(residual_mean) <= tolerance:
        checks.append(passed("residual_mean_near_zero", "error", round_float(residual_mean, 12), f"abs <= {tolerance}"))
    else:
        checks.append(failed("residual_mean_near_zero", "error", round_float(residual_mean, 12), f"abs <= {tolerance}"))

    condition_number = float(np.linalg.cond(x))
    if condition_number > float(thresholds["condition_number_max"]):
        warning_flags.append("high_condition_number")
        checks.append(failed("condition_number_below_threshold", "warning", round_float(condition_number), f"<= {thresholds['condition_number_max']}"))
    else:
        checks.append(passed("condition_number_below_threshold", "warning", round_float(condition_number), f"<= {thresholds['condition_number_max']}"))

    vif_values: list[dict[str, Any]] = []
    for index, name in enumerate(names):
        if name == "const":
            continue
        vif = float(variance_inflation_factor(x, index))
        flag = vif > float(thresholds["vif_max"])
        if flag:
            warning_flags.append(f"high_vif:{name}")
        vif_values.append({"term": name, "vif": round_float(vif), "flag": flag})
    if any(item["flag"] for item in vif_values):
        checks.append(failed("vif_below_threshold", "warning", vif_values, f"<= {thresholds['vif_max']}"))
    else:
        checks.append(passed("vif_below_threshold", "warning", vif_values, f"<= {thresholds['vif_max']}"))

    leverage_threshold = float(thresholds["leverage_threshold_multiplier"]) * p / n
    leverage_points = [
        {"row": index, "leverage": round_float(value)}
        for index, value in enumerate(leverage)
        if value > leverage_threshold
    ]
    if leverage_points:
        warning_flags.append("high_leverage_points")
        checks.append(failed("leverage_below_threshold", "warning", len(leverage_points), f"<= {round_float(leverage_threshold)}", leverage_points))
    else:
        checks.append(passed("leverage_below_threshold", "warning", 0, f"<= {round_float(leverage_threshold)}"))

    cook_threshold = float(thresholds["cook_distance_threshold_multiplier"]) / n
    cook_points = [
        {"row": index, "cook_distance": round_float(value)}
        for index, value in enumerate(cooks)
        if value > cook_threshold
    ]
    if cook_points:
        warning_flags.append("high_cook_distance")
        checks.append(failed("cook_distance_below_threshold", "warning", len(cook_points), f"<= {round_float(cook_threshold)}", cook_points))
    else:
        checks.append(passed("cook_distance_below_threshold", "warning", 0, f"<= {round_float(cook_threshold)}"))

    if n < int(thresholds["min_n_for_normality_test"]):
        warning_flags.append("too_few_rows_for_residual_normality_test")
        normality = {"method": "jarque_bera", "statistic": None, "pvalue": None, "status": "skipped"}
        checks.append(failed("residual_normality_test_available", "warning", n, f">= {thresholds['min_n_for_normality_test']}"))
    else:
        jb_stat, jb_pvalue, _, _ = sm.stats.jarque_bera(residuals)
        normality = {"method": "jarque_bera", "statistic": round_float(jb_stat), "pvalue": round_float(jb_pvalue), "status": "computed"}
        checks.append(passed("residual_normality_test_available", "warning", n, f">= {thresholds['min_n_for_normality_test']}"))

    if n < int(thresholds["min_n_for_heteroscedasticity_test"]):
        warning_flags.append("too_few_rows_for_breusch_pagan")
        heteroscedasticity = {"method": "breusch_pagan", "lm_statistic": None, "lm_pvalue": None, "status": "skipped"}
        checks.append(failed("heteroscedasticity_test_available", "warning", n, f">= {thresholds['min_n_for_heteroscedasticity_test']}"))
    else:
        lm_stat, lm_pvalue, _, _ = het_breuschpagan(residuals, x)
        heteroscedasticity = {"method": "breusch_pagan", "lm_statistic": round_float(lm_stat), "lm_pvalue": round_float(lm_pvalue), "status": "computed"}
        checks.append(passed("heteroscedasticity_test_available", "warning", n, f">= {thresholds['min_n_for_heteroscedasticity_test']}"))

    abs_residual_correlation = corr_or_none(fitted, np.abs(residuals))
    if abs_residual_correlation is not None and abs(abs_residual_correlation) > float(thresholds["nonlinearity_abs_correlation_threshold"]):
        warning_flags.append("residual_scale_related_to_fitted")
        checks.append(failed("residual_scale_not_related_to_fitted", "warning", round_float(abs_residual_correlation), f"abs <= {thresholds['nonlinearity_abs_correlation_threshold']}"))
    else:
        checks.append(passed("residual_scale_not_related_to_fitted", "warning", round_float(abs_residual_correlation), f"abs <= {thresholds['nonlinearity_abs_correlation_threshold']}"))

    if figure_path is not None:
        build_figure(figure_path, fitted, residuals, leverage, cooks)

    error_count = sum(1 for check in checks if check["severity"] == "error" and not check["valid"])
    warning_count = sum(1 for check in checks if check["severity"] == "warning" and not check["valid"])
    return {
        "valid": error_count == 0,
        "summary": {
            "diagnostic_id": spec["diagnostic_id"],
            "rows": n,
            "terms": p,
            "error_count": error_count,
            "warning_count": warning_count,
            "warning_flags": sorted(set(warning_flags)),
        },
        "diagnostics": {
            "residuals": {
                "mean": round_float(residual_mean, 12),
                "standard_deviation": round_float(float(np.std(residuals, ddof=1))),
                "min": round_float(float(np.min(residuals))),
                "max": round_float(float(np.max(residuals))),
            },
            "condition_number": round_float(condition_number),
            "vif": vif_values,
            "leverage": {
                "threshold": round_float(leverage_threshold),
                "values": [round_float(value) for value in leverage.tolist()],
                "flagged_points": leverage_points,
            },
            "cook_distance": {
                "threshold": round_float(cook_threshold),
                "values": [round_float(value) for value in cooks.tolist()],
                "flagged_points": cook_points,
            },
            "normality": normality,
            "heteroscedasticity": heteroscedasticity,
            "residual_scale_correlation_with_fitted": round_float(abs_residual_correlation),
        },
        "limitations": spec["known_limitations"],
        "checks": checks,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check OLS regression diagnostics and write diagnostic figure")
    parser.add_argument("--model-report", type=Path, required=True)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output-report", type=Path, required=True)
    parser.add_argument("--output-figure", type=Path, required=True)
    args = parser.parse_args(argv)
    report = run(args.model_report, args.spec, args.output_figure)
    args.output_report.parent.mkdir(parents=True, exist_ok=True)
    args.output_report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "valid": report["valid"],
                "warning_count": report["summary"]["warning_count"],
                "error_count": report["summary"]["error_count"],
                "warning_flags": report["summary"]["warning_flags"],
            },
            ensure_ascii=False,
        )
    )
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
