from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import statistics
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from scipy import stats


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as source:
        value = json.load(source)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain JSON object")
    return value


def parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise ValueError(f"expected boolean string, got {value!r}")


def round_float(value: float | None, digits: int = 6) -> float | None:
    if value is None or not np.isfinite(value):
        return None
    return round(float(value), digits)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def observed_rows(sample_path: Path) -> list[dict[str, str]]:
    return [
        row
        for row in read_csv(sample_path)
        if parse_bool(row["outcome_observed"]) and int(row["observed_days"]) >= 7
    ]


def winsorized_mean(values: list[float], lower_q: float = 0.1, upper_q: float = 0.9) -> float:
    lower, upper = np.quantile(np.asarray(values, dtype=float), [lower_q, upper_q])
    clipped = np.clip(values, lower, upper)
    return float(np.mean(clipped))


def robust_estimates(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    revenue = [float(row["first_order_amount_rub"]) for row in rows]
    onboarding = [float(row["onboarding_seconds"]) for row in rows]
    activation = [1.0 if parse_bool(row["activated_7d"]) else 0.0 for row in rows]
    tickets = [float(row["support_tickets_7d"]) for row in rows]
    return [
        {
            "metric_id": "first_order_amount_rub",
            "method": "mean",
            "estimate": round_float(statistics.fmean(revenue)),
            "limitation": "Sensitive to zero mass and large purchases.",
        },
        {
            "metric_id": "first_order_amount_rub",
            "method": "median",
            "estimate": round_float(statistics.median(revenue)),
            "limitation": "Robust to large purchases but ignores upper-tail business value.",
        },
        {
            "metric_id": "first_order_amount_rub",
            "method": "trimmed_mean_20pct",
            "estimate": round_float(float(stats.trim_mean(revenue, 0.2))),
            "limitation": "Drops both tails; useful as sensitivity, not replacement revenue metric.",
        },
        {
            "metric_id": "first_order_amount_rub",
            "method": "winsorized_mean_10_90",
            "estimate": round_float(winsorized_mean(revenue)),
            "limitation": "Caps tails at 10/90 percentiles to measure outlier sensitivity.",
        },
        {
            "metric_id": "onboarding_seconds",
            "method": "median",
            "estimate": round_float(statistics.median(onboarding)),
            "limitation": "Robust center for right-tailed onboarding duration.",
        },
        {
            "metric_id": "activated_7d",
            "method": "sample_proportion",
            "estimate": round_float(statistics.fmean(activation)),
            "limitation": "Binary metric; robust sensitivity focuses on resampling and exact/binomial alternatives.",
        },
        {
            "metric_id": "support_tickets_7d",
            "method": "median_count",
            "estimate": round_float(statistics.median(tickets)),
            "limitation": "Median hides rare tickets; report together with count-rate estimate.",
        },
    ]


def sensitivity_report(rows: list[dict[str, str]], diagnostics: dict[str, Any]) -> dict[str, Any]:
    revenue = np.asarray([float(row["first_order_amount_rub"]) for row in rows], dtype=float)
    leave_one_out = []
    for index, row in enumerate(rows):
        kept = np.delete(revenue, index)
        leave_one_out.append(
            {
                "left_out_user_id": row["user_id"],
                "first_order_amount_mean": round_float(float(np.mean(kept))),
            }
        )
    sessions_active = [float(row["sessions_7d"]) for row in rows if parse_bool(row["activated_7d"])]
    sessions_inactive = [float(row["sessions_7d"]) for row in rows if not parse_bool(row["activated_7d"])]
    if sessions_active and sessions_inactive:
        mann = stats.mannwhitneyu(sessions_active, sessions_inactive, alternative="two-sided")
        mann_whitney = {
            "metric": "sessions_7d_by_activated_7d",
            "method": "mann_whitney_u",
            "u_statistic": round_float(float(mann.statistic)),
            "p_value": round_float(float(mann.pvalue)),
            "group_sizes": {"activated": len(sessions_active), "not_activated": len(sessions_inactive)},
            "warning": "small_group" if min(len(sessions_active), len(sessions_inactive)) < 3 else None,
        }
    else:
        mann_whitney = {"metric": "sessions_7d_by_activated_7d", "method": "mann_whitney_u", "status": "blocked"}
    means = [item["first_order_amount_mean"] for item in leave_one_out]
    return {
        "leave_one_out_revenue": {
            "baseline_mean": round_float(float(np.mean(revenue))),
            "min_mean": round_float(min(means)),
            "max_mean": round_float(max(means)),
            "max_abs_delta": round_float(max(abs(value - float(np.mean(revenue))) for value in means)),
            "rows": leave_one_out,
        },
        "nonparametric_comparison": mann_whitney,
        "regression_warning_flags": diagnostics.get("summary", {}).get("warning_flags", []),
        "interpretation": "Robust and nonparametric checks are sensitivity evidence; they do not remove sampling, observational, or model-specification limitations.",
    }


def copy_required_files(phase_root: Path, output_dir: Path) -> dict[str, Path]:
    mapping = {
        "sampling/population-and-frame.json": phase_root / "01-population-and-sample" / "outputs" / "sampling_spec.json",
        "sampling/sampling-audit.json": phase_root / "03-estimators" / "outputs" / "upstream_sampling_audit.json",
        "distributions/distribution-cards.json": phase_root / "02-distributions" / "outputs" / "distribution_cards.json",
        "estimates/point-estimates.csv": phase_root / "03-estimators" / "outputs" / "point_estimates.csv",
        "estimates/bias-variance.csv": phase_root / "04-bias-and-variance" / "outputs" / "bias_variance.csv",
        "estimates/confidence-intervals.csv": phase_root / "05-confidence-intervals" / "outputs" / "confidence_intervals.csv",
        "estimates/bootstrap-intervals.json": phase_root / "06-bootstrap" / "outputs" / "bootstrap_intervals.json",
        "association/correlation-audit.json": phase_root / "07-correlation" / "outputs" / "correlation_audit.json",
        "regression/model-spec.json": phase_root / "08-linear-regression" / "outputs" / "model_spec.json",
        "regression/coefficients.csv": phase_root / "08-linear-regression" / "outputs" / "coefficients.csv",
        "regression/diagnostics.json": phase_root / "09-regression-diagnostics" / "outputs" / "diagnostics.json",
        "figures/regression-diagnostics.png": phase_root / "09-regression-diagnostics" / "outputs" / "regression_diagnostics.png",
    }
    copied: dict[str, Path] = {}
    for relative, source in mapping.items():
        target = output_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        copied[relative] = target
    return copied


def build_sampling_bias_figure(output_path: Path, bias_variance_csv: Path) -> None:
    rows = [
        row
        for row in read_csv(bias_variance_csv)
        if row["parameter_id"] == "activation_rate" and row["estimator_id"] == "activation_naive"
    ]
    labels = [row["mechanism_id"].replace("_", "\n") for row in rows]
    values = [float(row["bias"]) for row in rows]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(6, 3.2), constrained_layout=True)
    ax.axhline(0, color="#555555", linewidth=1)
    ax.bar(labels, values, color="#2563eb")
    ax.set_ylabel("Bias")
    ax.set_title("Activation estimate bias by sampling mechanism")
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def build_interval_coverage_figure(output_path: Path, intervals_csv: Path) -> None:
    rows = [row for row in read_csv(intervals_csv) if row["coverage_rate"]]
    labels = [row["interval_id"].replace("_", "\n") for row in rows]
    values = [float(row["coverage_rate"]) for row in rows]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(6, 3.2), constrained_layout=True)
    ax.axhline(0.95, color="#dc2626", linewidth=1, linestyle="--")
    ax.bar(labels, values, color="#059669")
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("Coverage rate")
    ax.set_title("Formula interval coverage simulation")
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def manifest(output_dir: Path) -> dict[str, Any]:
    files: dict[str, Any] = {}
    for path in sorted(output_dir.rglob("*")):
        if path.is_file() and path.name != "manifest.json":
            relative = path.relative_to(output_dir).as_posix()
            files[relative] = {"sha256": sha256(path), "bytes": path.stat().st_size}
    return {"files": files, "file_count": len(files)}


