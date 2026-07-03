from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import sklearn
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.utils.validation import check_is_fitted

REQUIRED_MANIFEST_COLUMNS = {
    "snapshot_id",
    "user_id",
    "prediction_time",
    "split",
    "split_order",
    "role",
    "assigned_by_policy",
}
REQUIRED_LABEL_COLUMNS = {
    "snapshot_id",
    "target_name",
    "label_observed_at",
    "churned_14d",
    "label_window_complete",
}
ROLE_BY_SPLIT = {
    "train": "fit_preprocessing_and_estimator",
    "validation": "model_selection_and_threshold_selection",
    "test": "final_once_only_evaluation",
}
EXPECTED_STEPS = ["preprocess", "estimator"]
GENERATED_AT = "2026-07-02T09:00:00+03:00"
TINY_TRAIN_WARNING_THRESHOLD = 20


class PipelineRunnerError(ValueError):
    """Raised when pipeline runner inputs cannot be parsed."""


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
        raise PipelineRunnerError(f"{path} must contain a JSON object")
    return value


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open(encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        return list(reader), list(reader.fieldnames or [])


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    return str(value).strip() == ""


def parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized == "true":
            return True
        if normalized == "false":
            return False
    raise PipelineRunnerError(f"expected boolean, got {value!r}")


def parse_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise PipelineRunnerError(f"expected integer, got {value!r}") from error


def parse_float(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as error:
        raise PipelineRunnerError(f"expected finite number, got {value!r}") from error
    if not math.isfinite(parsed):
        raise PipelineRunnerError(f"expected finite number, got {value!r}")
    return parsed


def rounded(value: float) -> float:
    return round(float(value), 6)


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


def feature_names(contract: dict[str, Any]) -> tuple[list[str], list[str]]:
    numeric = [
        str(item["name"])
        for item in contract.get("numeric_features", [])
        if isinstance(item, dict) and item.get("name")
    ]
    categorical = [
        str(item["name"])
        for item in contract.get("categorical_features", [])
        if isinstance(item, dict) and item.get("name")
    ]
    return numeric, categorical


def duplicate_values(values: list[str]) -> list[str]:
    return sorted(value for value, count in Counter(values).items() if count > 1)


def validate_pipeline_spec(
    *,
    problem_spec: dict[str, Any],
    preprocessing_contract: dict[str, Any],
    pipeline_spec: dict[str, Any],
) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []

    if pipeline_spec.get("problem_id") != problem_spec.get("problem_id"):
        errors.append(
            {
                "field": "problem_id",
                "observed": pipeline_spec.get("problem_id"),
                "expected": problem_spec.get("problem_id"),
            }
        )
    if pipeline_spec.get("preprocessing_contract_id") != preprocessing_contract.get("contract_id"):
        errors.append(
            {
                "field": "preprocessing_contract_id",
                "observed": pipeline_spec.get("preprocessing_contract_id"),
                "expected": preprocessing_contract.get("contract_id"),
            }
        )
    if pipeline_spec.get("fit_split") != "train":
        errors.append(
            {
                "field": "fit_split",
                "observed": pipeline_spec.get("fit_split"),
                "expected": "train",
            }
        )
    if set(pipeline_spec.get("predict_splits") or []) != {"validation", "test"}:
        errors.append(
            {
                "field": "predict_splits",
                "observed": pipeline_spec.get("predict_splits"),
                "expected": ["validation", "test"],
            }
        )
    if pipeline_spec.get("preprocessing_location") != "inside_pipeline":
        errors.append(
            {
                "field": "preprocessing_location",
                "observed": pipeline_spec.get("preprocessing_location"),
                "expected": "inside_pipeline",
            }
        )
    if pipeline_spec.get("score_type") != "churn_risk_probability":
        errors.append(
            {
                "field": "score_type",
                "observed": pipeline_spec.get("score_type"),
                "expected": "churn_risk_probability",
            }
        )

    steps = pipeline_spec.get("steps")
    step_names = [step.get("name") for step in steps] if isinstance(steps, list) else []
    if step_names != EXPECTED_STEPS:
        errors.append(
            {
                "field": "steps",
                "observed": step_names,
                "expected": EXPECTED_STEPS,
            }
        )
    else:
        preprocess_step, estimator_step = steps
        if preprocess_step.get("kind") != "contract_preprocessor":
            errors.append(
                {
                    "field": "steps.preprocess.kind",
                    "observed": preprocess_step.get("kind"),
                    "expected": "contract_preprocessor",
                }
            )
        if estimator_step.get("kind") != "logistic_regression":
            errors.append(
                {
                    "field": "steps.estimator.kind",
                    "observed": estimator_step.get("kind"),
                    "expected": "logistic_regression",
                }
            )
        params = estimator_step.get("params") if isinstance(estimator_step, dict) else {}
        if not isinstance(params, dict):
            errors.append({"field": "steps.estimator.params", "reason": "object required"})
        else:
            if params.get("solver") != "liblinear":
                errors.append(
                    {
                        "field": "steps.estimator.params.solver",
                        "observed": params.get("solver"),
                        "expected": "liblinear",
                    }
                )
            if params.get("random_state") is None:
                errors.append(
                    {
                        "field": "steps.estimator.params.random_state",
                        "reason": "fixed random_state required",
                    }
                )

    audit_policy = pipeline_spec.get("audit_policy")
    if not isinstance(audit_policy, dict):
        errors.append({"field": "audit_policy", "reason": "object required"})
    else:
        for field in (
            "require_single_pipeline_object",
            "fit_preprocessing_and_estimator_together",
            "forbid_external_preprocessed_matrix_input",
            "forbid_fit_on_validation_or_test",
        ):
            if audit_policy.get(field) is not True:
                errors.append(
                    {
                        "field": f"audit_policy.{field}",
                        "observed": audit_policy.get(field),
                        "expected": True,
                    }
                )

    output = pipeline_spec.get("output")
    if not isinstance(output, dict):
        errors.append({"field": "output", "reason": "object required"})
    else:
        for field in ("prediction_file", "report_file", "serialized_spec_file"):
            if not output.get(field):
                errors.append({"field": f"output.{field}", "reason": "required"})

    if errors:
        return failed(
            "pipeline_spec_declares_single_safe_pipeline",
            len(errors),
            "inside-pipeline preprocessing, train fit split, validation/test predictions",
            errors,
        )
    return passed(
        "pipeline_spec_declares_single_safe_pipeline",
        {
            "pipeline_id": pipeline_spec["pipeline_id"],
            "steps": step_names,
            "fit_split": pipeline_spec["fit_split"],
            "predict_splits": pipeline_spec["predict_splits"],
        },
        "single sklearn Pipeline contract",
    )


def validate_manifest(
    rows: list[dict[str, str]], columns: list[str]
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    errors: list[dict[str, Any]] = []
    missing_columns = sorted(REQUIRED_MANIFEST_COLUMNS - set(columns))
    if missing_columns:
        errors.append({"reason": "missing manifest columns", "sample": missing_columns})

    split_counts = Counter(row.get("split") for row in rows)
    for split in ("train", "validation", "test"):
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
                "split_manifest_supports_pipeline_roles",
                len(errors),
                "train fit role and validation/test prediction roles",
                errors,
            ),
            rows,
        )
    return (
        passed(
            "split_manifest_supports_pipeline_roles",
            dict(sorted(split_counts.items())),
            "manifest supports Pipeline fit and prediction boundaries",
        ),
        rows,
    )


def validate_features(
    feature_rows: list[dict[str, str]],
    feature_columns: list[str],
    manifest_rows: list[dict[str, str]],
    preprocessing_contract: dict[str, Any],
) -> dict[str, Any]:
    key = str(preprocessing_contract.get("key", "snapshot_id"))
    numeric, categorical = feature_names(preprocessing_contract)
    required_columns = {key, *numeric, *categorical}
    errors: list[dict[str, Any]] = []

    missing_columns = sorted(required_columns - set(feature_columns))
    if missing_columns:
        errors.append({"reason": "missing feature columns", "sample": missing_columns})

    forbidden_columns = sorted(
        set(preprocessing_contract.get("forbidden_columns") or []) & set(feature_columns)
    )
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
            "raw_features_cover_pipeline_population",
            len(errors),
            "one raw feature row per split manifest row and no forbidden columns",
            errors,
        )
    return passed(
        "raw_features_cover_pipeline_population",
        {"rows": len(feature_rows), "columns": sorted(required_columns)},
        "raw features match split population",
    )


