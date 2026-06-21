from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
from scipy import stats
from statsmodels.stats.power import NormalIndPower, TTestIndPower
from statsmodels.stats.proportion import proportion_effectsize


PLAN_FIELDS = [
    "metric_id",
    "metric_type",
    "baseline",
    "mde_absolute",
    "mde_relative",
    "effect_size",
    "required_n_control",
    "required_n_treatment",
    "required_total_units",
    "runtime_days_unconstrained",
    "recommended_runtime_days",
    "planned_n_control",
    "planned_n_treatment",
    "planned_power",
    "simulation_power",
    "simulation_repetitions",
    "status",
]

GRID_FIELDS = [
    "metric_id",
    "mde_absolute",
    "mde_relative",
    "effect_size",
    "required_n_control",
    "required_n_treatment",
    "required_total_units",
    "runtime_days_unconstrained",
    "recommended_runtime_days",
    "planned_power",
]


def read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as source:
        value = json.load(source)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def parse_float(value: str | int | float) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if value.strip() == "":
        raise ValueError("empty numeric value")
    return float(value)


def round_float(value: float, digits: int = 6) -> float | str:
    if math.isnan(value):
        return "nan"
    if math.isinf(value):
        return "inf"
    return round(value, digits)


def baseline_by_metric(rows: list[dict[str, str]], experiment_id: str) -> dict[str, dict[str, str]]:
    return {row["metric_id"]: row for row in rows if row.get("experiment_id") == experiment_id}


def allocation_ratio(protocol: dict[str, Any]) -> tuple[float, float, float]:
    allocation = protocol["traffic_allocation"]
    variants = protocol["variants"]
    control_id = next(item["variant_id"] for item in variants if item.get("is_control") is True)
    treatment_id = next(item["variant_id"] for item in variants if item.get("is_control") is False)
    control_share = parse_float(allocation[control_id])
    treatment_share = parse_float(allocation[treatment_id])
    if control_share <= 0 or treatment_share <= 0:
        raise ValueError("control and treatment allocation shares must be positive")
    return control_share, treatment_share, treatment_share / control_share


def metric_mde(metric_spec: dict[str, Any], protocol: dict[str, Any]) -> float:
    if metric_spec.get("mde_source") == "protocol.minimum_detectable_effect":
        protocol_mde = protocol["minimum_detectable_effect"]
        if protocol_mde["metric_id"] != metric_spec["metric_id"]:
            raise ValueError("protocol MDE metric does not match primary metric spec")
        return parse_float(protocol_mde["absolute"])
    return parse_float(metric_spec["mde_absolute"])


def runtime_days(total_units: int, expected_daily_units: int, minimum_runtime_days: int) -> tuple[int, int]:
    unconstrained = math.ceil(total_units / expected_daily_units)
    return unconstrained, max(unconstrained, minimum_runtime_days)


def planned_units(protocol: dict[str, Any], ratio: float) -> tuple[int, int]:
    control_n = int(protocol["sample_size_plan"]["planned_units_per_variant"])
    treatment_n = math.ceil(control_n * ratio)
    return control_n, treatment_n


def status_for_power(
    formula_power: float,
    simulation_power: float,
    target_power: float,
    tolerance: float,
) -> str:
    if abs(target_power - simulation_power) > tolerance:
        return "simulation_mismatch"
    if formula_power < target_power:
        return "underpowered"
    return "ready"


def proportion_plan_row(
    metric_spec: dict[str, Any],
    baseline: float,
    mde: float,
    protocol: dict[str, Any],
    power_spec: dict[str, Any],
    seed: int,
) -> dict[str, Any]:
    alpha = parse_float(protocol["alpha"])
    target_power = parse_float(protocol["power"])
    expected_daily_units = int(protocol["sample_size_plan"]["expected_daily_eligible_units"])
    minimum_runtime_days = int(protocol["minimum_runtime_days"])
    _, _, ratio = allocation_ratio(protocol)
    treatment = baseline + mde
    if not 0 < baseline < 1 or not 0 < treatment < 1:
        raise ValueError(f"{metric_spec['metric_id']} proportion baseline and MDE must stay inside (0, 1)")
    effect_size = abs(proportion_effectsize(treatment, baseline))
    solver = NormalIndPower()
    required_control = math.ceil(
        solver.solve_power(
            effect_size=effect_size,
            alpha=alpha,
            power=target_power,
            ratio=ratio,
            alternative=metric_spec["alternative"],
        )
    )
    required_treatment = math.ceil(required_control * ratio)
    total_units = required_control + required_treatment
    runtime_raw, runtime_recommended = runtime_days(total_units, expected_daily_units, minimum_runtime_days)
    planned_control, planned_treatment = planned_units(protocol, ratio)
    planned_power = float(
        solver.power(
            effect_size=effect_size,
            nobs1=planned_control,
            alpha=alpha,
            ratio=ratio,
            alternative=metric_spec["alternative"],
        )
    )
    repetitions = int(power_spec["simulation_repetitions"]["proportion"])
    simulation_power = simulate_proportion_power(
        baseline,
        treatment,
        required_control,
        required_treatment,
        alpha,
        repetitions,
        seed,
    )
    return {
        "metric_id": metric_spec["metric_id"],
        "metric_type": "proportion",
        "baseline": round_float(baseline),
        "mde_absolute": round_float(mde),
        "mde_relative": round_float(mde / baseline),
        "effect_size": round_float(effect_size),
        "required_n_control": required_control,
        "required_n_treatment": required_treatment,
        "required_total_units": total_units,
        "runtime_days_unconstrained": runtime_raw,
        "recommended_runtime_days": runtime_recommended,
        "planned_n_control": planned_control,
        "planned_n_treatment": planned_treatment,
        "planned_power": round_float(planned_power),
        "simulation_power": round_float(simulation_power),
        "simulation_repetitions": repetitions,
        "status": status_for_power(planned_power, simulation_power, target_power, parse_float(power_spec["simulation_tolerance"])),
    }