def verify_manifest(output_dir: Path) -> dict[str, Any]:
    package_manifest = read_json(output_dir / "manifest.json")
    errors: list[dict[str, str]] = []
    for relative, metadata in package_manifest.get("files", {}).items():
        path = output_dir / relative
        if not path.is_file():
            errors.append({"path": relative, "error": "missing"})
            continue
        actual = sha256(path)
        if actual != metadata.get("sha256"):
            errors.append({"path": relative, "error": "checksum_mismatch"})
    return {"valid": not errors, "errors": errors}


def build_report_md(output_dir: Path, sensitivity: dict[str, Any]) -> None:
    warning_flags = ", ".join(sensitivity["regression_warning_flags"]) or "none"
    text = f"""# Statistical Evidence Report

## Question

Can we trust early activation, revenue, association and regression evidence from the current user-level sample?

## Main Answer

The package supports association-only statistical evidence with explicit limitations. Point estimates and intervals are available, but sampling coverage warnings, weak tiny-sample intervals, bootstrap discreteness and regression diagnostics prevent causal or production-decision claims.

## Evidence

- Sampling audit: `sampling/sampling-audit.json`.
- Distribution cards: `distributions/distribution-cards.json`.
- Point estimates and bias/variance: `estimates/point-estimates.csv`, `estimates/bias-variance.csv`.
- Formula and bootstrap intervals: `estimates/confidence-intervals.csv`, `estimates/bootstrap-intervals.json`.
- Correlation audit: `association/correlation-audit.json`.
- OLS inference and diagnostics: `regression/coefficients.csv`, `regression/diagnostics.json`.
- Robust sensitivity: `robustness/robust-estimates.csv`, `robustness/sensitivity.json`.

## Robustness

Leave-one-out revenue max absolute delta is `{sensitivity['leave_one_out_revenue']['max_abs_delta']}` RUB. Regression warning flags: `{warning_flags}`.

## Limitations

Coverage bias, non-response, tiny sample size, observational design, formula interval under-coverage and regression specification warnings remain active. The next decision should use this as evidence preparation, not as an experiment result.
"""
    (output_dir / "report.md").write_text(text, encoding="utf-8")