def validate_labels(
    labels: list[dict[str, str]],
    columns: list[str],
    manifest_rows: list[dict[str, str]],
    problem_spec: dict[str, Any],
) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    missing_columns = sorted(REQUIRED_LABEL_COLUMNS - set(columns))
    if missing_columns:
        errors.append({"reason": "missing label columns", "sample": missing_columns})

    target = target_column(problem_spec)
    label_by_id: dict[str, dict[str, str]] = {}
    for row in labels:
        snapshot_id = row.get("snapshot_id", "")
        if snapshot_id in label_by_id:
            errors.append({"reason": "duplicate label row", "snapshot_id": snapshot_id})
        label_by_id[snapshot_id] = row

    manifest_ids = {row["snapshot_id"] for row in manifest_rows}
    missing_labels = sorted(manifest_ids - set(label_by_id))
    if missing_labels:
        errors.append({"reason": "manifest rows missing labels", "sample": missing_labels[:5]})

    for snapshot_id in sorted(manifest_ids & set(label_by_id)):
        row = label_by_id[snapshot_id]
        try:
            parse_bool(row[target])
            complete = parse_bool(row["label_window_complete"])
        except (KeyError, PipelineRunnerError) as error:
            errors.append({"snapshot_id": snapshot_id, "reason": str(error)})
            continue
        if not complete:
            errors.append({"snapshot_id": snapshot_id, "reason": "label window is incomplete"})

    if errors:
        return failed(
            "labels_support_pipeline_training_and_prediction_audit",
            len(errors),
            "complete binary labels for all split rows",
            errors,
        )
    return passed(
        "labels_support_pipeline_training_and_prediction_audit",
        {"rows": len(manifest_ids), "target": target},
        "labels are complete for training and audit",
    )