def mean_plan_row(
    metric_spec: dict[str, Any],
    baseline: float,
    mde: float,
    protocol: dict[str, Any],
    power_spec: dict[str, Any],
    seed: int,
) -> dict[str, Any]:
    alpha = parse_float(protocol["alpha"])
    target_power = parse_float(protocol["power"])
    expected_daily_units = int(protocol["sample_size_plan"]["expected_daily_eligible_units"])
    minimum_runtime_days = int(protocol["minimum_runtime_days"])
    _, _, ratio = allocation_ratio(protocol)
    sd = parse_float(metric_spec["baseline_standard_deviation"])
    if sd <= 0:
        raise ValueError("baseline_standard_deviation must be positive")
    effect_size = abs(mde / sd)
    solver = TTestIndPower()
    required_control = math.ceil(
        solver.solve_power(
            effect_size=effect_size,
            alpha=alpha,
            power=target_power,
            ratio=ratio,
            alternative=metric_spec["alternative"],
        )
    )
    required_treatment = math.ceil(required_control * ratio)
    total_units = required_control + required_treatment
    runtime_raw, runtime_recommended = runtime_days(total_units, expected_daily_units, minimum_runtime_days)
    planned_control, planned_treatment = planned_units(protocol, ratio)
    planned_power = float(
        solver.power(
            effect_size=effect_size,
            nobs1=planned_control,
            alpha=alpha,
            ratio=ratio,
            alternative=metric_spec["alternative"],
        )
    )
    repetitions = int(power_spec["simulation_repetitions"]["mean"])
    simulation_power = simulate_mean_power(
        baseline,
        baseline + mde,
        sd,
        required_control,
        required_treatment,
        alpha,
        repetitions,
        seed,
    )
    return {
        "metric_id": metric_spec["metric_id"],
        "metric_type": "mean",
        "baseline": round_float(baseline),
        "baseline_standard_deviation": round_float(sd),
        "mde_absolute": round_float(mde),
        "mde_relative": round_float(mde / baseline if baseline else math.inf),
        "effect_size": round_float(effect_size),
        "required_n_control": required_control,
        "required_n_treatment": required_treatment,
        "required_total_units": total_units,
        "runtime_days_unconstrained": runtime_raw,
        "recommended_runtime_days": runtime_recommended,
        "planned_n_control": planned_control,
        "planned_n_treatment": planned_treatment,
        "planned_power": round_float(planned_power),
        "simulation_power": round_float(simulation_power),
        "simulation_repetitions": repetitions,
        "status": status_for_power(planned_power, simulation_power, target_power, parse_float(power_spec["simulation_tolerance"])),
    }


def simulate_proportion_power(
    control_rate: float,
    treatment_rate: float,
    n_control: int,
    n_treatment: int,
    alpha: float,
    repetitions: int,
    seed: int,
) -> float:
    rng = np.random.default_rng(seed)
    control_success = rng.binomial(n_control, control_rate, repetitions)
    treatment_success = rng.binomial(n_treatment, treatment_rate, repetitions)
    control_rate_observed = control_success / n_control
    treatment_rate_observed = treatment_success / n_treatment
    pooled = (control_success + treatment_success) / (n_control + n_treatment)
    standard_error = np.sqrt(pooled * (1 - pooled) * (1 / n_control + 1 / n_treatment))
    z_score = (treatment_rate_observed - control_rate_observed) / standard_error
    p_values = stats.norm.sf(z_score)
    return float(np.mean(p_values <= alpha))