def build_package(phase_root: Path, output_dir: Path) -> dict[str, Any]:
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    copied = copy_required_files(phase_root, output_dir)
    rows = observed_rows(phase_root / "data" / "tiny" / "sample_observations.csv")
    diagnostics = read_json(phase_root / "09-regression-diagnostics" / "outputs" / "diagnostics.json")

    question = {
        "question_id": "phase_09_statistical_evidence",
        "target_population": "Eligible non-test registered users with complete seven-day windows.",
        "sampling_unit": "user_id",
        "allowed_claim_type": "association_and_estimation_with_limitations",
        "forbidden_claims": ["causal effect", "experiment result", "production forecast"],
    }
    write_json(output_dir / "question.json", question)

    robust_rows = robust_estimates(rows)
    write_csv(
        output_dir / "robustness" / "robust-estimates.csv",
        robust_rows,
        ["metric_id", "method", "estimate", "limitation"],
    )
    sensitivity = sensitivity_report(rows, diagnostics)
    if not sensitivity["regression_warning_flags"]:
        raise ValueError("regression diagnostics must preserve at least one warning flag")
    write_json(output_dir / "robustness" / "sensitivity.json", sensitivity)
    build_sampling_bias_figure(output_dir / "figures" / "sampling-bias.png", copied["estimates/bias-variance.csv"])
    build_interval_coverage_figure(output_dir / "figures" / "interval-coverage.png", copied["estimates/confidence-intervals.csv"])
    build_report_md(output_dir, sensitivity)
    package_manifest = manifest(output_dir)
    write_json(output_dir / "manifest.json", package_manifest)
    verification = verify_manifest(output_dir)
    return {
        "valid": verification["valid"],
        "summary": {
            "output_dir": str(output_dir),
            "files": package_manifest["file_count"],
            "observed_rows": len(rows),
            "robust_estimates": len(robust_rows),
        },
        "manifest": package_manifest,
        "verification": verification,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build final phase 09 statistical evidence package")
    parser.add_argument("--phase-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    report = build_package(args.phase_root, args.output_dir)
    print(json.dumps({"valid": report["valid"], **report["summary"]}, ensure_ascii=False))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