def rows_by_id(rows: list[dict[str, str]], key: str = "snapshot_id") -> dict[str, dict[str, str]]:
    return {row[key]: row for row in rows}


def ordered_manifest(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return sorted(rows, key=lambda row: (parse_int(row["split_order"]), row["snapshot_id"]))


def split_ids(manifest_rows: list[dict[str, str]], split: str) -> list[str]:
    return [row["snapshot_id"] for row in ordered_manifest(manifest_rows) if row["split"] == split]


def make_frame(
    snapshot_ids: list[str],
    feature_rows_by_id: dict[str, dict[str, str]],
    preprocessing_contract: dict[str, Any],
) -> pd.DataFrame:
    numeric, categorical = feature_names(preprocessing_contract)
    columns = numeric + categorical
    rows = [
        {column: feature_rows_by_id[snapshot_id][column] for column in columns}
        for snapshot_id in snapshot_ids
    ]
    return pd.DataFrame(rows, index=snapshot_ids, columns=columns)


def make_target(
    snapshot_ids: list[str],
    labels_by_id: dict[str, dict[str, str]],
    problem_spec: dict[str, Any],
) -> np.ndarray:
    target = target_column(problem_spec)
    return np.array(
        [int(parse_bool(labels_by_id[snapshot_id][target])) for snapshot_id in snapshot_ids]
    )


def imputation_value(feature: dict[str, Any], values: list[float]) -> float:
    impute = feature["impute"]
    strategy = impute["strategy"]
    if strategy == "constant":
        return parse_float(impute["fill_value"])
    if not values:
        raise PipelineRunnerError(f"{feature['name']} has no observed train values")
    if strategy == "median":
        return median(values)
    if strategy == "mean":
        return sum(values) / len(values)
    raise PipelineRunnerError(f"unknown imputation strategy {strategy!r}")


class ContractPreprocessor(BaseEstimator, TransformerMixin):
    """A small sklearn-compatible transformer backed by preprocessing_contract.json."""

    def __init__(self, contract: dict[str, Any]):
        self.contract = contract

    def fit(self, X: pd.DataFrame, y: Any = None) -> ContractPreprocessor:
        numeric_features, categorical_features = feature_names(self.contract)
        self.numeric_features_ = numeric_features
        self.categorical_features_ = categorical_features
        self.missing_bucket_ = str(self.contract["missing_category_bucket"])
        self.unknown_bucket_ = str(self.contract["unknown_category_bucket"])
        self.numeric_state_: dict[str, dict[str, float | str]] = {}
        self.categorical_state_: dict[str, dict[str, Any]] = {}

        for feature in self.contract["numeric_features"]:
            name = str(feature["name"])
            observed: list[float] = []
            for value in X[name].tolist():
                if is_missing(value):
                    continue
                observed.append(parse_float(value))
            fill_value = imputation_value(feature, observed)
            imputed = [
                fill_value if is_missing(value) else parse_float(value)
                for value in X[name].tolist()
            ]
            mean_value = float(np.mean(imputed))
            scale = float(np.std(imputed))
            if scale == 0.0:
                scale = 1.0
            self.numeric_state_[name] = {
                "imputation_strategy": feature["impute"]["strategy"],
                "fill_value": fill_value,
                "mean": mean_value,
                "scale": scale,
                "source_split": "train",
            }

        for feature in self.contract["categorical_features"]:
            name = str(feature["name"])
            fill_value = str(feature["impute"]["fill_value"])
            observed_train = [
                fill_value if is_missing(value) else str(value) for value in X[name].tolist()
            ]
            categories = sorted(set(observed_train))
            for special in (self.missing_bucket_, self.unknown_bucket_):
                if special not in categories:
                    categories.append(special)
            self.categorical_state_[name] = {
                "imputation_strategy": "constant",
                "fill_value": fill_value,
                "observed_train_categories": sorted(set(observed_train)),
                "encoded_categories": categories,
                "handle_unknown": feature["handle_unknown"],
                "source_split": "train",
            }

        feature_names_out = [f"num__{name}" for name in numeric_features]
        for name in categorical_features:
            for category in self.categorical_state_[name]["encoded_categories"]:
                feature_names_out.append(f"cat__{name}={category}")
        self.feature_names_out_ = np.array(feature_names_out, dtype=object)
        self.fit_row_count_ = len(X)
        return self

    def transform(self, X: pd.DataFrame) -> np.ndarray:
        check_is_fitted(self, ["numeric_state_", "categorical_state_", "feature_names_out_"])
        columns: list[np.ndarray] = []
        for name in self.numeric_features_:
            state = self.numeric_state_[name]
            values = [
                state["fill_value"] if is_missing(value) else parse_float(value)
                for value in X[name].tolist()
            ]
            transformed = (np.array(values, dtype=float) - float(state["mean"])) / float(
                state["scale"]
            )
            columns.append(transformed.reshape(-1, 1))

        for name in self.categorical_features_:
            state = self.categorical_state_[name]
            categories = state["encoded_categories"]
            values = []
            for raw_value in X[name].tolist():
                value = self.missing_bucket_ if is_missing(raw_value) else str(raw_value)
                if value not in state["observed_train_categories"] and value not in {
                    self.missing_bucket_,
                    self.unknown_bucket_,
                }:
                    value = self.unknown_bucket_
                values.append(value)
            for category in categories:
                encoded = np.array([1.0 if value == category else 0.0 for value in values])
                columns.append(encoded.reshape(-1, 1))

        if not columns:
            return np.empty((len(X), 0))
        return np.hstack(columns)

    def get_feature_names_out(self, input_features: Any = None) -> np.ndarray:
        check_is_fitted(self, ["feature_names_out_"])
        return self.feature_names_out_

    def unknown_events(self, X: pd.DataFrame, split: str) -> list[dict[str, Any]]:
        check_is_fitted(self, ["categorical_state_"])
        events: list[dict[str, Any]] = []
        for snapshot_id, row in X.iterrows():
            for name in self.categorical_features_:
                state = self.categorical_state_[name]
                raw_value = row[name]
                if is_missing(raw_value):
                    continue
                value = str(raw_value)
                if value not in state["observed_train_categories"] and value not in {
                    self.missing_bucket_,
                    self.unknown_bucket_,
                }:
                    events.append(
                        {
                            "snapshot_id": str(snapshot_id),
                            "split": split,
                            "feature": name,
                            "value": value,
                        }
                    )
        return events

    def state_for_report(self) -> dict[str, Any]:
        check_is_fitted(self, ["numeric_state_", "categorical_state_"])
        return {
            "numeric_features": {
                name: {
                    key: rounded(value) if isinstance(value, float) else value
                    for key, value in state.items()
                }
                for name, state in self.numeric_state_.items()
            },
            "categorical_features": self.categorical_state_,
            "feature_names": list(self.feature_names_out_),
            "fit_row_count": self.fit_row_count_,
        }


def estimator_params(pipeline_spec: dict[str, Any]) -> dict[str, Any]:
    estimator_step = pipeline_spec["steps"][1]
    params = dict(estimator_step["params"])
    return params


def build_pipeline(
    preprocessing_contract: dict[str, Any],
    pipeline_spec: dict[str, Any],
) -> Pipeline:
    return Pipeline(
        steps=[
            ("preprocess", ContractPreprocessor(preprocessing_contract)),
            ("estimator", LogisticRegression(**estimator_params(pipeline_spec))),
        ]
    )


def score_summary(rows: list[dict[str, Any]], split: str) -> dict[str, Any]:
    values = [float(row["score"]) for row in rows if row["split"] == split]
    if not values:
        return {"row_count": 0, "min": None, "max": None, "mean": None}
    return {
        "row_count": len(values),
        "min": rounded(min(values)),
        "max": rounded(max(values)),
        "mean": rounded(sum(values) / len(values)),
    }


def validate_prediction_rows(
    prediction_rows: list[dict[str, Any]],
    manifest_rows: list[dict[str, str]],
    pipeline_spec: dict[str, Any],
) -> dict[str, Any]:
    predict_ids = {
        row["snapshot_id"]
        for row in manifest_rows
        if row["split"] in set(pipeline_spec["predict_splits"])
    }
    observed_ids = [str(row["snapshot_id"]) for row in prediction_rows]
    errors: list[dict[str, Any]] = []
    duplicates = duplicate_values(observed_ids)
    if duplicates:
        errors.append({"reason": "duplicate prediction rows", "sample": duplicates[:5]})
    missing = sorted(predict_ids - set(observed_ids))
    extra = sorted(set(observed_ids) - predict_ids)
    if missing:
        errors.append({"reason": "prediction rows missing split rows", "sample": missing[:5]})
    if extra:
        errors.append({"reason": "prediction rows outside predict splits", "sample": extra[:5]})
    for row in prediction_rows:
        score = parse_float(row["score"])
        if score < 0 or score > 1:
            errors.append(
                {"snapshot_id": row["snapshot_id"], "field": "score", "reason": "outside [0, 1]"}
            )
        if row["trained_on_split"] != "train":
            errors.append(
                {
                    "snapshot_id": row["snapshot_id"],
                    "field": "trained_on_split",
                    "observed": row["trained_on_split"],
                    "expected": "train",
                }
            )

    if errors:
        return failed(
            "prediction_report_has_validation_and_test_scores_only",
            len(errors),
            "one probability score for every validation/test row and none for train",
            errors,
        )
    return passed(
        "prediction_report_has_validation_and_test_scores_only",
        {"rows": len(prediction_rows), "splits": pipeline_spec["predict_splits"]},
        "validation/test probability scores only",
    )


def run(
    *,
    spec_path: Path,
    preprocessing_contract_path: Path,
    pipeline_spec_path: Path,
    features_path: Path,
    labels_path: Path,
    manifest_path: Path,
    predictions_output_path: Path | None = None,
    serialized_spec_output_path: Path | None = None,
) -> dict[str, Any]:
    problem_spec = read_json(spec_path)
    preprocessing_contract = read_json(preprocessing_contract_path)
    pipeline_spec = read_json(pipeline_spec_path)
    feature_rows, feature_columns = read_csv(features_path)
    labels, label_columns = read_csv(labels_path)
    manifest_rows, manifest_columns = read_csv(manifest_path)

    checks: list[dict[str, Any]] = [
        validate_pipeline_spec(
            problem_spec=problem_spec,
            preprocessing_contract=preprocessing_contract,
            pipeline_spec=pipeline_spec,
        )
    ]
    manifest_check, manifest_rows = validate_manifest(manifest_rows, manifest_columns)
    checks.append(manifest_check)
    checks.append(
        validate_features(feature_rows, feature_columns, manifest_rows, preprocessing_contract)
    )
    checks.append(validate_labels(labels, label_columns, manifest_rows, problem_spec))

    blocking_errors = [
        check["id"] for check in checks if check["severity"] == "error" and not check["valid"]
    ]
    if blocking_errors:
        return {
            "valid": False,
            "problem_id": problem_spec.get("problem_id"),
            "summary": {
                "pipeline_id": pipeline_spec.get("pipeline_id"),
                "blocking_errors": blocking_errors,
                "warnings": [],
                "readiness_status": "blocked_before_pipeline_fit",
            },
            "checks": checks,
        }

    feature_rows_by_id = rows_by_id(feature_rows)
    labels_by_id = rows_by_id(labels)
    train_ids = split_ids(manifest_rows, "train")
    predict_splits = list(pipeline_spec["predict_splits"])

    X_train = make_frame(train_ids, feature_rows_by_id, preprocessing_contract)
    y_train = make_target(train_ids, labels_by_id, problem_spec)
    if len(set(y_train.tolist())) < 2:
        checks.append(
            failed(
                "train_split_has_both_classes_for_estimator",
                sorted(set(y_train.tolist())),
                "binary train labels",
            )
        )
        return {
            "valid": False,
            "problem_id": problem_spec.get("problem_id"),
            "summary": {
                "pipeline_id": pipeline_spec.get("pipeline_id"),
                "blocking_errors": ["train_split_has_both_classes_for_estimator"],
                "warnings": [],
                "readiness_status": "blocked_before_pipeline_fit",
            },
            "checks": checks,
        }

    pipeline = build_pipeline(preprocessing_contract, pipeline_spec)
    pipeline.fit(X_train, y_train)
    fitted_preprocessor: ContractPreprocessor = pipeline.named_steps["preprocess"]
    estimator: LogisticRegression = pipeline.named_steps["estimator"]
    feature_names_out = list(fitted_preprocessor.get_feature_names_out())
    trace: list[dict[str, Any]] = [
        {
            "event": "pipeline.fit",
            "split": "train",
            "snapshot_ids": train_ids,
            "row_count": len(train_ids),
            "fits_preprocessing": True,
            "fits_estimator": True,
        }
    ]

    prediction_rows: list[dict[str, Any]] = []
    unknown_events: list[dict[str, Any]] = []
    for split in predict_splits:
        ids = split_ids(manifest_rows, split)
        X_split = make_frame(ids, feature_rows_by_id, preprocessing_contract)
        scores = pipeline.predict_proba(X_split)[:, 1]
        unknown_events.extend(fitted_preprocessor.unknown_events(X_split, split))
        trace.append(
            {
                "event": "pipeline.predict_proba",
                "split": split,
                "snapshot_ids": ids,
                "row_count": len(ids),
                "uses_fitted_preprocessing": True,
                "fits_anything": False,
            }
        )
        for snapshot_id, score in zip(ids, scores, strict=True):
            prediction_rows.append(
                {
                    "snapshot_id": snapshot_id,
                    "pipeline_id": pipeline_spec["pipeline_id"],
                    "split": split,
                    "score": rounded(float(score)),
                    "score_type": pipeline_spec["score_type"],
                    "trained_on_split": "train",
                    "generated_at": GENERATED_AT,
                }
            )

    fit_ids = set(train_ids)
    validation_test_ids = {
        row["snapshot_id"] for row in manifest_rows if row["split"] in {"validation", "test"}
    }
    if fit_ids & validation_test_ids:
        checks.append(
            failed(
                "pipeline_fit_uses_train_only",
                sorted(fit_ids & validation_test_ids),
                "no validation/test ids in fit",
            )
        )
    else:
        checks.append(
            passed(
                "pipeline_fit_uses_train_only",
                {"fit_split": "train", "fit_snapshot_ids": train_ids},
                "Pipeline.fit used train rows only",
            )
        )

    step_names = [name for name, _step in pipeline.steps]
    if step_names != EXPECTED_STEPS:
        checks.append(
            failed(
                "pipeline_steps_are_ordered_preprocess_then_estimator",
                step_names,
                EXPECTED_STEPS,
            )
        )
    else:
        checks.append(
            passed(
                "pipeline_steps_are_ordered_preprocess_then_estimator",
                step_names,
                EXPECTED_STEPS,
            )
        )

    checks.append(validate_prediction_rows(prediction_rows, manifest_rows, pipeline_spec))

    if unknown_events:
        checks.append(
            failed(
                "pipeline_unknown_categories_bucketed",
                len(unknown_events),
                "unknown validation/test categories routed by fitted preprocessor",
                unknown_events,
                severity="warning",
            )
        )
    if len(train_ids) < TINY_TRAIN_WARNING_THRESHOLD:
        checks.append(
            failed(
                "tiny_pipeline_training_sample_expected",
                len(train_ids),
                f">= {TINY_TRAIN_WARNING_THRESHOLD} train rows for production estimator fit",
                severity="warning",
            )
        )

    serialized_spec = {
        "pipeline_id": pipeline_spec["pipeline_id"],
        "sklearn_version": sklearn.__version__,
        "steps": [
            {
                "name": "preprocess",
                "class": "ContractPreprocessor",
                "contract_id": preprocessing_contract["contract_id"],
            },
            {
                "name": "estimator",
                "class": "LogisticRegression",
                "params": estimator.get_params(),
                "classes": [int(value) for value in estimator.classes_],
                "coef_shape": list(estimator.coef_.shape),
                "intercept": [rounded(value) for value in estimator.intercept_.tolist()],
            },
        ],
        "feature_names": feature_names_out,
        "fit_trace": trace,
    }

    if predictions_output_path is not None:
        write_csv(
            predictions_output_path,
            prediction_rows,
            [
                "snapshot_id",
                "pipeline_id",
                "split",
                "score",
                "score_type",
                "trained_on_split",
                "generated_at",
            ],
        )
    if serialized_spec_output_path is not None:
        write_json(serialized_spec_output_path, serialized_spec)

    blocking_errors = [
        check["id"] for check in checks if check["severity"] == "error" and not check["valid"]
    ]
    warnings = [
        check["id"] for check in checks if check["severity"] == "warning" and not check["valid"]
    ]
    valid = not blocking_errors
    summary = {
        "pipeline_id": pipeline_spec["pipeline_id"],
        "problem_id": problem_spec["problem_id"],
        "sklearn_version": sklearn.__version__,
        "fit_split": "train",
        "fit_row_count": len(train_ids),
        "predict_splits": predict_splits,
        "prediction_row_count": len(prediction_rows),
        "transformed_feature_count": len(feature_names_out),
        "estimator": "LogisticRegression",
        "estimator_classes": [int(value) for value in estimator.classes_],
        "score_summary_by_split": {
            split: score_summary(prediction_rows, split) for split in predict_splits
        },
        "unknown_category_events": unknown_events,
        "blocking_errors": blocking_errors,
        "warnings": warnings,
        "readiness_status": "ready_for_column_transformer_lesson"
        if valid
        else "blocked_by_pipeline_audit",
    }
    return {
        "valid": valid,
        "problem_id": problem_spec["problem_id"],
        "summary": summary,
        "serialized_spec": serialized_spec,
        "preprocessing_state": fitted_preprocessor.state_for_report(),
        "predictions": prediction_rows,
        "checks": checks,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fit and audit a scikit-learn Pipeline")
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--preprocessing-contract", type=Path, required=True)
    parser.add_argument("--pipeline-spec", type=Path, required=True)
    parser.add_argument("--features", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--predictions-output", type=Path)
    parser.add_argument("--serialized-spec-output", type=Path)
    parser.add_argument("--fail-on-warning", action="store_true")
    args = parser.parse_args(argv)

    try:
        report = run(
            spec_path=args.spec,
            preprocessing_contract_path=args.preprocessing_contract,
            pipeline_spec_path=args.pipeline_spec,
            features_path=args.features,
            labels_path=args.labels,
            manifest_path=args.manifest,
            predictions_output_path=args.predictions_output,
            serialized_spec_output_path=args.serialized_spec_output,
        )
    except (OSError, json.JSONDecodeError, PipelineRunnerError, KeyError, ValueError) as error:
        report = {
            "valid": False,
            "summary": {
                "blocking_errors": ["pipeline_runner_runtime_error"],
                "warnings": [],
                "readiness_status": "runtime_error",
            },
            "checks": [
                failed(
                    "pipeline_runner_runtime_error",
                    str(error),
                    "readable JSON/CSV inputs and fit-able sklearn Pipeline",
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
