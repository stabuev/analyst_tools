from __future__ import annotations

import argparse
import csv
import json
import statistics
from pathlib import Path
from typing import Any

import numpy as np

SUPPORTED_VALUE_TYPES = {"boolean", "numeric"}
SUPPORTED_SELECTION = {"equal_without_replacement", "probability_without_replacement"}
SUPPORTED_ESTIMATORS = {
    "sample_mean",
    "sample_proportion",
    "inverse_probability_weighted_mean",
    "inverse_probability_weighted_proportion",
}
CSV_COLUMNS = [
    "mechanism_id",
    "estimator_id",
    "parameter_id",
    "true_parameter",
    "mean_estimate",
    "bias",
    "variance",
    "standard_deviation",
    "mse",
    "iterations_requested",
    "iterations_used",
    "skipped_iterations",
    "mean_observed_n",
    "bias_flag",
]


def passed(check_id: str, severity: str, observed: Any, expected: Any) -> dict[str, Any]:
    return {
        "id": check_id,
        "severity": severity,
        "valid": True,
        "observed": observed,
        "expected": expected,
        "sample": [],
    }


def failed(
    check_id: str,
    severity: str,
    observed: Any,
    expected: Any,
    sample: list[Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "severity": severity,
        "valid": False,
        "observed": observed,
        "expected": expected,
        "sample": sample or [],
    }


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as source:
        value = json.load(source)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise ValueError(f"expected boolean string, got {value!r}")


def parse_value(row: dict[str, str], column: str, value_type: str) -> float:
    if value_type == "boolean":
        return 1.0 if parse_bool(row[column]) else 0.0
    if value_type == "numeric":
        return float(row[column])
    raise ValueError(f"unsupported value_type: {value_type}")


def round_float(value: float | None, digits: int = 6) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def eligible_population(population: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        row
        for row in population
        if parse_bool(row["eligible_for_analysis"])
        and not parse_bool(row["is_test_user"])
        and int(row["true_observed_days"]) >= 7
    ]


def attach_frame(
    population_rows: list[dict[str, str]],
    frame_rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    population_by_id = {row["user_id"]: row for row in population_rows}
    attached: list[dict[str, str]] = []
    for frame_row in frame_rows:
        user = population_by_id.get(frame_row["user_id"])
        if user is not None:
            merged = dict(user)
            merged.update(frame_row)
            attached.append(merged)
    return attached


def spec_checks(spec: dict[str, Any]) -> list[dict[str, Any]]:
    required = {
        "version",
        "question_id",
        "target_population",
        "sampling_unit",
        "seed",
        "n_simulations",
        "minimum_observations",
        "bias_threshold",
        "parameters",
        "estimators",
        "mechanisms",
    }
    checks: list[dict[str, Any]] = []
    missing = sorted(required - set(spec))
    if missing:
        checks.append(failed("bias_variance_spec_required_fields", "error", sorted(spec), sorted(required), missing))
        return checks
    checks.append(passed("bias_variance_spec_required_fields", "error", sorted(required), sorted(required)))

    parameter_ids = [item.get("parameter_id") for item in spec["parameters"] if isinstance(item, dict)]
    estimator_ids = [item.get("estimator_id") for item in spec["estimators"] if isinstance(item, dict)]
    mechanism_ids = [item.get("mechanism_id") for item in spec["mechanisms"] if isinstance(item, dict)]
    for label, ids in (
        ("parameter_ids_unique", parameter_ids),
        ("estimator_ids_unique", estimator_ids),
        ("mechanism_ids_unique", mechanism_ids),
    ):
        duplicates = sorted({item for item in ids if ids.count(item) > 1})
        if duplicates:
            checks.append(failed(label, "error", duplicates, "unique ids"))
        else:
            checks.append(passed(label, "error", len(ids), "unique ids"))

    unsupported_values = sorted(
        item.get("value_type")
        for item in spec["parameters"]
        if isinstance(item, dict) and item.get("value_type") not in SUPPORTED_VALUE_TYPES
    )
    if unsupported_values:
        checks.append(failed("parameter_value_types_supported", "error", unsupported_values, sorted(SUPPORTED_VALUE_TYPES)))
    else:
        checks.append(passed("parameter_value_types_supported", "error", sorted(SUPPORTED_VALUE_TYPES), sorted(SUPPORTED_VALUE_TYPES)))

    parameter_set = set(parameter_ids)
    unknown_parameters = sorted(
        item.get("parameter_id")
        for item in spec["estimators"]
        if isinstance(item, dict) and item.get("parameter_id") not in parameter_set
    )
    if unknown_parameters:
        checks.append(failed("estimator_parameters_resolve", "error", unknown_parameters, sorted(parameter_set)))
    else:
        checks.append(passed("estimator_parameters_resolve", "error", sorted(parameter_set), sorted(parameter_set)))

    unsupported_estimators = sorted(
        item.get("estimator")
        for item in spec["estimators"]
        if isinstance(item, dict) and item.get("estimator") not in SUPPORTED_ESTIMATORS
    )
    if unsupported_estimators:
        checks.append(failed("estimators_supported", "error", unsupported_estimators, sorted(SUPPORTED_ESTIMATORS)))
    else:
        checks.append(passed("estimators_supported", "error", sorted(SUPPORTED_ESTIMATORS), sorted(SUPPORTED_ESTIMATORS)))

    estimator_set = set(estimator_ids)
    for mechanism in spec["mechanisms"]:
        if not isinstance(mechanism, dict):
            continue
        mechanism_id = mechanism.get("mechanism_id", "unknown_mechanism")
        if mechanism.get("selection") not in SUPPORTED_SELECTION:
            checks.append(
                failed(f"{mechanism_id}_selection_supported", "error", mechanism.get("selection"), sorted(SUPPORTED_SELECTION))
            )
        else:
            checks.append(passed(f"{mechanism_id}_selection_supported", "error", mechanism["selection"], sorted(SUPPORTED_SELECTION)))
        unknown_estimators = sorted(set(mechanism.get("estimators", [])) - estimator_set)
        if unknown_estimators:
            checks.append(failed(f"{mechanism_id}_estimators_resolve", "error", unknown_estimators, sorted(estimator_set)))
        else:
            checks.append(passed(f"{mechanism_id}_estimators_resolve", "error", sorted(mechanism.get("estimators", [])), sorted(estimator_set)))
    return checks


def true_parameters(
    rows: list[dict[str, str]],
    parameters: list[dict[str, Any]],
) -> tuple[dict[str, float], list[dict[str, Any]]]:
    checks: list[dict[str, Any]] = []
    result: dict[str, float] = {}
    columns = set(rows[0]) if rows else set()
    for parameter in parameters:
        parameter_id = parameter["parameter_id"]
        column = parameter["metric_column"]
        if column not in columns:
            checks.append(failed(f"{parameter_id}_metric_column_present", "error", column, sorted(columns)))
            continue
        values = [parse_value(row, column, parameter["value_type"]) for row in rows]
        result[parameter_id] = statistics.fmean(values)
        checks.append(passed(f"{parameter_id}_true_parameter_computed", "error", round_float(result[parameter_id]), "population mean"))
    return result, checks


def source_rows(
    mechanism: dict[str, Any],
    population_rows: list[dict[str, str]],
    frame_attached_rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    source = mechanism["source"]
    if source == "population":
        return population_rows
    if source == "frame":
        return frame_attached_rows
    raise ValueError(f"unsupported source: {source}")


def draw_sample(
    rng: np.random.Generator,
    rows: list[dict[str, str]],
    mechanism: dict[str, Any],
) -> list[dict[str, str]]:
    sample_size = int(mechanism["sample_size"])
    if sample_size > len(rows):
        raise ValueError(f"sample_size {sample_size} is larger than source rows {len(rows)}")

    if mechanism["selection"] == "equal_without_replacement":
        indices = rng.choice(len(rows), size=sample_size, replace=False)
    elif mechanism["selection"] == "probability_without_replacement":
        probability_column = mechanism["probability_column"]
        raw_probabilities = np.array([float(row[probability_column]) for row in rows], dtype=float)
        if np.any(raw_probabilities <= 0):
            raise ValueError(f"{probability_column} must be positive")
        probabilities = raw_probabilities / raw_probabilities.sum()
        indices = rng.choice(len(rows), size=sample_size, replace=False, p=probabilities)
    else:
        raise ValueError(f"unsupported selection: {mechanism['selection']}")

    selected = [dict(rows[int(index)]) for index in indices]
    if mechanism["response_model"] == "complete":
        return selected
    if mechanism["response_model"] == "bernoulli":
        response_column = mechanism["response_probability_column"]
        observed: list[dict[str, str]] = []
        for row in selected:
            if rng.random() < float(row[response_column]):
                observed.append(row)
        return observed
    raise ValueError(f"unsupported response_model: {mechanism['response_model']}")


def estimate_value(
    rows: list[dict[str, str]],
    estimator: dict[str, Any],
    parameter: dict[str, Any],
) -> float:
    values = [parse_value(row, parameter["metric_column"], parameter["value_type"]) for row in rows]
    estimator_name = estimator["estimator"]
    if estimator_name in {"sample_mean", "sample_proportion"}:
        return statistics.fmean(values)
    if estimator_name in {"inverse_probability_weighted_mean", "inverse_probability_weighted_proportion"}:
        weight_spec = estimator.get("weights")
        if not weight_spec:
            raise ValueError(f"{estimator['estimator_id']} requires weights")
        weights = [float(row[weight_spec["column"]]) for row in rows]
        return float(np.average(np.array(values, dtype=float), weights=np.array(weights, dtype=float)))
    raise ValueError(f"unsupported estimator: {estimator_name}")


def summarize_estimates(
    mechanism_id: str,
    estimator: dict[str, Any],
    true_parameter: float,
    estimates: list[float],
    observed_sizes: list[int],
    iterations_requested: int,
    bias_threshold: float,
) -> dict[str, Any]:
    mean_estimate = statistics.fmean(estimates)
    bias = mean_estimate - true_parameter
    variance = statistics.variance(estimates) if len(estimates) > 1 else 0.0
    mse = bias * bias + variance
    return {
        "mechanism_id": mechanism_id,
        "estimator_id": estimator["estimator_id"],
        "parameter_id": estimator["parameter_id"],
        "true_parameter": round_float(true_parameter),
        "mean_estimate": round_float(mean_estimate),
        "bias": round_float(bias),
        "variance": round_float(variance),
        "standard_deviation": round_float(variance ** 0.5),
        "mse": round_float(mse),
        "iterations_requested": iterations_requested,
        "iterations_used": len(estimates),
        "skipped_iterations": iterations_requested - len(estimates),
        "mean_observed_n": round_float(statistics.fmean(observed_sizes)),
        "bias_flag": abs(bias) > bias_threshold,
    }


def simulate(
    population_path: Path,
    frame_path: Path,
    spec_path: Path,
) -> dict[str, Any]:
    population_raw = read_csv(population_path)
    frame_raw = read_csv(frame_path)
    spec = read_json(spec_path)
    checks = spec_checks(spec)
    if any(not check["valid"] and check["severity"] == "error" for check in checks):
        return {
            "valid": False,
            "summary": {"rows": 0, "error_count": sum(not check["valid"] for check in checks)},
            "true_parameters": {},
            "simulation_rows": [],
            "checks": checks,
        }

    population_rows = eligible_population(population_raw)
    frame_attached_rows = attach_frame(population_rows, frame_raw)
    checks.append(passed("eligible_population_available", "error", len(population_rows), "> 0 eligible users"))
    checks.append(passed("frame_rows_attached_to_population", "error", len(frame_attached_rows), "> 0 frame users"))

    true_values, parameter_checks = true_parameters(population_rows, spec["parameters"])
    checks.extend(parameter_checks)
    if any(not check["valid"] and check["severity"] == "error" for check in checks):
        return {
            "valid": False,
            "summary": {"rows": 0, "error_count": sum(not check["valid"] for check in checks)},
            "true_parameters": true_values,
            "simulation_rows": [],
            "checks": checks,
        }

    parameter_by_id = {item["parameter_id"]: item for item in spec["parameters"]}
    estimator_by_id = {item["estimator_id"]: item for item in spec["estimators"]}
    rng = np.random.default_rng(int(spec["seed"]))
    iterations = int(spec["n_simulations"])
    minimum = int(spec["minimum_observations"])
    bias_threshold = float(spec["bias_threshold"])

    simulation_rows: list[dict[str, Any]] = []
    for mechanism in spec["mechanisms"]:
        mechanism_id = mechanism["mechanism_id"]
        rows = source_rows(mechanism, population_rows, frame_attached_rows)
        checks.append(passed(f"{mechanism_id}_source_rows_available", "error", len(rows), "source rows"))
        estimate_store = {estimator_id: [] for estimator_id in mechanism["estimators"]}
        observed_store = {estimator_id: [] for estimator_id in mechanism["estimators"]}
        skipped = {estimator_id: 0 for estimator_id in mechanism["estimators"]}
        for _ in range(iterations):
            drawn = draw_sample(rng, rows, mechanism)
            if len(drawn) < minimum:
                for estimator_id in mechanism["estimators"]:
                    skipped[estimator_id] += 1
                continue
            for estimator_id in mechanism["estimators"]:
                estimator = estimator_by_id[estimator_id]
                parameter = parameter_by_id[estimator["parameter_id"]]
                estimate_store[estimator_id].append(estimate_value(drawn, estimator, parameter))
                observed_store[estimator_id].append(len(drawn))
        for estimator_id, estimates in estimate_store.items():
            estimator = estimator_by_id[estimator_id]
            if not estimates:
                checks.append(failed(f"{mechanism_id}_{estimator_id}_simulations_available", "error", 0, "> 0 usable simulations"))
                continue
            checks.append(passed(f"{mechanism_id}_{estimator_id}_simulations_available", "error", len(estimates), "> 0 usable simulations"))
            simulation_rows.append(
                summarize_estimates(
                    mechanism_id,
                    estimator,
                    true_values[estimator["parameter_id"]],
                    estimates,
                    observed_store[estimator_id],
                    iterations,
                    bias_threshold,
                )
            )

    error_count = sum(1 for check in checks if check["severity"] == "error" and not check["valid"])
    warning_count = sum(1 for check in checks if check["severity"] == "warning" and not check["valid"])
    return {
        "valid": error_count == 0,
        "summary": {
            "simulation_rows": len(simulation_rows),
            "n_simulations": iterations,
            "seed": int(spec["seed"]),
            "eligible_population_rows": len(population_rows),
            "frame_rows": len(frame_attached_rows),
            "error_count": error_count,
            "warning_count": warning_count,
        },
        "true_parameters": {key: round_float(value) for key, value in true_values.items()},
        "simulation_rows": simulation_rows,
        "checks": checks,
    }


def write_simulation_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=CSV_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run bias/variance simulations for phase 09 estimators")
    parser.add_argument("--population", type=Path, required=True)
    parser.add_argument("--frame", type=Path, required=True)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output-csv", type=Path, required=True)
    parser.add_argument("--output-report", type=Path, required=True)
    args = parser.parse_args(argv)

    report = simulate(args.population, args.frame, args.spec)
    write_simulation_csv(args.output_csv, report["simulation_rows"])
    args.output_report.parent.mkdir(parents=True, exist_ok=True)
    args.output_report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "valid": report["valid"],
                "simulation_rows": report["summary"]["simulation_rows"],
                "error_count": report["summary"]["error_count"],
                "warning_count": report["summary"]["warning_count"],
            },
            ensure_ascii=False,
        )
    )
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
