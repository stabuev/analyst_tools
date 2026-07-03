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
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
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
EXPECTED_ROUTE_NAMES = ["numeric_median", "numeric_constant", "categorical", "binary"]
GENERATED_AT = "2026-07-02T10:00:00+03:00"
TINY_TRAIN_WARNING_THRESHOLD = 20


class ColumnTransformerAuditError(ValueError):
    """Raised when ColumnTransformer auditor inputs cannot be parsed."""


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
        raise ColumnTransformerAuditError(f"{path} must contain a JSON object")
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
    raise ColumnTransformerAuditError(f"expected boolean, got {value!r}")


def parse_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise ColumnTransformerAuditError(f"expected integer, got {value!r}") from error


def parse_float(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as error:
        raise ColumnTransformerAuditError(f"expected finite number, got {value!r}") from error
    if not math.isfinite(parsed):
        raise ColumnTransformerAuditError(f"expected finite number, got {value!r}")
    return parsed


def rounded(value: float) -> float:
    return round(float(value), 6)


def duplicate_values(values: list[str]) -> list[str]:
    return sorted(value for value, count in Counter(values).items() if count > 1)


def target_column(spec: dict[str, Any]) -> str:
    target_definition = spec.get("target_definition")
    if isinstance(target_definition, dict) and target_definition.get("target_column"):
        return str(target_definition["target_column"])
    return "churned_14d"


def contract_numeric_columns(contract: dict[str, Any]) -> list[str]:
    return [
        str(item["name"])
        for item in contract.get("numeric_features", [])
        if isinstance(item, dict) and item.get("name")
    ]


def contract_categorical_columns(contract: dict[str, Any]) -> list[str]:
    return [
        str(item["name"])
        for item in contract.get("categorical_features", [])
        if isinstance(item, dict) and item.get("name")
    ]


def routes_by_name(column_transformer_spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    routes = column_transformer_spec.get("routes")
    if not isinstance(routes, list):
        return {}
    return {str(route.get("name")): route for route in routes if isinstance(route, dict)}


def route_columns(column_transformer_spec: dict[str, Any]) -> list[str]:
    columns: list[str] = []
    for route in column_transformer_spec.get("routes") or []:
        if isinstance(route, dict):
            columns.extend(str(column) for column in route.get("columns") or [])
    return columns


def route_steps(route: dict[str, Any]) -> list[str]:
    return [str(step.get("class")) for step in route.get("steps") or [] if isinstance(step, dict)]


def estimator_params(column_transformer_spec: dict[str, Any]) -> dict[str, Any]:
    estimator = column_transformer_spec["estimator"]
    return dict(estimator["params"])


def validate_column_transformer_spec(
    *,
    problem_spec: dict[str, Any],
    preprocessing_contract: dict[str, Any],
    pipeline_spec: dict[str, Any],
    column_transformer_spec: dict[str, Any],
) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []

    expected_identity = {
        "problem_id": problem_spec.get("problem_id"),
        "preprocessing_contract_id": preprocessing_contract.get("contract_id"),
        "pipeline_id": pipeline_spec.get("pipeline_id"),
    }
    for field, expected in expected_identity.items():
        if column_transformer_spec.get(field) != expected:
            errors.append(
                {
                    "field": field,
                    "observed": column_transformer_spec.get(field),
                    "expected": expected,
                }
            )

    if column_transformer_spec.get("fit_split") != "train":
        errors.append(
            {
                "field": "fit_split",
                "observed": column_transformer_spec.get("fit_split"),
                "expected": "train",
            }
        )
    if set(column_transformer_spec.get("predict_splits") or []) != {"validation", "test"}:
        errors.append(
            {
                "field": "predict_splits",
                "observed": column_transformer_spec.get("predict_splits"),
                "expected": ["validation", "test"],
            }
        )
    if column_transformer_spec.get("preprocessing_location") != "inside_pipeline":
        errors.append(
            {
                "field": "preprocessing_location",
                "observed": column_transformer_spec.get("preprocessing_location"),
                "expected": "inside_pipeline",
            }
        )
    if column_transformer_spec.get("remainder") != "drop":
        errors.append(
            {
                "field": "remainder",
                "observed": column_transformer_spec.get("remainder"),
                "expected": "drop",
            }
        )
    if column_transformer_spec.get("sparse_output") is not False:
        errors.append(
            {
                "field": "sparse_output",
                "observed": column_transformer_spec.get("sparse_output"),
                "expected": False,
            }
        )

    routes = routes_by_name(column_transformer_spec)
    if list(routes) != EXPECTED_ROUTE_NAMES:
        errors.append(
            {
                "field": "routes",
                "observed": list(routes),
                "expected": EXPECTED_ROUTE_NAMES,
            }
        )
    else:
        numeric_columns = set(contract_numeric_columns(preprocessing_contract))
        routed_numeric = set(routes["numeric_median"]["columns"]) | set(
            routes["numeric_constant"]["columns"]
        )
        if routed_numeric != numeric_columns:
            errors.append(
                {
                    "field": "routes.numeric.columns",
                    "observed": sorted(routed_numeric),
                    "expected": sorted(numeric_columns),
                }
            )
        if set(routes["categorical"]["columns"]) != set(
            contract_categorical_columns(preprocessing_contract)
        ):
            errors.append(
                {
                    "field": "routes.categorical.columns",
                    "observed": routes["categorical"].get("columns"),
                    "expected": contract_categorical_columns(preprocessing_contract),
                }
            )
        if routes["binary"].get("columns") != ["had_support_ticket_14d"]:
            errors.append(
                {
                    "field": "routes.binary.columns",
                    "observed": routes["binary"].get("columns"),
                    "expected": ["had_support_ticket_14d"],
                }
            )
        if route_steps(routes["numeric_median"]) != ["SimpleImputer", "StandardScaler"]:
            errors.append(
                {
                    "field": "routes.numeric_median.steps",
                    "observed": route_steps(routes["numeric_median"]),
                    "expected": ["SimpleImputer", "StandardScaler"],
                }
            )
        if route_steps(routes["numeric_constant"]) != ["SimpleImputer", "StandardScaler"]:
            errors.append(
                {
                    "field": "routes.numeric_constant.steps",
                    "observed": route_steps(routes["numeric_constant"]),
                    "expected": ["SimpleImputer", "StandardScaler"],
                }
            )
        if route_steps(routes["categorical"]) != ["UnknownCategoryBucketer", "OneHotEncoder"]:
            errors.append(
                {
                    "field": "routes.categorical.steps",
                    "observed": route_steps(routes["categorical"]),
                    "expected": ["UnknownCategoryBucketer", "OneHotEncoder"],
                }
            )
        if route_steps(routes["binary"]) != ["SimpleImputer"]:
            errors.append(
                {
                    "field": "routes.binary.steps",
                    "observed": route_steps(routes["binary"]),
                    "expected": ["SimpleImputer"],
                }
            )

        categorical = routes["categorical"]
        categories = categorical.get("allowed_categories")
        if not isinstance(categories, dict):
            errors.append(
                {"field": "routes.categorical.allowed_categories", "reason": "object required"}
            )
        else:
            for column in categorical.get("columns", []):
                values = categories.get(column)
                if not isinstance(values, list):
                    errors.append(
                        {
                            "field": f"routes.categorical.allowed_categories.{column}",
                            "reason": "list required",
                        }
                    )
                    continue
                for bucket in (
                    preprocessing_contract.get("missing_category_bucket"),
                    preprocessing_contract.get("unknown_category_bucket"),
                ):
                    if bucket not in values:
                        errors.append(
                            {
                                "field": f"routes.categorical.allowed_categories.{column}",
                                "observed": values,
                                "expected": f"includes {bucket}",
                            }
                        )
        categorical_steps = (
            categorical.get("steps") if isinstance(categorical.get("steps"), list) else []
        )
        one_hot = categorical_steps[1] if len(categorical_steps) > 1 else {}
        one_hot_params = one_hot.get("params") if isinstance(one_hot, dict) else {}
        if one_hot_params.get("handle_unknown") != "error":
            errors.append(
                {
                    "field": "routes.categorical.steps.one_hot.params.handle_unknown",
                    "observed": one_hot_params.get("handle_unknown"),
                    "expected": "error after explicit unknown bucketing",
                }
            )
        if one_hot_params.get("sparse_output") is not False:
            errors.append(
                {
                    "field": "routes.categorical.steps.one_hot.params.sparse_output",
                    "observed": one_hot_params.get("sparse_output"),
                    "expected": False,
                }
            )

    routed_columns = route_columns(column_transformer_spec)
    duplicates = duplicate_values(routed_columns)
    if duplicates:
        errors.append(
            {
                "field": "routes.columns",
                "reason": "columns routed more than once",
                "sample": duplicates,
            }
        )

    estimator = column_transformer_spec.get("estimator")
    if not isinstance(estimator, dict) or estimator.get("kind") != "logistic_regression":
        errors.append(
            {
                "field": "estimator.kind",
                "observed": estimator.get("kind") if isinstance(estimator, dict) else estimator,
                "expected": "logistic_regression",
            }
        )
    else:
        params = estimator.get("params") if isinstance(estimator.get("params"), dict) else {}
        if params.get("solver") != "liblinear":
            errors.append(
                {
                    "field": "estimator.params.solver",
                    "observed": params.get("solver"),
                    "expected": "liblinear",
                }
            )
        if params.get("random_state") is None:
            errors.append(
                {
                    "field": "estimator.params.random_state",
                    "reason": "fixed random_state required",
                }
            )

    audit_policy = column_transformer_spec.get("audit_policy")
    if not isinstance(audit_policy, dict):
        errors.append({"field": "audit_policy", "reason": "object required"})
    else:
        for field in (
            "require_column_transformer_inside_pipeline",
            "require_explicit_column_routes",
            "forbid_remainder_passthrough",
            "require_feature_names_out",
            "require_unknown_category_bucket",
            "forbid_dropped_required_features",
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

    output = column_transformer_spec.get("output")
    if not isinstance(output, dict):
        errors.append({"field": "output", "reason": "object required"})
    else:
        for field in (
            "routing_file",
            "feature_schema_file",
            "prediction_file",
            "report_file",
            "serialized_spec_file",
        ):
            if not output.get(field):
                errors.append({"field": f"output.{field}", "reason": "required"})

    if errors:
        return failed(
            "column_transformer_spec_declares_explicit_routes",
            len(errors),
            "explicit numeric/categorical/binary routes, drop remainder and sklearn components",
            errors,
        )
    return passed(
        "column_transformer_spec_declares_explicit_routes",
        {
            "column_transformer_id": column_transformer_spec["column_transformer_id"],
            "routes": EXPECTED_ROUTE_NAMES,
            "remainder": "drop",
        },
        "explicit ColumnTransformer routing contract",
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
                "split_manifest_supports_column_transformer_roles",
                len(errors),
                "train fit role and validation/test prediction roles",
                errors,
            ),
            rows,
        )
    return (
        passed(
            "split_manifest_supports_column_transformer_roles",
            dict(sorted(split_counts.items())),
            "manifest supports ColumnTransformer fit and prediction boundaries",
        ),
        rows,
    )


def validate_features(
    feature_rows: list[dict[str, str]],
    feature_columns: list[str],
    manifest_rows: list[dict[str, str]],
    preprocessing_contract: dict[str, Any],
    column_transformer_spec: dict[str, Any],
) -> dict[str, Any]:
    key = str(preprocessing_contract.get("key", "snapshot_id"))
    routed_columns = route_columns(column_transformer_spec)
    required_columns = {key, *routed_columns}
    errors: list[dict[str, Any]] = []

    missing_columns = sorted(required_columns - set(feature_columns))
    if missing_columns:
        errors.append({"reason": "missing feature columns", "sample": missing_columns})

    forbidden_columns = sorted(
        set(preprocessing_contract.get("forbidden_columns") or []) & set(feature_columns)
    )
    if forbidden_columns:
        errors.append({"reason": "forbidden columns present", "sample": forbidden_columns})

    unapproved_columns = sorted(set(feature_columns) - required_columns)
    if unapproved_columns:
        errors.append(
            {
                "reason": "columns would be silently dropped by ColumnTransformer",
                "sample": unapproved_columns,
            }
        )

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
            "raw_features_match_column_transformer_routes",
            len(errors),
            "one raw feature row per split row and every non-key column explicitly routed",
            errors,
        )
    return passed(
        "raw_features_match_column_transformer_routes",
        {"rows": len(feature_rows), "routed_columns": routed_columns, "dropped_columns": [key]},
        "raw features match explicit ColumnTransformer routes",
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
        except (KeyError, ColumnTransformerAuditError) as error:
            errors.append({"snapshot_id": snapshot_id, "reason": str(error)})
            continue
        if not complete:
            errors.append({"snapshot_id": snapshot_id, "reason": "label window is incomplete"})

    if errors:
        return failed(
            "labels_support_column_transformer_training_and_prediction_audit",
            len(errors),
            "complete binary labels for all split rows",
            errors,
        )
    return passed(
        "labels_support_column_transformer_training_and_prediction_audit",
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
    column_transformer_spec: dict[str, Any],
) -> pd.DataFrame:
    columns = route_columns(column_transformer_spec)
    rows = [
        {column: feature_rows_by_id[snapshot_id][column] for column in columns}
        for snapshot_id in snapshot_ids
    ]
    frame = pd.DataFrame(rows, index=snapshot_ids, columns=columns)
    routes = routes_by_name(column_transformer_spec)
    for column in routes["numeric_median"]["columns"] + routes["numeric_constant"]["columns"]:
        frame[column] = [
            np.nan if is_missing(value) else parse_float(value) for value in frame[column]
        ]
    for column in routes["binary"]["columns"]:
        frame[column] = [
            np.nan if is_missing(value) else parse_float(value) for value in frame[column]
        ]
    return frame


def make_target(
    snapshot_ids: list[str],
    labels_by_id: dict[str, dict[str, str]],
    problem_spec: dict[str, Any],
) -> np.ndarray:
    target = target_column(problem_spec)
    return np.array(
        [int(parse_bool(labels_by_id[snapshot_id][target])) for snapshot_id in snapshot_ids]
    )


class UnknownCategoryBucketer(BaseEstimator, TransformerMixin):
    """Map missing and unknown categorical values before OneHotEncoder."""

    def __init__(
        self,
        allowed_categories: dict[str, list[str]],
        *,
        missing_value: str = "__missing__",
        unknown_value: str = "__unknown__",
    ):
        self.allowed_categories = allowed_categories
        self.missing_value = missing_value
        self.unknown_value = unknown_value

    def fit(self, X: pd.DataFrame, y: Any = None) -> UnknownCategoryBucketer:
        self.feature_names_in_ = np.array(list(X.columns), dtype=object)
        self.allowed_categories_ = {
            name: list(self.allowed_categories[name]) for name in self.feature_names_in_
        }
        self.observed_train_categories_ = {}
        for name in self.feature_names_in_:
            values = [
                self.missing_value if is_missing(value) else str(value)
                for value in X[name].tolist()
            ]
            self.observed_train_categories_[str(name)] = sorted(set(values))
        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:
        check_is_fitted(self, ["feature_names_in_", "allowed_categories_"])
        rows: list[dict[str, str]] = []
        for _index, row in X.iterrows():
            output_row: dict[str, str] = {}
            for name in self.feature_names_in_:
                raw_value = row[str(name)]
                value = self.missing_value if is_missing(raw_value) else str(raw_value)
                if value not in self.allowed_categories_[str(name)]:
                    value = self.unknown_value
                output_row[str(name)] = value
            rows.append(output_row)
        return pd.DataFrame(rows, index=X.index, columns=list(self.feature_names_in_))

    def get_feature_names_out(self, input_features: Any = None) -> np.ndarray:
        check_is_fitted(self, ["feature_names_in_"])
        return self.feature_names_in_

    def unknown_events(self, X: pd.DataFrame, split: str) -> list[dict[str, Any]]:
        check_is_fitted(self, ["feature_names_in_", "allowed_categories_"])
        events: list[dict[str, Any]] = []
        for snapshot_id, row in X.iterrows():
            for name in self.feature_names_in_:
                raw_value = row[str(name)]
                if is_missing(raw_value):
                    continue
                value = str(raw_value)
                if value not in self.allowed_categories_[str(name)]:
                    events.append(
                        {
                            "snapshot_id": str(snapshot_id),
                            "split": split,
                            "feature": str(name),
                            "value": value,
                        }
                    )
        return events

    def state_for_report(self) -> dict[str, Any]:
        check_is_fitted(self, ["allowed_categories_", "observed_train_categories_"])
        return {
            "allowed_categories": self.allowed_categories_,
            "observed_train_categories": self.observed_train_categories_,
            "missing_value": self.missing_value,
            "unknown_value": self.unknown_value,
        }


def make_pipeline_from_steps(steps: list[tuple[str, Any]]) -> Pipeline:
    return Pipeline(steps=steps)


def build_column_transformer(column_transformer_spec: dict[str, Any]) -> ColumnTransformer:
    routes = routes_by_name(column_transformer_spec)
    categorical = routes["categorical"]
    categories_by_column = categorical["allowed_categories"]
    categorical_columns = list(categorical["columns"])
    categorical_pipeline = make_pipeline_from_steps(
        [
            (
                "unknown_bucket",
                UnknownCategoryBucketer(
                    allowed_categories=categories_by_column,
                    missing_value=categorical["missing_category_bucket"],
                    unknown_value=categorical["unknown_category_bucket"],
                ),
            ),
            (
                "one_hot",
                OneHotEncoder(
                    categories=[categories_by_column[column] for column in categorical_columns],
                    handle_unknown="error",
                    sparse_output=False,
                    feature_name_combiner="concat",
                ),
            ),
        ]
    )
    return ColumnTransformer(
        transformers=[
            (
                "numeric_median",
                make_pipeline_from_steps(
                    [
                        ("imputer", SimpleImputer(strategy="median")),
                        ("scaler", StandardScaler()),
                    ]
                ),
                routes["numeric_median"]["columns"],
            ),
            (
                "numeric_constant",
                make_pipeline_from_steps(
                    [
                        ("imputer", SimpleImputer(strategy="constant", fill_value=0.0)),
                        ("scaler", StandardScaler()),
                    ]
                ),
                routes["numeric_constant"]["columns"],
            ),
            ("categorical", categorical_pipeline, categorical_columns),
            (
                "binary",
                make_pipeline_from_steps(
                    [("imputer", SimpleImputer(strategy="constant", fill_value=0.0))]
                ),
                routes["binary"]["columns"],
            ),
        ],
        remainder=column_transformer_spec["remainder"],
        sparse_threshold=0.0,
        verbose_feature_names_out=True,
    )


def build_pipeline(column_transformer_spec: dict[str, Any]) -> Pipeline:
    return Pipeline(
        steps=[
            ("preprocess", build_column_transformer(column_transformer_spec)),
            ("estimator", LogisticRegression(**estimator_params(column_transformer_spec))),
        ]
    )


def fitted_route_state(preprocess: ColumnTransformer) -> dict[str, Any]:
    state: dict[str, Any] = {}
    for name, transformer, columns in preprocess.transformers_:
        if name == "remainder":
            continue
        route_state: dict[str, Any] = {"columns": list(columns)}
        if isinstance(transformer, Pipeline):
            route_state["steps"] = [step_name for step_name, _step in transformer.steps]
            if "imputer" in transformer.named_steps:
                imputer = transformer.named_steps["imputer"]
                route_state["imputer_statistics"] = [
                    rounded(value) if isinstance(value, float | np.floating) else value
                    for value in imputer.statistics_.tolist()
                ]
            if "scaler" in transformer.named_steps:
                scaler = transformer.named_steps["scaler"]
                route_state["scaler_mean"] = [rounded(value) for value in scaler.mean_.tolist()]
                route_state["scaler_scale"] = [rounded(value) for value in scaler.scale_.tolist()]
            if "unknown_bucket" in transformer.named_steps:
                bucket = transformer.named_steps["unknown_bucket"]
                route_state["unknown_bucket_state"] = bucket.state_for_report()
            if "one_hot" in transformer.named_steps:
                one_hot = transformer.named_steps["one_hot"]
                route_state["one_hot_categories"] = [
                    [str(value) for value in category_values]
                    for category_values in one_hot.categories_
                ]
        state[name] = route_state
    return state


def build_feature_schema(
    feature_names: list[str],
    column_transformer_spec: dict[str, Any],
) -> list[dict[str, Any]]:
    routes = routes_by_name(column_transformer_spec)
    expected_sources: list[dict[str, str | None]] = []
    for route_name in ("numeric_median", "numeric_constant"):
        for column in routes[route_name]["columns"]:
            expected_sources.append(
                {"source_route": route_name, "source_column": column, "source_category": None}
            )
    categorical = routes["categorical"]
    for column in categorical["columns"]:
        for category in categorical["allowed_categories"][column]:
            expected_sources.append(
                {
                    "source_route": "categorical",
                    "source_column": column,
                    "source_category": category,
                }
            )
    for column in routes["binary"]["columns"]:
        expected_sources.append(
            {"source_route": "binary", "source_column": column, "source_category": None}
        )

    rows: list[dict[str, Any]] = []
    for position, (feature_name, source) in enumerate(
        zip(feature_names, expected_sources, strict=True)
    ):
        rows.append(
            {
                "position": position,
                "feature_name": feature_name,
                "source_route": source["source_route"],
                "source_column": source["source_column"],
                "source_category": source["source_category"] or "",
            }
        )
    return rows


def build_routing_rows(
    feature_columns: list[str],
    preprocessing_contract: dict[str, Any],
    column_transformer_spec: dict[str, Any],
    feature_schema_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    key = str(preprocessing_contract.get("key", "snapshot_id"))
    rows: list[dict[str, Any]] = [
        {
            "route": "remainder",
            "kind": "key",
            "column": key,
            "action": "drop",
            "transformer": "drop",
            "output_feature_count": 0,
            "reason": "identifier_not_model_feature",
        }
    ]
    schema_counts = Counter(row["source_column"] for row in feature_schema_rows)
    for route in column_transformer_spec["routes"]:
        transformer = "|".join(route_steps(route))
        for column in route["columns"]:
            rows.append(
                {
                    "route": route["name"],
                    "kind": route["kind"],
                    "column": column,
                    "action": "transform",
                    "transformer": transformer,
                    "output_feature_count": schema_counts[column],
                    "reason": "explicit_route",
                }
            )
    routed = {row["column"] for row in rows}
    for column in feature_columns:
        if column not in routed:
            rows.append(
                {
                    "route": "remainder",
                    "kind": "unapproved",
                    "column": column,
                    "action": "drop",
                    "transformer": "drop",
                    "output_feature_count": 0,
                    "reason": "unapproved_column",
                }
            )
    return rows


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
    column_transformer_spec: dict[str, Any],
) -> dict[str, Any]:
    predict_ids = {
        row["snapshot_id"]
        for row in manifest_rows
        if row["split"] in set(column_transformer_spec["predict_splits"])
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
            "column_transformer_predictions_cover_validation_and_test_only",
            len(errors),
            "one probability score for every validation/test row and none for train",
            errors,
        )
    return passed(
        "column_transformer_predictions_cover_validation_and_test_only",
        {"rows": len(prediction_rows), "splits": column_transformer_spec["predict_splits"]},
        "validation/test probability scores only",
    )


def run(
    *,
    spec_path: Path,
    preprocessing_contract_path: Path,
    pipeline_spec_path: Path,
    column_transformer_spec_path: Path,
    features_path: Path,
    labels_path: Path,
    manifest_path: Path,
    report_output_path: Path | None = None,
    routing_output_path: Path | None = None,
    feature_schema_output_path: Path | None = None,
    predictions_output_path: Path | None = None,
    serialized_spec_output_path: Path | None = None,
) -> dict[str, Any]:
    problem_spec = read_json(spec_path)
    preprocessing_contract = read_json(preprocessing_contract_path)
    pipeline_spec = read_json(pipeline_spec_path)
    column_transformer_spec = read_json(column_transformer_spec_path)
    feature_rows, feature_columns = read_csv(features_path)
    labels, label_columns = read_csv(labels_path)
    manifest_rows, manifest_columns = read_csv(manifest_path)

    checks: list[dict[str, Any]] = [
        validate_column_transformer_spec(
            problem_spec=problem_spec,
            preprocessing_contract=preprocessing_contract,
            pipeline_spec=pipeline_spec,
            column_transformer_spec=column_transformer_spec,
        )
    ]
    manifest_check, manifest_rows = validate_manifest(manifest_rows, manifest_columns)
    checks.append(manifest_check)
    checks.append(
        validate_features(
            feature_rows,
            feature_columns,
            manifest_rows,
            preprocessing_contract,
            column_transformer_spec,
        )
    )
    checks.append(validate_labels(labels, label_columns, manifest_rows, problem_spec))

    blocking_errors = [
        check["id"] for check in checks if check["severity"] == "error" and not check["valid"]
    ]
    if blocking_errors:
        report = {
            "valid": False,
            "problem_id": problem_spec.get("problem_id"),
            "summary": {
                "column_transformer_id": column_transformer_spec.get("column_transformer_id"),
                "blocking_errors": blocking_errors,
                "warnings": [],
                "readiness_status": "blocked_before_column_transformer_fit",
            },
            "checks": checks,
        }
        if report_output_path is not None:
            write_json(report_output_path, report)
        return report

    feature_rows_by_id = rows_by_id(feature_rows)
    labels_by_id = rows_by_id(labels)
    train_ids = split_ids(manifest_rows, "train")
    predict_splits = list(column_transformer_spec["predict_splits"])

    X_train = make_frame(train_ids, feature_rows_by_id, column_transformer_spec)
    y_train = make_target(train_ids, labels_by_id, problem_spec)
    if len(set(y_train.tolist())) < 2:
        checks.append(
            failed(
                "train_split_has_both_classes_for_column_transformer_estimator",
                sorted(set(y_train.tolist())),
                "binary train labels",
            )
        )
        report = {
            "valid": False,
            "problem_id": problem_spec.get("problem_id"),
            "summary": {
                "column_transformer_id": column_transformer_spec.get("column_transformer_id"),
                "blocking_errors": [
                    "train_split_has_both_classes_for_column_transformer_estimator"
                ],
                "warnings": [],
                "readiness_status": "blocked_before_column_transformer_fit",
            },
            "checks": checks,
        }
        if report_output_path is not None:
            write_json(report_output_path, report)
        return report

    pipeline = build_pipeline(column_transformer_spec)
    pipeline.fit(X_train, y_train)
    preprocess: ColumnTransformer = pipeline.named_steps["preprocess"]
    estimator: LogisticRegression = pipeline.named_steps["estimator"]
    feature_names_out = [str(value) for value in preprocess.get_feature_names_out()]
    feature_schema_rows = build_feature_schema(feature_names_out, column_transformer_spec)
    routing_rows = build_routing_rows(
        feature_columns, preprocessing_contract, column_transformer_spec, feature_schema_rows
    )
    trace: list[dict[str, Any]] = [
        {
            "event": "pipeline.fit",
            "split": "train",
            "snapshot_ids": train_ids,
            "row_count": len(train_ids),
            "fits_column_transformer": True,
            "fits_estimator": True,
        }
    ]

    prediction_rows: list[dict[str, Any]] = []
    unknown_events: list[dict[str, Any]] = []
    categorical_pipeline: Pipeline = preprocess.named_transformers_["categorical"]
    bucket: UnknownCategoryBucketer = categorical_pipeline.named_steps["unknown_bucket"]
    for split in predict_splits:
        ids = split_ids(manifest_rows, split)
        X_split = make_frame(ids, feature_rows_by_id, column_transformer_spec)
        scores = pipeline.predict_proba(X_split)[:, 1]
        unknown_events.extend(bucket.unknown_events(X_split[bucket.feature_names_in_], split))
        trace.append(
            {
                "event": "pipeline.predict_proba",
                "split": split,
                "snapshot_ids": ids,
                "row_count": len(ids),
                "uses_fitted_column_transformer": True,
                "fits_anything": False,
            }
        )
        for snapshot_id, score in zip(ids, scores, strict=True):
            prediction_rows.append(
                {
                    "snapshot_id": snapshot_id,
                    "column_transformer_id": column_transformer_spec["column_transformer_id"],
                    "split": split,
                    "score": rounded(float(score)),
                    "score_type": column_transformer_spec["score_type"],
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
                "column_transformer_fit_uses_train_only",
                sorted(fit_ids & validation_test_ids),
                "no validation/test ids in fit",
            )
        )
    else:
        checks.append(
            passed(
                "column_transformer_fit_uses_train_only",
                {"fit_split": "train", "fit_snapshot_ids": train_ids},
                "Pipeline.fit used train rows only",
            )
        )

    transformer_names = [name for name, _transformer, _columns in preprocess.transformers_]
    if transformer_names != EXPECTED_ROUTE_NAMES:
        checks.append(
            failed(
                "column_transformer_routes_match_declared_order",
                transformer_names,
                EXPECTED_ROUTE_NAMES,
            )
        )
    else:
        checks.append(
            passed(
                "column_transformer_routes_match_declared_order",
                transformer_names,
                EXPECTED_ROUTE_NAMES,
            )
        )

    dropped_columns = [
        row["column"]
        for row in routing_rows
        if row["action"] == "drop" and row["reason"] == "identifier_not_model_feature"
    ]
    unapproved_drops = [
        row["column"] for row in routing_rows if row["reason"] == "unapproved_column"
    ]
    if unapproved_drops:
        checks.append(
            failed(
                "column_transformer_remainder_drops_only_declared_non_features",
                unapproved_drops,
                "only snapshot_id may be dropped",
            )
        )
    else:
        checks.append(
            passed(
                "column_transformer_remainder_drops_only_declared_non_features",
                dropped_columns,
                ["snapshot_id"],
            )
        )

    checks.append(validate_prediction_rows(prediction_rows, manifest_rows, column_transformer_spec))

    if unknown_events:
        checks.append(
            failed(
                "column_transformer_unknown_categories_bucketed",
                len(unknown_events),
                "unknown validation/test categories routed to explicit bucket before OneHotEncoder",
                unknown_events,
                severity="warning",
            )
        )
    if len(train_ids) < TINY_TRAIN_WARNING_THRESHOLD:
        checks.append(
            failed(
                "tiny_column_transformer_training_sample_expected",
                len(train_ids),
                f">= {TINY_TRAIN_WARNING_THRESHOLD} train rows for production estimator fit",
                severity="warning",
            )
        )

    serialized_spec = {
        "column_transformer_id": column_transformer_spec["column_transformer_id"],
        "sklearn_version": sklearn.__version__,
        "pipeline_steps": [
            {"name": "preprocess", "class": "ColumnTransformer"},
            {"name": "estimator", "class": "LogisticRegression"},
        ],
        "column_transformer": {
            "remainder": preprocess.remainder,
            "sparse_threshold": preprocess.sparse_threshold,
            "routes": [
                {
                    "name": name,
                    "columns": list(columns),
                    "class": transformer.__class__.__name__,
                }
                for name, transformer, columns in preprocess.transformers_
            ],
        },
        "route_state": fitted_route_state(preprocess),
        "estimator": {
            "class": "LogisticRegression",
            "params": estimator.get_params(),
            "classes": [int(value) for value in estimator.classes_],
            "coef_shape": list(estimator.coef_.shape),
            "intercept": [rounded(value) for value in estimator.intercept_.tolist()],
        },
        "feature_names": feature_names_out,
        "fit_trace": trace,
    }

    if routing_output_path is not None:
        write_csv(
            routing_output_path,
            routing_rows,
            [
                "route",
                "kind",
                "column",
                "action",
                "transformer",
                "output_feature_count",
                "reason",
            ],
        )
    if feature_schema_output_path is not None:
        write_csv(
            feature_schema_output_path,
            feature_schema_rows,
            ["position", "feature_name", "source_route", "source_column", "source_category"],
        )
    if predictions_output_path is not None:
        write_csv(
            predictions_output_path,
            prediction_rows,
            [
                "snapshot_id",
                "column_transformer_id",
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
        "column_transformer_id": column_transformer_spec["column_transformer_id"],
        "problem_id": problem_spec["problem_id"],
        "sklearn_version": sklearn.__version__,
        "fit_split": "train",
        "fit_row_count": len(train_ids),
        "predict_splits": predict_splits,
        "prediction_row_count": len(prediction_rows),
        "routed_input_feature_count": len(route_columns(column_transformer_spec)),
        "transformed_feature_count": len(feature_names_out),
        "route_names": EXPECTED_ROUTE_NAMES,
        "dropped_columns": dropped_columns,
        "unapproved_dropped_columns": unapproved_drops,
        "estimator": "LogisticRegression",
        "estimator_classes": [int(value) for value in estimator.classes_],
        "score_summary_by_split": {
            split: score_summary(prediction_rows, split) for split in predict_splits
        },
        "unknown_category_events": unknown_events,
        "blocking_errors": blocking_errors,
        "warnings": warnings,
        "readiness_status": "ready_for_linear_baseline_lesson"
        if valid
        else "blocked_by_column_transformer_audit",
    }
    report = {
        "valid": valid,
        "problem_id": problem_spec["problem_id"],
        "summary": summary,
        "routing": routing_rows,
        "feature_schema": feature_schema_rows,
        "serialized_spec": serialized_spec,
        "predictions": prediction_rows,
        "checks": checks,
    }
    if report_output_path is not None:
        write_json(report_output_path, report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fit and audit a scikit-learn ColumnTransformer")
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--preprocessing-contract", type=Path, required=True)
    parser.add_argument("--pipeline-spec", type=Path, required=True)
    parser.add_argument("--column-transformer-spec", type=Path, required=True)
    parser.add_argument("--features", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--routing-output", type=Path)
    parser.add_argument("--feature-schema-output", type=Path)
    parser.add_argument("--predictions-output", type=Path)
    parser.add_argument("--serialized-spec-output", type=Path)
    parser.add_argument("--fail-on-warning", action="store_true")
    args = parser.parse_args(argv)

    try:
        report = run(
            spec_path=args.spec,
            preprocessing_contract_path=args.preprocessing_contract,
            pipeline_spec_path=args.pipeline_spec,
            column_transformer_spec_path=args.column_transformer_spec,
            features_path=args.features,
            labels_path=args.labels,
            manifest_path=args.manifest,
            report_output_path=args.output,
            routing_output_path=args.routing_output,
            feature_schema_output_path=args.feature_schema_output,
            predictions_output_path=args.predictions_output,
            serialized_spec_output_path=args.serialized_spec_output,
        )
    except (
        OSError,
        json.JSONDecodeError,
        ColumnTransformerAuditError,
        KeyError,
        ValueError,
    ) as error:
        report = {
            "valid": False,
            "summary": {
                "blocking_errors": ["column_transformer_runtime_error"],
                "warnings": [],
                "readiness_status": "runtime_error",
            },
            "checks": [
                failed(
                    "column_transformer_runtime_error",
                    str(error),
                    "readable JSON/CSV inputs and fit-able sklearn ColumnTransformer Pipeline",
                )
            ],
        }
        if args.output is not None:
            write_json(args.output, report)

    if args.output is None:
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
