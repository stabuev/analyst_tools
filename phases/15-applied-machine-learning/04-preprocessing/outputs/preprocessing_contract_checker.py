from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

REQUIRED_MANIFEST_COLUMNS = {
    "snapshot_id",
    "user_id",
    "prediction_time",
    "split",
    "split_order",
    "role",
    "assigned_by_policy",
}
REQUIRED_SPLITS = {"train", "validation", "test"}
ROLE_BY_SPLIT = {
    "train": "fit_preprocessing_and_estimator",
    "validation": "model_selection_and_threshold_selection",
    "test": "final_once_only_evaluation",
}
WARNING_TINY_SAMPLE_MIN_ROWS = 20


class PreprocessingContractError(ValueError):
    """Raised when preprocessing inputs cannot be parsed."""


def passed(check_id: str, observed: Any = None, expected: Any = None) -> dict[str, Any]:
    return {
        "id": check_id,
        "severity": "error",
        "valid": True,
        "observed": observed,
        "expected": expected,
        "sample": [],
    }


def failed(
    check_id: str,
    observed: Any,
    expected: Any,
    sample: list[Any] | None = None,
    *,
    severity: str = "error",
) -> dict[str, Any]:
    return {
        "id": check_id,
        "severity": severity,
        "valid": False,
        "observed": observed,
        "expected": expected,
        "sample": sample or [],
    }


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PreprocessingContractError(f"{path} must contain a JSON object")
    return value


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open(encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        return list(reader), list(reader.fieldnames or [])


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def is_missing(value: Any) -> bool:
    return value is None or str(value).strip() == ""


def parse_float(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as error:
        raise PreprocessingContractError(f"expected finite number, got {value!r}") from error
    if not math.isfinite(parsed):
        raise PreprocessingContractError(f"expected finite number, got {value!r}")
    return parsed


def parse_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise PreprocessingContractError(f"expected integer, got {value!r}") from error


def rounded(value: float) -> float:
    return round(value, 6)


def median(values: list[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def target_column(spec: dict[str, Any]) -> str:
    target_definition = spec.get("target_definition")
    if isinstance(target_definition, dict) and target_definition.get("target_column"):
        return str(target_definition["target_column"])
    return "churned_14d"


def feature_names(contract: dict[str, Any], key: str) -> tuple[list[str], list[str]]:
    numeric = [
        str(item.get("name"))
        for item in contract.get("numeric_features", [])
        if isinstance(item, dict) and item.get("name")
    ]
    categorical = [
        str(item.get("name"))
        for item in contract.get("categorical_features", [])
        if isinstance(item, dict) and item.get("name")
    ]
    if key in numeric or key in categorical:
        raise PreprocessingContractError("key column cannot also be a feature")
    return numeric, categorical


def duplicate_values(values: list[str]) -> list[str]:
    return sorted(value for value, count in Counter(values).items() if count > 1)


def validate_problem_alignment(spec: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    if contract.get("problem_id") != spec.get("problem_id"):
        errors.append(
            {
                "field": "problem_id",
                "observed": contract.get("problem_id"),
                "expected": spec.get("problem_id"),
            }
        )
    forbidden = set(contract.get("forbidden_columns") or [])
    expected_forbidden = {target_column(spec), "label_observed_at", "score", "split", "role"}
    missing = sorted(expected_forbidden - forbidden)
    if missing:
        errors.append({"field": "forbidden_columns", "missing": missing})

    if errors:
        return failed(
            "problem_and_preprocessing_contract_align",
            len(errors),
            "contract problem_id and forbidden target/label/score columns",
            errors,
        )
    return passed(
        "problem_and_preprocessing_contract_align",
        {
            "problem_id": contract.get("problem_id"),
            "forbidden_columns": sorted(forbidden),
        },
        "contract aligned with problem spec",
    )


def validate_contract(contract: dict[str, Any]) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    key = str(contract.get("key", "snapshot_id"))

    if contract.get("fit_split") != "train":
        errors.append(
            {
                "field": "fit_split",
                "observed": contract.get("fit_split"),
                "expected": "train",
            }
        )
    transform_splits = set(contract.get("transform_splits") or [])
    if not transform_splits >= REQUIRED_SPLITS:
        errors.append(
            {
                "field": "transform_splits",
                "missing": sorted(REQUIRED_SPLITS - transform_splits),
            }
        )
    if contract.get("missing_value_policy") != "explicit_impute":
        errors.append(
            {
                "field": "missing_value_policy",
                "observed": contract.get("missing_value_policy"),
                "expected": "explicit_impute",
            }
        )
    if contract.get("unknown_category_policy") != "bucket":
        errors.append(
            {
                "field": "unknown_category_policy",
                "observed": contract.get("unknown_category_policy"),
                "expected": "bucket",
            }
        )
    if not contract.get("unknown_category_bucket"):
        errors.append({"field": "unknown_category_bucket", "reason": "non-empty string required"})
    if not contract.get("missing_category_bucket"):
        errors.append({"field": "missing_category_bucket", "reason": "non-empty string required"})

    numeric = contract.get("numeric_features")
    categorical = contract.get("categorical_features")
    if not isinstance(numeric, list) or not numeric:
        errors.append({"field": "numeric_features", "reason": "non-empty list required"})
        numeric = []
    if not isinstance(categorical, list) or not categorical:
        errors.append({"field": "categorical_features", "reason": "non-empty list required"})
        categorical = []

    numeric_names, categorical_names = feature_names(contract, key)
    duplicates = duplicate_values(numeric_names + categorical_names)
    if duplicates:
        errors.append(
            {"field": "features", "reason": "duplicate feature names", "sample": duplicates}
        )

    for item in numeric:
        if not isinstance(item, dict):
            errors.append({"field": "numeric_features", "reason": "objects required"})
            continue
        name = item.get("name")
        impute = item.get("impute")
        if not name:
            errors.append({"field": "numeric_features.name", "reason": "required"})
        if not isinstance(impute, dict) or impute.get("strategy") not in {
            "median",
            "mean",
            "constant",
        }:
            errors.append(
                {
                    "field": f"numeric_features.{name}.impute",
                    "observed": impute,
                    "expected": "median, mean or constant strategy",
                }
            )
        elif impute.get("strategy") == "constant":
            try:
                parse_float(impute.get("fill_value"))
            except PreprocessingContractError as error:
                errors.append(
                    {
                        "field": f"numeric_features.{name}.impute.fill_value",
                        "reason": str(error),
                    }
                )
        if item.get("scale") != "standard":
            errors.append(
                {
                    "field": f"numeric_features.{name}.scale",
                    "observed": item.get("scale"),
                    "expected": "standard",
                }
            )

    for item in categorical:
        if not isinstance(item, dict):
            errors.append({"field": "categorical_features", "reason": "objects required"})
            continue
        name = item.get("name")
        impute = item.get("impute")
        if not name:
            errors.append({"field": "categorical_features.name", "reason": "required"})
        if not isinstance(impute, dict) or impute.get("strategy") != "constant":
            errors.append(
                {
                    "field": f"categorical_features.{name}.impute",
                    "observed": impute,
                    "expected": "constant imputation",
                }
            )
        elif is_missing(impute.get("fill_value")):
            errors.append(
                {
                    "field": f"categorical_features.{name}.impute.fill_value",
                    "reason": "non-empty categorical fill value required",
                }
            )
        if item.get("encode") != "one_hot":
            errors.append(
                {
                    "field": f"categorical_features.{name}.encode",
                    "observed": item.get("encode"),
                    "expected": "one_hot",
                }
            )
        if item.get("handle_unknown") != "use_unknown_bucket":
            errors.append(
                {
                    "field": f"categorical_features.{name}.handle_unknown",
                    "observed": item.get("handle_unknown"),
                    "expected": "use_unknown_bucket",
                }
            )

    output = contract.get("output")
    if not isinstance(output, dict):
        errors.append({"field": "output", "reason": "object required"})
    else:
        if not output.get("matrix_file"):
            errors.append({"field": "output.matrix_file", "reason": "required"})
        if not output.get("state_file"):
            errors.append({"field": "output.state_file", "reason": "required"})

    if errors:
        return failed(
            "preprocessing_contract_is_explicit",
            len(errors),
            "train fit split, explicit imputation, unknown bucket and output files",
            errors,
        )
    return passed(
        "preprocessing_contract_is_explicit",
        {
            "fit_split": contract["fit_split"],
            "numeric_features": numeric_names,
            "categorical_features": categorical_names,
        },
        "explicit train-fitted preprocessing contract",
    )


def validate_manifest(
    rows: list[dict[str, str]], columns: list[str]
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    errors: list[dict[str, Any]] = []
    missing_columns = sorted(REQUIRED_MANIFEST_COLUMNS - set(columns))
    if missing_columns:
        errors.append({"reason": "missing manifest columns", "sample": missing_columns})

    split_counts = Counter(row.get("split") for row in rows)
    for split in REQUIRED_SPLITS:
        if split_counts[split] == 0:
            errors.append({"reason": "missing required split", "split": split})
    for row in rows:
        split = row.get("split")
        if split in ROLE_BY_SPLIT and row.get("role") != ROLE_BY_SPLIT[split]:
            errors.append(
                {
                    "snapshot_id": row.get("snapshot_id"),
                    "field": "role",
                    "observed": row.get("role"),
                    "expected": ROLE_BY_SPLIT[split],
                }
            )

    if errors:
        return (
            failed(
                "split_manifest_supports_preprocessing_roles",
                len(errors),
                "train/validation/test roles with train as fit split",
                errors,
            ),
            rows,
        )
    return (
        passed(
            "split_manifest_supports_preprocessing_roles",
            dict(sorted(split_counts.items())),
            "manifest has train fit and validation/test transform roles",
        ),
        rows,
    )


def validate_feature_population(
    feature_rows: list[dict[str, str]],
    feature_columns: list[str],
    manifest_rows: list[dict[str, str]],
    contract: dict[str, Any],
) -> dict[str, Any]:
    key = str(contract.get("key", "snapshot_id"))
    numeric, categorical = feature_names(contract, key)
    required_columns = {key, *numeric, *categorical}
    errors: list[dict[str, Any]] = []

    missing_columns = sorted(required_columns - set(feature_columns))
    if missing_columns:
        errors.append({"reason": "missing feature columns", "sample": missing_columns})

    forbidden_columns = sorted(set(contract.get("forbidden_columns") or []) & set(feature_columns))
    if forbidden_columns:
        errors.append({"reason": "forbidden columns present", "sample": forbidden_columns})

    row_keys = [row.get(key, "") for row in feature_rows]
    duplicates = duplicate_values(row_keys)
    if duplicates:
        errors.append({"reason": "duplicate feature rows", "sample": duplicates[:5]})

    manifest_ids = {row["snapshot_id"] for row in manifest_rows}
    feature_ids = set(row_keys)
    missing_rows = sorted(manifest_ids - feature_ids)
    extra_rows = sorted(feature_ids - manifest_ids)
    if missing_rows:
        errors.append({"reason": "manifest rows missing features", "sample": missing_rows[:5]})
    if extra_rows:
        errors.append({"reason": "feature rows outside split manifest", "sample": extra_rows[:5]})

    if errors:
        return failed(
            "raw_feature_schema_and_population_match_manifest",
            len(errors),
            "one feature row per split manifest row and no forbidden columns",
            errors,
        )
    return passed(
        "raw_feature_schema_and_population_match_manifest",
        {"rows": len(feature_rows), "columns": sorted(required_columns)},
        "feature table exactly matches eligible split population",
    )


def imputation_value(feature: dict[str, Any], values: list[float]) -> float:
    impute = feature["impute"]
    strategy = impute["strategy"]
    if strategy == "constant":
        return parse_float(impute["fill_value"])
    if not values:
        raise PreprocessingContractError(f"{feature['name']} has no observed train values")
    if strategy == "median":
        return median(values)
    if strategy == "mean":
        return sum(values) / len(values)
    raise PreprocessingContractError(f"unknown imputation strategy {strategy!r}")


def fit_numeric_state(
    feature_rows_by_id: dict[str, dict[str, str]],
    train_ids: list[str],
    numeric_features: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, int]]:
    state: dict[str, Any] = {}
    errors: list[dict[str, Any]] = []
    missing_counts: dict[str, int] = {}

    for feature in numeric_features:
        name = str(feature["name"])
        observed: list[float] = []
        missing_count = 0
        for snapshot_id in train_ids:
            raw_value = feature_rows_by_id[snapshot_id].get(name)
            if is_missing(raw_value):
                missing_count += 1
                continue
            try:
                observed.append(parse_float(raw_value))
            except PreprocessingContractError as error:
                errors.append({"snapshot_id": snapshot_id, "feature": name, "reason": str(error)})
        try:
            fill_value = imputation_value(feature, observed)
        except PreprocessingContractError as error:
            errors.append({"feature": name, "reason": str(error)})
            fill_value = 0.0

        imputed_train = [
            fill_value
            if is_missing(feature_rows_by_id[snapshot_id].get(name))
            else parse_float(feature_rows_by_id[snapshot_id][name])
            for snapshot_id in train_ids
        ]
        mean_value = sum(imputed_train) / len(imputed_train)
        variance = sum((value - mean_value) ** 2 for value in imputed_train) / len(imputed_train)
        scale = math.sqrt(variance)
        if scale == 0:
            scale = 1.0
        state[name] = {
            "imputation_strategy": feature["impute"]["strategy"],
            "fill_value": rounded(fill_value),
            "mean": rounded(mean_value),
            "scale": rounded(scale),
            "source_split": "train",
        }
        missing_counts[name] = missing_count

    return state, errors, missing_counts


def fit_categorical_state(
    feature_rows_by_id: dict[str, dict[str, str]],
    train_ids: list[str],
    categorical_features: list[dict[str, Any]],
    missing_bucket: str,
    unknown_bucket: str,
) -> tuple[dict[str, Any], dict[str, int]]:
    state: dict[str, Any] = {}
    missing_counts: dict[str, int] = {}

    for feature in categorical_features:
        name = str(feature["name"])
        fill_value = str(feature["impute"]["fill_value"])
        observed_train: list[str] = []
        missing_count = 0
        for snapshot_id in train_ids:
            raw_value = feature_rows_by_id[snapshot_id].get(name)
            if is_missing(raw_value):
                missing_count += 1
                observed_train.append(fill_value)
            else:
                observed_train.append(str(raw_value))
        categories = sorted(set(observed_train))
        for special in (missing_bucket, unknown_bucket):
            if special not in categories:
                categories.append(special)
        state[name] = {
            "imputation_strategy": "constant",
            "fill_value": fill_value,
            "observed_train_categories": sorted(set(observed_train)),
            "encoded_categories": categories,
            "handle_unknown": feature["handle_unknown"],
            "source_split": "train",
        }
        missing_counts[name] = missing_count

    return state, missing_counts


def transform_rows(
    feature_rows_by_id: dict[str, dict[str, str]],
    manifest_rows: list[dict[str, str]],
    numeric_state: dict[str, Any],
    categorical_state: dict[str, Any],
    contract: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]], dict[str, int]]:
    numeric_features = [item["name"] for item in contract["numeric_features"]]
    categorical_features = [item["name"] for item in contract["categorical_features"]]
    unknown_policy = contract.get("unknown_category_policy")
    unknown_bucket = str(contract["unknown_category_bucket"])
    missing_bucket = str(contract["missing_category_bucket"])
    feature_order = [f"num__{name}" for name in numeric_features]
    for name in categorical_features:
        for category in categorical_state[name]["encoded_categories"]:
            feature_order.append(f"cat__{name}={category}")

    transformed: list[dict[str, Any]] = []
    unknown_events: list[dict[str, Any]] = []
    missing_counts: dict[str, int] = defaultdict(int)

    ordered_manifest = sorted(
        manifest_rows,
        key=lambda row: (parse_int(row["split_order"]), row["snapshot_id"]),
    )
    for manifest_row in ordered_manifest:
        snapshot_id = manifest_row["snapshot_id"]
        raw = feature_rows_by_id[snapshot_id]
        output: dict[str, Any] = {"snapshot_id": snapshot_id, "split": manifest_row["split"]}

        for name in numeric_features:
            state = numeric_state[name]
            raw_value = raw.get(name)
            if is_missing(raw_value):
                missing_counts[name] += 1
                value = state["fill_value"]
            else:
                value = parse_float(raw_value)
            output[f"num__{name}"] = rounded((value - state["mean"]) / state["scale"])

        for name in categorical_features:
            state = categorical_state[name]
            raw_value = raw.get(name)
            if is_missing(raw_value):
                missing_counts[name] += 1
                value = missing_bucket
            else:
                value = str(raw_value)
            if value not in state["observed_train_categories"] and value not in {
                missing_bucket,
                unknown_bucket,
            }:
                unknown_events.append(
                    {
                        "snapshot_id": snapshot_id,
                        "split": manifest_row["split"],
                        "feature": name,
                        "value": value,
                    }
                )
                if unknown_policy == "bucket" and state["handle_unknown"] == "use_unknown_bucket":
                    value = unknown_bucket
            for category in state["encoded_categories"]:
                output[f"cat__{name}={category}"] = 1.0 if value == category else 0.0

        transformed.append(output)

    return transformed, feature_order, unknown_events, dict(missing_counts)


def transformed_matrix_check(
    matrix_rows: list[dict[str, Any]], feature_order: list[str]
) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    expected_columns = {"snapshot_id", "split", *feature_order}
    for row in matrix_rows:
        missing_columns = sorted(expected_columns - set(row))
        if missing_columns:
            errors.append(
                {
                    "snapshot_id": row.get("snapshot_id"),
                    "reason": "missing transformed columns",
                    "sample": missing_columns[:5],
                }
            )
        for name in feature_order:
            value = row.get(name)
            if (
                value is None
                or not isinstance(value, int | float)
                or not math.isfinite(float(value))
            ):
                errors.append(
                    {
                        "snapshot_id": row.get("snapshot_id"),
                        "feature": name,
                        "reason": "non-numeric transformed value",
                        "value": value,
                    }
                )

    if errors:
        return failed(
            "transformed_matrix_is_numeric_and_stable",
            len(errors),
            "all transformed feature columns are numeric and stable",
            errors[:10],
        )
    return passed(
        "transformed_matrix_is_numeric_and_stable",
        {"rows": len(matrix_rows), "features": len(feature_order)},
        "numeric transformed matrix with stable feature names",
    )


def run(
    *,
    spec_path: Path,
    contract_path: Path,
    features_path: Path,
    manifest_path: Path,
    matrix_output_path: Path | None = None,
    state_output_path: Path | None = None,
) -> dict[str, Any]:
    spec = read_json(spec_path)
    contract = read_json(contract_path)
    feature_rows, feature_columns = read_csv(features_path)
    manifest_rows, manifest_columns = read_csv(manifest_path)

    checks: list[dict[str, Any]] = [
        validate_problem_alignment(spec, contract),
        validate_contract(contract),
    ]
    manifest_check, manifest_rows = validate_manifest(manifest_rows, manifest_columns)
    checks.append(manifest_check)
    checks.append(
        validate_feature_population(feature_rows, feature_columns, manifest_rows, contract)
    )

    blocking_errors = [
        check["id"] for check in checks if check["severity"] == "error" and not check["valid"]
    ]
    if blocking_errors:
        summary = {
            "contract_id": contract.get("contract_id"),
            "fit_split": contract.get("fit_split"),
            "blocking_errors": blocking_errors,
            "warnings": [],
            "readiness_status": "blocked_before_preprocessing_fit",
        }
        return {
            "valid": False,
            "problem_id": spec.get("problem_id"),
            "summary": summary,
            "checks": checks,
        }

    key = str(contract.get("key", "snapshot_id"))
    feature_rows_by_id = {row[key]: row for row in feature_rows}
    train_ids = [
        row["snapshot_id"]
        for row in sorted(manifest_rows, key=lambda row: row["snapshot_id"])
        if row["split"] == "train"
    ]
    train_split_ids = {row["snapshot_id"] for row in manifest_rows if row["split"] == "train"}
    validation_or_test_ids = {
        row["snapshot_id"] for row in manifest_rows if row["split"] in {"validation", "test"}
    }
    if set(train_ids) != train_split_ids or set(train_ids) & validation_or_test_ids:
        checks.append(
            failed(
                "preprocessing_state_is_fit_on_train_only",
                {"fit_ids": train_ids},
                "fit ids must be train split only",
            )
        )
    else:
        checks.append(
            passed(
                "preprocessing_state_is_fit_on_train_only",
                {"fit_split": "train", "fit_snapshot_ids": train_ids},
                "only train rows used by fit",
            )
        )

    numeric_state, numeric_errors, numeric_train_missing = fit_numeric_state(
        feature_rows_by_id,
        train_ids,
        contract["numeric_features"],
    )
    categorical_state, categorical_train_missing = fit_categorical_state(
        feature_rows_by_id,
        train_ids,
        contract["categorical_features"],
        str(contract["missing_category_bucket"]),
        str(contract["unknown_category_bucket"]),
    )
    if numeric_errors:
        checks.append(
            failed(
                "missing_values_have_explicit_imputation",
                len(numeric_errors),
                "numeric values parse and all missing values have imputation",
                numeric_errors,
            )
        )
    else:
        checks.append(
            passed(
                "missing_values_have_explicit_imputation",
                {
                    "numeric_train_missing": numeric_train_missing,
                    "categorical_train_missing": categorical_train_missing,
                },
                "train-fitted imputation values are explicit",
            )
        )

    matrix_rows, feature_order, unknown_events, all_missing_counts = transform_rows(
        feature_rows_by_id,
        manifest_rows,
        numeric_state,
        categorical_state,
        contract,
    )

    if unknown_events and (
        contract.get("unknown_category_policy") != "bucket"
        or any(
            item.get("handle_unknown") != "use_unknown_bucket"
            for item in contract["categorical_features"]
        )
    ):
        checks.append(
            failed(
                "unknown_categories_have_explicit_policy",
                len(unknown_events),
                "unknown categories must be bucketed or blocked explicitly",
                unknown_events[:10],
            )
        )
    elif unknown_events:
        checks.append(
            failed(
                "unknown_categories_bucketed",
                len(unknown_events),
                "unknown validation/test categories are routed to __unknown__ bucket",
                unknown_events[:10],
                severity="warning",
            )
        )
        checks.append(
            passed(
                "unknown_categories_have_explicit_policy",
                {"bucketed_events": len(unknown_events)},
                "unknown categories are not silently ignored",
            )
        )
    else:
        checks.append(
            passed(
                "unknown_categories_have_explicit_policy",
                {"bucketed_events": 0},
                "no unknown categories outside train",
            )
        )

    checks.append(transformed_matrix_check(matrix_rows, feature_order))

    if len(train_ids) < WARNING_TINY_SAMPLE_MIN_ROWS:
        checks.append(
            failed(
                "tiny_preprocessing_sample_expected",
                len(train_ids),
                f">= {WARNING_TINY_SAMPLE_MIN_ROWS} train rows for production preprocessing stats",
                severity="warning",
            )
        )

    preprocessing_state = {
        "contract_id": contract["contract_id"],
        "problem_id": contract["problem_id"],
        "fit_split": "train",
        "fit_snapshot_ids": train_ids,
        "numeric_features": numeric_state,
        "categorical_features": categorical_state,
        "feature_names": feature_order,
    }

    if matrix_output_path is not None:
        write_csv(matrix_output_path, matrix_rows, ["snapshot_id", "split", *feature_order])
    if state_output_path is not None:
        write_json(state_output_path, preprocessing_state)

    blocking_errors = [
        check["id"] for check in checks if check["severity"] == "error" and not check["valid"]
    ]
    warnings = [
        check["id"] for check in checks if check["severity"] == "warning" and not check["valid"]
    ]
    valid = not blocking_errors
    summary = {
        "contract_id": contract["contract_id"],
        "problem_id": contract["problem_id"],
        "fit_split": "train",
        "fit_row_count": len(train_ids),
        "transformed_row_count": len(matrix_rows),
        "transformed_feature_count": len(feature_order),
        "numeric_feature_count": len(contract["numeric_features"]),
        "categorical_feature_count": len(contract["categorical_features"]),
        "missing_value_counts": all_missing_counts,
        "unknown_category_events": unknown_events,
        "feature_names": feature_order,
        "blocking_errors": blocking_errors,
        "warnings": warnings,
        "readiness_status": "ready_for_pipeline_lesson"
        if valid
        else "blocked_by_preprocessing_audit",
    }
    return {
        "valid": valid,
        "problem_id": spec.get("problem_id"),
        "summary": summary,
        "preprocessing_state": preprocessing_state,
        "transformed_matrix_preview": matrix_rows[:5],
        "checks": checks,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check train-fitted preprocessing contract")
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--features", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--matrix-output", type=Path)
    parser.add_argument("--state-output", type=Path)
    parser.add_argument("--fail-on-warning", action="store_true")
    args = parser.parse_args(argv)

    try:
        report = run(
            spec_path=args.spec,
            contract_path=args.contract,
            features_path=args.features,
            manifest_path=args.manifest,
            matrix_output_path=args.matrix_output,
            state_output_path=args.state_output,
        )
    except (OSError, json.JSONDecodeError, PreprocessingContractError) as error:
        report = {
            "valid": False,
            "summary": {
                "blocking_errors": ["preprocessing_contract_checker_runtime_error"],
                "warnings": [],
                "readiness_status": "runtime_error",
            },
            "checks": [
                failed(
                    "preprocessing_contract_checker_runtime_error",
                    str(error),
                    "readable JSON/CSV inputs",
                )
            ],
        }

    if args.output is not None:
        write_json(args.output, report)
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))

    has_errors = any(
        check["severity"] == "error" and not check["valid"] for check in report["checks"]
    )
    has_warnings = any(
        check["severity"] == "warning" and not check["valid"] for check in report["checks"]
    )
    if has_errors or (args.fail_on_warning and has_warnings):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