def simulate_mean_power(
    control_mean: float,
    treatment_mean: float,
    sd: float,
    n_control: int,
    n_treatment: int,
    alpha: float,
    repetitions: int,
    seed: int,
) -> float:
    rng = np.random.default_rng(seed)
    rejected = 0
    completed = 0
    batch_size = 100
    while completed < repetitions:
        batch = min(batch_size, repetitions - completed)
        control = rng.normal(control_mean, sd, size=(batch, n_control))
        treatment = rng.normal(treatment_mean, sd, size=(batch, n_treatment))
        result = stats.ttest_ind(control, treatment, axis=1, equal_var=False, alternative="less")
        rejected += int(np.sum(result.pvalue <= alpha))
        completed += batch
    return rejected / repetitions


def build_mde_grid(
    primary_metric_spec: dict[str, Any],
    baseline: float,
    protocol: dict[str, Any],
    power_spec: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    alpha = parse_float(protocol["alpha"])
    target_power = parse_float(protocol["power"])
    expected_daily_units = int(protocol["sample_size_plan"]["expected_daily_eligible_units"])
    minimum_runtime_days = int(protocol["minimum_runtime_days"])
    _, _, ratio = allocation_ratio(protocol)
    planned_control, planned_treatment = planned_units(protocol, ratio)
    solver = NormalIndPower()
    for effect in power_spec["grid_absolute_effects"]:
        mde = parse_float(effect)
        treatment = baseline + mde
        effect_size = abs(proportion_effectsize(treatment, baseline))
        required_control = math.ceil(
            solver.solve_power(
                effect_size=effect_size,
                alpha=alpha,
                power=target_power,
                ratio=ratio,
                alternative=primary_metric_spec["alternative"],
            )
        )
        required_treatment = math.ceil(required_control * ratio)
        total_units = required_control + required_treatment
        runtime_raw, runtime_recommended = runtime_days(total_units, expected_daily_units, minimum_runtime_days)
        planned_power = solver.power(
            effect_size=effect_size,
            nobs1=planned_control,
            alpha=alpha,
            ratio=ratio,
            alternative=primary_metric_spec["alternative"],
        )
        rows.append(
            {
                "metric_id": primary_metric_spec["metric_id"],
                "mde_absolute": round_float(mde),
                "mde_relative": round_float(mde / baseline),
                "effect_size": round_float(effect_size),
                "required_n_control": required_control,
                "required_n_treatment": required_treatment,
                "required_total_units": total_units,
                "runtime_days_unconstrained": runtime_raw,
                "recommended_runtime_days": runtime_recommended,
                "planned_power": round_float(float(planned_power)),
            }
        )
    return rows


def render_power_curve(path: Path, grid_rows: list[dict[str, Any]], protocol: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    x = [100 * parse_float(row["mde_absolute"]) for row in grid_rows]
    y = [parse_float(row["planned_power"]) for row in grid_rows]
    target_power = parse_float(protocol["power"])
    fig, ax = plt.subplots(figsize=(7, 4.2))
    ax.plot(x, y, marker="o", color="#2563eb", linewidth=2)
    ax.axhline(target_power, color="#dc2626", linestyle="--", linewidth=1.5, label=f"target power {target_power:.0%}")
    ax.set_xlabel("Absolute MDE, percentage points")
    ax.set_ylabel("Power at planned sample")
    ax.set_ylim(0, 1.05)
    ax.set_title("Power curve for activation_rate_7d")
    ax.grid(True, color="#d1d5db", linewidth=0.8, alpha=0.7)
    ax.legend(loc="lower right")
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def build_plan(
    protocol: dict[str, Any],
    metric_baselines: list[dict[str, str]],
    health_report: dict[str, Any],
    power_spec: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    experiment_id = str(protocol["experiment_id"])
    if power_spec.get("experiment_id") != experiment_id:
        raise ValueError("power spec experiment_id must match protocol")
    health_blocking = list(health_report.get("summary", {}).get("blocking_failures", []))
    if health_report.get("ready_for_ab_analysis") is not True:
        plan = {
            "valid": False,
            "ready_for_sizing": False,
            "summary": {
                "experiment_id": experiment_id,
                "blocking_failures": ["upstream_randomization_health_not_ready"] + health_blocking,
            },
            "checks": [
                {
                    "id": "upstream_randomization_health_ready",
                    "severity": "error",
                    "valid": False,
                    "observed": health_report.get("ready_for_ab_analysis"),
                    "expected": True,
                    "sample": health_blocking,
                }
            ],
            "metric_plans": [],
        }
        return plan, []
    baselines = baseline_by_metric(metric_baselines, experiment_id)
    metric_plans: list[dict[str, Any]] = []
    random_seed = int(power_spec["random_seed"])
    for index, metric_spec in enumerate(power_spec["metrics"]):
        metric_id = metric_spec["metric_id"]
        if metric_id not in baselines:
            raise ValueError(f"missing baseline for metric {metric_id}")
        baseline = parse_float(baselines[metric_id]["baseline_value"])
        mde = metric_mde(metric_spec, protocol)
        seed = random_seed + 101 * (index + 1)
        if metric_spec["metric_type"] == "proportion":
            metric_plans.append(proportion_plan_row(metric_spec, baseline, mde, protocol, power_spec, seed))
        elif metric_spec["metric_type"] == "mean":
            metric_plans.append(mean_plan_row(metric_spec, baseline, mde, protocol, power_spec, seed))
        else:
            raise ValueError(f"unsupported metric_type: {metric_spec['metric_type']}")
    primary_spec = next(metric for metric in power_spec["metrics"] if metric["metric_id"] == protocol["primary_metric"])
    grid_rows = build_mde_grid(primary_spec, parse_float(baselines[protocol["primary_metric"]]["baseline_value"]), protocol, power_spec)
    statuses = [row["status"] for row in metric_plans]
    plan = {
        "valid": all(status == "ready" for status in statuses),
        "ready_for_sizing": True,
        "summary": {
            "experiment_id": experiment_id,
            "alpha": protocol["alpha"],
            "target_power": protocol["power"],
            "allocation_ratio": protocol["sample_size_plan"]["allocation_ratio"],
            "expected_daily_eligible_units": protocol["sample_size_plan"]["expected_daily_eligible_units"],
            "minimum_runtime_days": protocol["minimum_runtime_days"],
            "planned_units_per_variant": protocol["sample_size_plan"]["planned_units_per_variant"],
            "metric_statuses": {row["metric_id"]: row["status"] for row in metric_plans},
        },
        "checks": [
            {
                "id": "upstream_randomization_health_ready",
                "severity": "error",
                "valid": True,
                "observed": health_report.get("ready_for_ab_analysis"),
                "expected": True,
                "sample": health_report.get("summary", {}).get("warning_checks", []),
            },
            {
                "id": "planned_sample_meets_target_power",
                "severity": "error",
                "valid": all(row["planned_power"] >= protocol["power"] for row in metric_plans),
                "observed": {row["metric_id"]: row["planned_power"] for row in metric_plans},
                "expected": f">= {protocol['power']}",
                "sample": [row for row in metric_plans if row["planned_power"] < protocol["power"]],
            },
            {
                "id": "simulation_matches_formula_power",
                "severity": "warning",
                "valid": all(row["status"] != "simulation_mismatch" for row in metric_plans),
                "observed": {row["metric_id"]: row["simulation_power"] for row in metric_plans},
                "expected": f"within {power_spec['simulation_tolerance']} of target power at required sample",
                "sample": [row for row in metric_plans if row["status"] == "simulation_mismatch"],
            },
        ],
        "metric_plans": metric_plans,
        "mde_grid_path": "outputs/mde_grid.csv",
        "power_curve_path": "outputs/power_curve.png",
    }
    return plan, grid_rows


def run(
    protocol_path: Path,
    metric_baselines_path: Path,
    health_report_path: Path,
    power_spec_path: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    protocol = read_json(protocol_path)
    metric_baselines = read_csv(metric_baselines_path)
    health_report = read_json(health_report_path)
    power_spec = read_json(power_spec_path)
    return build_plan(protocol, metric_baselines, health_report, power_spec)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Plan MDE, sample size, runtime and power for a fixed-horizon A/B test")
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--metric-baselines", type=Path, required=True)
    parser.add_argument("--health-report", type=Path, required=True)
    parser.add_argument("--power-spec", type=Path, required=True)
    parser.add_argument("--output-plan", type=Path)
    parser.add_argument("--output-grid", type=Path)
    parser.add_argument("--output-figure", type=Path)
    parser.add_argument("--allow-failures", action="store_true")
    args = parser.parse_args(argv)
    try:
        plan, grid_rows = run(args.protocol, args.metric_baselines, args.health_report, args.power_spec)
    except (OSError, json.JSONDecodeError, KeyError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2
    if args.output_plan is not None:
        write_json(args.output_plan, plan)
    if args.output_grid is not None and grid_rows:
        write_csv(args.output_grid, grid_rows, GRID_FIELDS)
    if args.output_figure is not None and grid_rows:
        render_power_curve(args.output_figure, grid_rows, read_json(args.protocol))
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    if plan["valid"] or args.allow_failures:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
