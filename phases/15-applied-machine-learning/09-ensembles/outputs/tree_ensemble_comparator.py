from __future__ import annotations

# ruff: noqa: E402, I001

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import sklearn
from sklearn.ensemble import RandomForestClassifier
from sklearn.inspection import permutation_importance
from sklearn.pipeline import Pipeline

TREE_OUTPUT_ROOT = Path(__file__).resolve().parents[2] / "08-trees" / "outputs"
LINEAR_OUTPUT_ROOT = Path(__file__).resolve().parents[2] / "07-linear-models" / "outputs"
COLUMN_OUTPUT_ROOT = Path(__file__).resolve().parents[2] / "06-column-transformer" / "outputs"
for output_root in (TREE_OUTPUT_ROOT, LINEAR_OUTPUT_ROOT, COLUMN_OUTPUT_ROOT):
    if str(output_root) not in sys.path:
        sys.path.insert(0, str(output_root))

from column_transformer_auditor import (  # noqa: E402
    ColumnTransformerAuditError,
    build_column_transformer,
    build_feature_schema,
    failed,
    make_frame,
    make_target,
    passed,
    read_csv,
    read_json,
    rounded,
    rows_by_id,
    split_ids,
    write_json,
)
from linear_baseline_trainer import (  # noqa: E402
    LinearBaselineError,
    cost_weights,
    prediction_rows_for_split,
    run as run_linear_baseline_audit,
    selected_ids_at_budget,
    selection_budget,
    split_metric_row,
)
from tree_diagnostic_trainer import (  # noqa: E402
    TreeDiagnosticError,
    run as run_tree_diagnostic_audit,
)

REQUIRED_MANIFEST_COLUMNS = {
    "snapshot_id",
    "user_id",
    "prediction_time",
    "split",
    "split_order",
    "role",
    "assigned_by_policy",
}
ROLE_BY_SPLIT = {
    "train": "fit_preprocessing_and_estimator",
    "validation": "model_selection_and_threshold_selection",
    "test": "final_once_only_evaluation",
}
GENERATED_AT = "2026-07-02T13:00:00+03:00"
TINY_TRAIN_WARNING_THRESHOLD = 20


class TreeEnsembleError(ValueError):
    """Raised when tree ensemble comparator inputs cannot be parsed."""


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_ready(item) for item in value]
    if isinstance(value, tuple):
        return [json_ready(item) for item in value]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def validate_tree_ensemble_spec(
    *,
    problem_spec: dict[str, Any],
    pipeline_spec: dict[str, Any],
    column_transformer_spec: dict[str, Any],
    linear_baseline_spec: dict[str, Any],
    tree_diagnostic_spec: dict[str, Any],
    tree_ensemble_spec: dict[str, Any],
) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    expected_identity = {
        "problem_id": problem_spec.get("problem_id"),
        "pipeline_id": pipeline_spec.get("pipeline_id"),
        "column_transformer_id": column_transformer_spec.get("column_transformer_id"),
        "linear_baseline_id": linear_baseline_spec.get("linear_baseline_id"),
        "tree_diagnostic_id": tree_diagnostic_spec.get("tree_diagnostic_id"),
    }
    for field, expected in expected_identity.items():
        if tree_ensemble_spec.get(field) != expected:
            errors.append(
                {"field": field, "observed": tree_ensemble_spec.get(field), "expected": expected}
            )

    expected_splits = {
        "fit_split": "train",
        "selection_split": "validation",
        "stability_split": "validation",
        "final_holdout_split": "test",
        "ensemble_role": "candidate_tree_ensemble_not_production_promotion",
    }
    for field, expected in expected_splits.items():
        if tree_ensemble_spec.get(field) != expected:
            errors.append(
                {"field": field, "observed": tree_ensemble_spec.get(field), "expected": expected}
            )
    if tree_ensemble_spec.get("score_type") != column_transformer_spec.get("score_type"):
        errors.append(
            {
                "field": "score_type",
                "observed": tree_ensemble_spec.get("score_type"),
                "expected": column_transformer_spec.get("score_type"),
            }
        )

    comparison = tree_ensemble_spec.get("comparison")
    if not isinstance(comparison, dict):
        errors.append({"field": "comparison", "reason": "object required"})
    else:
        if comparison.get("primary_metric") != "precision_at_budget":
            errors.append(
                {
                    "field": "comparison.primary_metric",
                    "observed": comparison.get("primary_metric"),
                    "expected": "precision_at_budget",
                }
            )
        if comparison.get("selection_data") != "validation":
            errors.append(
                {
                    "field": "comparison.selection_data",
                    "observed": comparison.get("selection_data"),
                    "expected": "validation",
                }
            )
        if comparison.get("test_data_role") != "final_once_only_evaluation":
            errors.append(
                {
                    "field": "comparison.test_data_role",
                    "observed": comparison.get("test_data_role"),
                    "expected": "final_once_only_evaluation",
                }
            )

    candidate = tree_ensemble_spec.get("candidate")
    if not isinstance(candidate, dict) or candidate.get("kind") != "random_forest_classifier":
        errors.append(
            {
                "field": "candidate.kind",
                "observed": candidate.get("kind") if isinstance(candidate, dict) else candidate,
                "expected": "random_forest_classifier",
            }
        )
    else:
        params = candidate.get("params") if isinstance(candidate.get("params"), dict) else {}
        n_estimators = params.get("n_estimators")
        if not isinstance(n_estimators, int) or n_estimators < 2:
            errors.append(
                {
                    "field": "candidate.params.n_estimators",
                    "observed": n_estimators,
                    "expected": "integer >= 2",
                }
            )
        max_depth = params.get("max_depth")
        if not isinstance(max_depth, int) or max_depth < 1 or max_depth > 4:
            errors.append(
                {
                    "field": "candidate.params.max_depth",
                    "observed": max_depth,
                    "expected": "integer between 1 and 4 for small ensemble lesson",
                }
            )
        min_samples_leaf = params.get("min_samples_leaf")
        if not isinstance(min_samples_leaf, int) or min_samples_leaf < 1:
            errors.append(
                {
                    "field": "candidate.params.min_samples_leaf",
                    "observed": min_samples_leaf,
                    "expected": "integer >= 1",
                }
            )
        if params.get("random_state") is None:
            errors.append({"field": "candidate.params.random_state", "reason": "required"})
        if params.get("n_jobs") != 1:
            errors.append(
                {
                    "field": "candidate.params.n_jobs",
                    "observed": params.get("n_jobs"),
                    "expected": 1,
                }
            )

    stability = tree_ensemble_spec.get("stability_policy")
    if not isinstance(stability, dict):
        errors.append({"field": "stability_policy", "reason": "object required"})
    else:
        seeds = stability.get("seeds")
        if not isinstance(seeds, list) or len(seeds) < 3 or not all(
            isinstance(seed, int) for seed in seeds
        ):
            errors.append(
                {
                    "field": "stability_policy.seeds",
                    "observed": seeds,
                    "expected": "at least three integer seeds",
                }
            )
        if stability.get("metric") != "precision_at_budget":
            errors.append(
                {
                    "field": "stability_policy.metric",
                    "observed": stability.get("metric"),
                    "expected": "precision_at_budget",
                }
            )
        if stability.get("split") != "validation":
            errors.append(
                {
                    "field": "stability_policy.split",
                    "observed": stability.get("split"),
                    "expected": "validation",
                }
            )
        if stability.get("max_allowed_range") is None:
            errors.append({"field": "stability_policy.max_allowed_range", "reason": "required"})

    importance = tree_ensemble_spec.get("feature_importance_policy")
    if not isinstance(importance, dict):
        errors.append({"field": "feature_importance_policy", "reason": "object required"})
    else:
        methods = importance.get("methods")
        if not isinstance(methods, list) or set(methods) != {"mdi", "permutation"}:
            errors.append(
                {
                    "field": "feature_importance_policy.methods",
                    "observed": methods,
                    "expected": ["mdi", "permutation"],
                }
            )
        if importance.get("permutation_split") != "validation":
            errors.append(
                {
                    "field": "feature_importance_policy.permutation_split",
                    "observed": importance.get("permutation_split"),
                    "expected": "validation",
                }
            )
        if not isinstance(importance.get("permutation_repeats"), int) or (
            importance.get("permutation_repeats") < 2
        ):
            errors.append(
                {
                    "field": "feature_importance_policy.permutation_repeats",
                    "observed": importance.get("permutation_repeats"),
                    "expected": "integer >= 2",
                }
            )
        if not isinstance(importance.get("warnings"), list) or len(importance["warnings"]) < 3:
            errors.append(
                {
                    "field": "feature_importance_policy.warnings",
                    "observed": importance.get("warnings"),
                    "expected": "at least three interpretation warnings",
                }
            )

    slice_policy = tree_ensemble_spec.get("slice_policy")
    if not isinstance(slice_policy, dict):
        errors.append({"field": "slice_policy", "reason": "object required"})
    else:
        if not isinstance(slice_policy.get("slices"), list) or not slice_policy["slices"]:
            errors.append({"field": "slice_policy.slices", "reason": "non-empty list required"})
        if slice_policy.get("split") != "validation":
            errors.append(
                {
                    "field": "slice_policy.split",
                    "observed": slice_policy.get("split"),
                    "expected": "validation",
                }
            )
        if not isinstance(slice_policy.get("min_rows_for_reliable_slice"), int):
            errors.append(
                {
                    "field": "slice_policy.min_rows_for_reliable_slice",
                    "reason": "integer required",
                }
            )

    audit_policy = tree_ensemble_spec.get("audit_policy")
    if not isinstance(audit_policy, dict):
        errors.append({"field": "audit_policy", "reason": "object required"})
    else:
        for field in (
            "require_tree_diagnostic_handoff",
            "require_validation_only_selection",
            "forbid_test_selection",
            "require_random_state",
            "require_stability_report",
            "require_feature_importance_warning",
            "require_slice_metrics",
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

    output = tree_ensemble_spec.get("output")
    if not isinstance(output, dict):
        errors.append({"field": "output", "reason": "object required"})
    else:
        for field in (
            "comparison_file",
            "stability_file",
            "feature_importance_file",
            "slice_metrics_file",
            "prediction_file",
            "report_file",
            "serialized_spec_file",
        ):
            if not output.get(field):
                errors.append({"field": f"output.{field}", "reason": "required"})

    if errors:
        return failed(
            "tree_ensemble_spec_declares_reproducible_comparison",
            len(errors),
            "RandomForestClassifier comparison with seed stability, importances and slices",
            errors,
        )
    return passed(
        "tree_ensemble_spec_declares_reproducible_comparison",
        {
            "tree_ensemble_id": tree_ensemble_spec["tree_ensemble_id"],
            "model_id": tree_ensemble_spec["candidate"]["model_id"],
            "seeds": tree_ensemble_spec["stability_policy"]["seeds"],
        },
        "tree ensemble contract is explicit",
    )


def validate_manifest_for_ensemble(
    manifest_rows: list[dict[str, str]], columns: list[str]
) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    missing_columns = sorted(REQUIRED_MANIFEST_COLUMNS - set(columns))
    if missing_columns:
        errors.append({"reason": "missing manifest columns", "sample": missing_columns})
    split_counts = {split: 0 for split in ("train", "validation", "test")}
    for row in manifest_rows:
        split = row.get("split", "")
        if split in split_counts:
            split_counts[split] += 1
            if row.get("role") != ROLE_BY_SPLIT[split]:
                errors.append(
                    {
                        "snapshot_id": row.get("snapshot_id"),
                        "field": "role",
                        "observed": row.get("role"),
                        "expected": ROLE_BY_SPLIT[split],
                    }
                )
    for split, count in split_counts.items():
        if count == 0:
            errors.append({"reason": "missing split", "split": split})
    if errors:
        return failed(
            "split_manifest_supports_tree_ensemble_roles",
            len(errors),
            "train fit, validation selection/stability and test final evaluation roles",
            errors,
        )
    return passed(
        "split_manifest_supports_tree_ensemble_roles",
        split_counts,
        "manifest exposes correct roles for tree ensemble comparison",
    )


def build_ensemble_pipeline(
    tree_ensemble_spec: dict[str, Any],
    column_transformer_spec: dict[str, Any],
    *,
    seed: int | None = None,
) -> Pipeline:
    params = dict(tree_ensemble_spec["candidate"]["params"])
    if seed is not None:
        params["random_state"] = seed
    estimator = RandomForestClassifier(**params)
    return Pipeline(
        steps=[
            ("preprocess", build_column_transformer(column_transformer_spec)),
            ("estimator", estimator),
        ]
    )


def positive_scores(pipeline: Pipeline, X: Any) -> np.ndarray:
    estimator = pipeline.named_steps["estimator"]
    classes = [int(value) for value in estimator.classes_]
    try:
        positive_index = classes.index(1)
    except ValueError as error:
        raise TreeEnsembleError("fitted ensemble has no positive class 1") from error
    return pipeline.predict_proba(X)[:, positive_index]


def prediction_scores_from_estimator(estimator: RandomForestClassifier, X: Any) -> np.ndarray:
    classes = [int(value) for value in estimator.classes_]
    try:
        positive_index = classes.index(1)
    except ValueError as error:
        raise TreeEnsembleError("fitted ensemble has no positive class 1") from error
    return estimator.predict_proba(X)[:, positive_index]


def comparison_rows(
    linear_report: dict[str, Any],
    tree_report: dict[str, Any],
    ensemble_metric_rows: list[dict[str, Any]],
    primary_metric: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for source, source_rows in (
        ("15/07-linear-baseline", linear_report.get("comparison", [])),
        ("15/08-tree-diagnostic", tree_report.get("metrics", [])),
        ("15/09-tree-ensemble", ensemble_metric_rows),
    ):
        for row in source_rows:
            copied = {
                "source": source,
                "model_id": row["model_id"],
                "model_kind": row["model_kind"],
                "split": row["split"],
                "row_count": row["row_count"],
                "positive_count": row["positive_count"],
                "negative_count": row["negative_count"],
                "selection_budget": row["selection_budget"],
                "precision_at_budget": row["precision_at_budget"],
                "recall_at_budget": row["recall_at_budget"],
                "average_precision": row["average_precision"],
                "roc_auc": row["roc_auc"],
                "log_loss": row["log_loss"],
                "error_cost_at_budget": row["error_cost_at_budget"],
                "accuracy_at_0_5": row["accuracy_at_0_5"],
                "selected_on_validation": False,
                "selection_rank": "",
            }
            rows.append(copied)

    validation_rows = [row for row in rows if row["split"] == "validation"]
    ranked = sorted(
        validation_rows,
        key=lambda row: (
            -float(row[primary_metric]),
            float(row["error_cost_at_budget"]),
            -(float(row["average_precision"]) if row["average_precision"] is not None else -1.0),
            float(row["log_loss"]),
            str(row["model_id"]),
        ),
    )
    for rank, row in enumerate(ranked, start=1):
        row["selection_rank"] = rank
        row["selected_on_validation"] = rank == 1
    rank_by_model = {row["model_id"]: row["selection_rank"] for row in ranked}
    selected_by_model = {row["model_id"]: row["selected_on_validation"] for row in ranked}
    for row in rows:
        if row["split"] != "validation" and row["model_id"] in rank_by_model:
            row["selection_rank"] = rank_by_model[row["model_id"]]
            row["selected_on_validation"] = selected_by_model[row["model_id"]]
    return rows


def build_stability_rows(
    *,
    tree_ensemble_spec: dict[str, Any],
    column_transformer_spec: dict[str, Any],
    feature_rows_by_id: dict[str, dict[str, str]],
    labels_by_id: dict[str, dict[str, str]],
    problem_spec: dict[str, Any],
    train_ids: list[str],
    validation_ids: list[str],
    budget: int,
    false_positive_cost: float,
    false_negative_cost: float,
) -> list[dict[str, Any]]:
    seeds = tree_ensemble_spec["stability_policy"]["seeds"]
    rows: list[dict[str, Any]] = []
    X_train = make_frame(train_ids, feature_rows_by_id, column_transformer_spec)
    y_train = make_target(train_ids, labels_by_id, problem_spec)
    X_validation = make_frame(validation_ids, feature_rows_by_id, column_transformer_spec)
    y_validation = make_target(validation_ids, labels_by_id, problem_spec)
    for seed in seeds:
        pipeline = build_ensemble_pipeline(tree_ensemble_spec, column_transformer_spec, seed=seed)
        pipeline.fit(X_train, y_train)
        scores = positive_scores(pipeline, X_validation)
        metric = split_metric_row(
            model_id=f"{tree_ensemble_spec['candidate']['model_id']}__seed_{seed}",
            model_kind=tree_ensemble_spec["candidate"]["kind"],
            split="validation",
            ids=validation_ids,
            y_true=y_validation,
            scores=scores,
            budget=budget,
            false_positive_cost=false_positive_cost,
            false_negative_cost=false_negative_cost,
        )
        selected_ids = sorted(selected_ids_at_budget(validation_ids, scores, budget))
        rows.append(
            {
                "model_id": tree_ensemble_spec["candidate"]["model_id"],
                "seed": seed,
                "split": "validation",
                "precision_at_budget": metric["precision_at_budget"],
                "recall_at_budget": metric["recall_at_budget"],
                "average_precision": metric["average_precision"],
                "log_loss": metric["log_loss"],
                "error_cost_at_budget": metric["error_cost_at_budget"],
                "accuracy_at_0_5": metric["accuracy_at_0_5"],
                "selected_ids": ",".join(selected_ids),
            }
        )
    return rows


def validate_stability_rows(
    stability_rows: list[dict[str, Any]], tree_ensemble_spec: dict[str, Any]
) -> dict[str, Any]:
    policy = tree_ensemble_spec["stability_policy"]
    metric = policy["metric"]
    values = [float(row[metric]) for row in stability_rows]
    observed_range = rounded(max(values) - min(values)) if values else 0.0
    selected_sets = {row["selected_ids"] for row in stability_rows}
    if observed_range > float(policy["max_allowed_range"]):
        return failed(
            "ensemble_seed_stability_range_exceeds_threshold",
            {"metric": metric, "range": observed_range, "selected_id_sets": sorted(selected_sets)},
            f"range <= {policy['max_allowed_range']}",
            severity="warning",
        )
    return passed(
        "ensemble_seed_stability_reported",
        {"metric": metric, "range": observed_range, "selected_id_sets": sorted(selected_sets)},
        "stability across declared seeds is reported",
    )


def precision_at_budget_score(y_true: np.ndarray, scores: np.ndarray, budget: int) -> float:
    if len(y_true) == 0:
        return 0.0
    ranked_indices = sorted(range(len(scores)), key=lambda index: (-float(scores[index]), index))
    selected = set(ranked_indices[:budget])
    selected_count = max(1, len(selected))
    true_positives = sum(1 for index in selected if int(y_true[index]) == 1)
    return true_positives / selected_count


def build_feature_importance_rows(
    *,
    pipeline: Pipeline,
    tree_ensemble_spec: dict[str, Any],
    column_transformer_spec: dict[str, Any],
    feature_rows_by_id: dict[str, dict[str, str]],
    labels_by_id: dict[str, dict[str, str]],
    problem_spec: dict[str, Any],
    validation_ids: list[str],
    feature_names: list[str],
    budget: int,
) -> list[dict[str, Any]]:
    estimator: RandomForestClassifier = pipeline.named_steps["estimator"]
    policy = tree_ensemble_spec["feature_importance_policy"]
    top_n = int(policy["top_n"])
    rows: list[dict[str, Any]] = []

    mdi_means = estimator.feature_importances_
    tree_importances = np.array([tree.feature_importances_ for tree in estimator.estimators_])
    mdi_stds = tree_importances.std(axis=0)
    for rank, feature_index in enumerate(np.argsort(mdi_means)[::-1][:top_n], start=1):
        rows.append(
            {
                "method": "mdi",
                "rank": rank,
                "feature_index": int(feature_index),
                "feature_name": feature_names[int(feature_index)],
                "importance_mean": rounded(float(mdi_means[int(feature_index)])),
                "importance_std": rounded(float(mdi_stds[int(feature_index)])),
                "computed_on_split": "train_impurity",
                "warning": "mdi_importance_is_train_impurity_based",
            }
        )

    preprocess = pipeline.named_steps["preprocess"]
    X_validation_raw = make_frame(validation_ids, feature_rows_by_id, column_transformer_spec)
    X_validation = preprocess.transform(X_validation_raw)
    y_validation = make_target(validation_ids, labels_by_id, problem_spec)

    def scorer(model: RandomForestClassifier, X: Any, y: np.ndarray) -> float:
        scores = prediction_scores_from_estimator(model, X)
        return precision_at_budget_score(y, scores, budget)

    permutation = permutation_importance(
        estimator,
        X_validation,
        y_validation,
        n_repeats=int(policy["permutation_repeats"]),
        random_state=int(policy["permutation_random_state"]),
        scoring=scorer,
    )
    permutation_means = permutation.importances_mean
    permutation_stds = permutation.importances_std
    for rank, feature_index in enumerate(np.argsort(permutation_means)[::-1][:top_n], start=1):
        rows.append(
            {
                "method": "permutation",
                "rank": rank,
                "feature_index": int(feature_index),
                "feature_name": feature_names[int(feature_index)],
                "importance_mean": rounded(float(permutation_means[int(feature_index)])),
                "importance_std": rounded(float(permutation_stds[int(feature_index)])),
                "computed_on_split": policy["permutation_split"],
                "warning": "permutation_on_tiny_validation_is_unstable",
            }
        )
    return rows


def validate_feature_importance_rows(
    importance_rows: list[dict[str, Any]],
    feature_schema_rows: list[dict[str, Any]],
    tree_ensemble_spec: dict[str, Any],
) -> dict[str, Any]:
    known_features = {row["feature_name"] for row in feature_schema_rows}
    observed_methods = {row["method"] for row in importance_rows}
    unknown = sorted({row["feature_name"] for row in importance_rows} - known_features)
    expected_methods = set(tree_ensemble_spec["feature_importance_policy"]["methods"])
    if unknown or observed_methods != expected_methods:
        return failed(
            "ensemble_feature_importance_aligns_with_schema",
            {"methods": sorted(observed_methods), "unknown_features": unknown},
            {"methods": sorted(expected_methods), "unknown_features": []},
        )
    return passed(
        "ensemble_feature_importance_aligns_with_schema",
        {"methods": sorted(observed_methods), "rows": len(importance_rows)},
        "feature importance rows use transformed feature schema",
    )


def build_slice_metric_rows(
    *,
    tree_ensemble_spec: dict[str, Any],
    feature_rows_by_id: dict[str, dict[str, str]],
    labels_by_id: dict[str, dict[str, str]],
    problem_spec: dict[str, Any],
    validation_ids: list[str],
    validation_scores: np.ndarray,
    budget: int,
    false_positive_cost: float,
    false_negative_cost: float,
) -> list[dict[str, Any]]:
    policy = tree_ensemble_spec["slice_policy"]
    min_rows = int(policy["min_rows_for_reliable_slice"])
    score_by_id = dict(zip(validation_ids, validation_scores.tolist(), strict=True))
    rows: list[dict[str, Any]] = []
    for slice_column in policy["slices"]:
        values = sorted(
            {feature_rows_by_id[snapshot_id][slice_column] for snapshot_id in validation_ids}
        )
        for slice_value in values:
            ids = [
                snapshot_id
                for snapshot_id in validation_ids
                if feature_rows_by_id[snapshot_id][slice_column] == slice_value
            ]
            y_true = make_target(ids, labels_by_id, problem_spec)
            scores = np.array([score_by_id[snapshot_id] for snapshot_id in ids])
            slice_budget = min(budget, len(ids))
            metric = split_metric_row(
                model_id=tree_ensemble_spec["candidate"]["model_id"],
                model_kind=tree_ensemble_spec["candidate"]["kind"],
                split="validation",
                ids=ids,
                y_true=y_true,
                scores=scores,
                budget=slice_budget,
                false_positive_cost=false_positive_cost,
                false_negative_cost=false_negative_cost,
            )
            rows.append(
                {
                    "model_id": tree_ensemble_spec["candidate"]["model_id"],
                    "split": "validation",
                    "slice_column": slice_column,
                    "slice_value": slice_value,
                    "row_count": metric["row_count"],
                    "positive_count": metric["positive_count"],
                    "negative_count": metric["negative_count"],
                    "selection_budget": slice_budget,
                    "precision_at_budget": metric["precision_at_budget"],
                    "recall_at_budget": metric["recall_at_budget"],
                    "accuracy_at_0_5": metric["accuracy_at_0_5"],
                    "small_n_warning": len(ids) < min_rows,
                }
            )
    return rows


def validate_slice_metric_rows(
    slice_rows: list[dict[str, Any]], tree_ensemble_spec: dict[str, Any]
) -> dict[str, Any]:
    expected_slices = set(tree_ensemble_spec["slice_policy"]["slices"])
    observed_slices = {row["slice_column"] for row in slice_rows}
    if observed_slices != expected_slices or not slice_rows:
        return failed(
            "ensemble_slice_metrics_reported",
            {"observed_slices": sorted(observed_slices), "rows": len(slice_rows)},
            {"expected_slices": sorted(expected_slices)},
        )
    return passed(
        "ensemble_slice_metrics_reported",
        {"observed_slices": sorted(observed_slices), "rows": len(slice_rows)},
        "validation slice metrics are published",
    )


def validate_fit_trace(trace: list[dict[str, Any]], train_ids: list[str]) -> dict[str, Any]:
    bad_fit_events = [
        event
        for event in trace
        if event["event"] == "pipeline.fit" and event["snapshot_ids"] != train_ids
    ]
    if bad_fit_events:
        return failed(
            "ensemble_fit_uses_train_only",
            bad_fit_events,
            "ensemble Pipeline.fit receives exactly train split ids",
        )
    return passed(
        "ensemble_fit_uses_train_only",
        {"fit_split": "train", "fit_snapshot_ids": train_ids},
        "tree ensemble fit used train only",
    )


def validate_predictions(
    prediction_rows: list[dict[str, Any]],
    manifest_rows: list[dict[str, str]],
    model_id: str,
) -> dict[str, Any]:
    expected_ids = {
        row["snapshot_id"]
        for row in manifest_rows
        if row["split"] in {"train", "validation", "test"}
    }
    observed_ids = [str(row["snapshot_id"]) for row in prediction_rows]
    errors: list[dict[str, Any]] = []
    if len(observed_ids) != len(set(observed_ids)):
        errors.append({"reason": "duplicate prediction rows"})
    missing = sorted(expected_ids - set(observed_ids))
    extra = sorted(set(observed_ids) - expected_ids)
    if missing:
        errors.append({"reason": "missing predictions", "sample": missing[:5]})
    if extra:
        errors.append({"reason": "unexpected predictions", "sample": extra[:5]})
    for row in prediction_rows:
        score = float(row["score"])
        if score < 0 or score > 1:
            errors.append({"snapshot_id": row["snapshot_id"], "reason": "score outside [0, 1]"})
        if row["model_id"] != model_id:
            errors.append(
                {
                    "snapshot_id": row["snapshot_id"],
                    "observed": row["model_id"],
                    "expected": model_id,
                }
            )
        if row["trained_on_split"] != "train":
            errors.append(
                {
                    "snapshot_id": row["snapshot_id"],
                    "observed": row["trained_on_split"],
                    "expected": "train",
                }
            )
    if errors:
        return failed(
            "ensemble_predictions_cover_train_validation_and_test",
            len(errors),
            "one ensemble probability row per train/validation/test snapshot",
            errors,
        )
    return passed(
        "ensemble_predictions_cover_train_validation_and_test",
        {"rows": len(prediction_rows), "model_id": model_id},
        "ensemble scored train for diagnostics and validation/test for evaluation",
    )


def first_warning_check(upstream_report: dict[str, Any], check_id: str) -> dict[str, Any] | None:
    for check in upstream_report.get("checks", []):
        if check.get("id") == check_id:
            return check
    return None


def run(
    *,
    spec_path: Path,
    preprocessing_contract_path: Path,
    pipeline_spec_path: Path,
    column_transformer_spec_path: Path,
    linear_baseline_spec_path: Path,
    tree_diagnostic_spec_path: Path,
    tree_ensemble_spec_path: Path,
    features_path: Path,
    labels_path: Path,
    manifest_path: Path,
    report_output_path: Path | None = None,
    comparison_output_path: Path | None = None,
    stability_output_path: Path | None = None,
    feature_importance_output_path: Path | None = None,
    slice_metrics_output_path: Path | None = None,
    predictions_output_path: Path | None = None,
    serialized_spec_output_path: Path | None = None,
) -> dict[str, Any]:
    problem_spec = read_json(spec_path)
    pipeline_spec = read_json(pipeline_spec_path)
    column_transformer_spec = read_json(column_transformer_spec_path)
    linear_baseline_spec = read_json(linear_baseline_spec_path)
    tree_diagnostic_spec = read_json(tree_diagnostic_spec_path)
    tree_ensemble_spec = read_json(tree_ensemble_spec_path)
    feature_rows, _feature_columns = read_csv(features_path)
    labels, _label_columns = read_csv(labels_path)
    manifest_rows, manifest_columns = read_csv(manifest_path)

    checks: list[dict[str, Any]] = [
        validate_tree_ensemble_spec(
            problem_spec=problem_spec,
            pipeline_spec=pipeline_spec,
            column_transformer_spec=column_transformer_spec,
            linear_baseline_spec=linear_baseline_spec,
            tree_diagnostic_spec=tree_diagnostic_spec,
            tree_ensemble_spec=tree_ensemble_spec,
        ),
        validate_manifest_for_ensemble(manifest_rows, manifest_columns),
    ]
    linear_report = run_linear_baseline_audit(
        spec_path=spec_path,
        preprocessing_contract_path=preprocessing_contract_path,
        pipeline_spec_path=pipeline_spec_path,
        column_transformer_spec_path=column_transformer_spec_path,
        linear_baseline_spec_path=linear_baseline_spec_path,
        features_path=features_path,
        labels_path=labels_path,
        manifest_path=manifest_path,
    )
    tree_report = run_tree_diagnostic_audit(
        spec_path=spec_path,
        preprocessing_contract_path=preprocessing_contract_path,
        pipeline_spec_path=pipeline_spec_path,
        column_transformer_spec_path=column_transformer_spec_path,
        linear_baseline_spec_path=linear_baseline_spec_path,
        tree_diagnostic_spec_path=tree_diagnostic_spec_path,
        features_path=features_path,
        labels_path=labels_path,
        manifest_path=manifest_path,
    )
    if tree_report.get("valid"):
        checks.append(
            passed(
                "upstream_tree_diagnostic_audit_is_valid",
                {
                    "tree_diagnostic_id": tree_diagnostic_spec.get("tree_diagnostic_id"),
                    "readiness_status": tree_report["summary"].get("readiness_status"),
                },
                "tree diagnostic handoff is valid",
            )
        )
    else:
        checks.append(
            failed(
                "upstream_tree_diagnostic_audit_is_valid",
                tree_report.get("summary", {}).get("blocking_errors", []),
                "valid tree diagnostic report before ensemble comparison",
                tree_report.get("checks", []),
            )
        )

    blocking_errors = [
        check["id"] for check in checks if check["severity"] == "error" and not check["valid"]
    ]
    if blocking_errors:
        report = {
            "valid": False,
            "problem_id": problem_spec.get("problem_id"),
            "summary": {
                "tree_ensemble_id": tree_ensemble_spec.get("tree_ensemble_id"),
                "blocking_errors": blocking_errors,
                "warnings": [],
                "readiness_status": "blocked_before_ensemble_fit",
            },
            "checks": checks,
        }
        if report_output_path is not None:
            write_json(report_output_path, report)
        return report

    feature_rows_by_id = rows_by_id(feature_rows)
    labels_by_id = rows_by_id(labels)
    train_ids = split_ids(manifest_rows, "train")
    validation_ids = split_ids(manifest_rows, "validation")
    test_ids = split_ids(manifest_rows, "test")
    X_train = make_frame(train_ids, feature_rows_by_id, column_transformer_spec)
    y_train = make_target(train_ids, labels_by_id, problem_spec)
    if len(set(y_train.tolist())) < 2:
        checks.append(
            failed(
                "train_split_has_both_classes_for_tree_ensemble",
                sorted(set(y_train.tolist())),
                "binary train labels",
            )
        )
        report = {
            "valid": False,
            "problem_id": problem_spec.get("problem_id"),
            "summary": {
                "tree_ensemble_id": tree_ensemble_spec.get("tree_ensemble_id"),
                "blocking_errors": ["train_split_has_both_classes_for_tree_ensemble"],
                "warnings": [],
                "readiness_status": "blocked_before_ensemble_fit",
            },
            "checks": checks,
        }
        if report_output_path is not None:
            write_json(report_output_path, report)
        return report

    pipeline = build_ensemble_pipeline(tree_ensemble_spec, column_transformer_spec)
    pipeline.fit(X_train, y_train)
    preprocess = pipeline.named_steps["preprocess"]
    estimator: RandomForestClassifier = pipeline.named_steps["estimator"]
    feature_names = [str(value) for value in preprocess.get_feature_names_out()]
    feature_schema_rows = build_feature_schema(feature_names, column_transformer_spec)
    false_positive_cost, false_negative_cost = cost_weights(problem_spec)
    budget = selection_budget(problem_spec)
    model_id = tree_ensemble_spec["candidate"]["model_id"]
    model_kind = tree_ensemble_spec["candidate"]["kind"]

    fit_trace: list[dict[str, Any]] = [
        {
            "event": "pipeline.fit",
            "model_id": model_id,
            "split": "train",
            "snapshot_ids": train_ids,
            "row_count": len(train_ids),
            "fits_column_transformer": True,
            "fits_estimator": True,
        }
    ]
    metric_rows: list[dict[str, Any]] = []
    prediction_rows: list[dict[str, Any]] = []
    validation_scores = np.array([])
    for split, ids in (("train", train_ids), ("validation", validation_ids), ("test", test_ids)):
        X_split = make_frame(ids, feature_rows_by_id, column_transformer_spec)
        y_split = make_target(ids, labels_by_id, problem_spec)
        scores = positive_scores(pipeline, X_split)
        if split == "validation":
            validation_scores = scores
        if split != "train":
            fit_trace.append(
                {
                    "event": "pipeline.predict_proba",
                    "model_id": model_id,
                    "split": split,
                    "snapshot_ids": ids,
                    "row_count": len(ids),
                    "uses_fitted_column_transformer": True,
                    "fits_anything": False,
                }
            )
        metric_rows.append(
            split_metric_row(
                model_id=model_id,
                model_kind=model_kind,
                split=split,
                ids=ids,
                y_true=y_split,
                scores=scores,
                budget=budget,
                false_positive_cost=false_positive_cost,
                false_negative_cost=false_negative_cost,
            )
        )
        split_prediction_rows = prediction_rows_for_split(
            model_id=model_id,
            model_kind=model_kind,
            split=split,
            ids=ids,
            y_true=y_split,
            scores=scores,
            score_type=tree_ensemble_spec["score_type"],
            budget=budget,
        )
        for row in split_prediction_rows:
            row["generated_at"] = GENERATED_AT
        prediction_rows.extend(split_prediction_rows)

    all_comparison_rows = comparison_rows(
        linear_report,
        tree_report,
        metric_rows,
        tree_ensemble_spec["comparison"]["primary_metric"],
    )
    stability_rows = build_stability_rows(
        tree_ensemble_spec=tree_ensemble_spec,
        column_transformer_spec=column_transformer_spec,
        feature_rows_by_id=feature_rows_by_id,
        labels_by_id=labels_by_id,
        problem_spec=problem_spec,
        train_ids=train_ids,
        validation_ids=validation_ids,
        budget=budget,
        false_positive_cost=false_positive_cost,
        false_negative_cost=false_negative_cost,
    )
    feature_importance_rows = build_feature_importance_rows(
        pipeline=pipeline,
        tree_ensemble_spec=tree_ensemble_spec,
        column_transformer_spec=column_transformer_spec,
        feature_rows_by_id=feature_rows_by_id,
        labels_by_id=labels_by_id,
        problem_spec=problem_spec,
        validation_ids=validation_ids,
        feature_names=feature_names,
        budget=budget,
    )
    slice_rows = build_slice_metric_rows(
        tree_ensemble_spec=tree_ensemble_spec,
        feature_rows_by_id=feature_rows_by_id,
        labels_by_id=labels_by_id,
        problem_spec=problem_spec,
        validation_ids=validation_ids,
        validation_scores=validation_scores,
        budget=budget,
        false_positive_cost=false_positive_cost,
        false_negative_cost=false_negative_cost,
    )

    checks.append(validate_fit_trace(fit_trace, train_ids))
    checks.append(validate_predictions(prediction_rows, manifest_rows, model_id))
    checks.append(validate_stability_rows(stability_rows, tree_ensemble_spec))
    checks.append(
        validate_feature_importance_rows(
            feature_importance_rows, feature_schema_rows, tree_ensemble_spec
        )
    )
    checks.append(validate_slice_metric_rows(slice_rows, tree_ensemble_spec))

    unknown_warning = first_warning_check(tree_report, "tree_unknown_categories_bucketed")
    if unknown_warning is not None and not unknown_warning.get("valid", True):
        checks.append(
            failed(
                "ensemble_unknown_categories_bucketed",
                unknown_warning.get("observed"),
                "unknown validation/test categories inherited explicit ColumnTransformer bucket",
                unknown_warning.get("sample", []),
                severity="warning",
            )
        )
    if len(train_ids) < TINY_TRAIN_WARNING_THRESHOLD:
        checks.append(
            failed(
                "tiny_ensemble_training_sample_expected",
                len(train_ids),
                f">= {TINY_TRAIN_WARNING_THRESHOLD} train rows for production ensemble comparison",
                severity="warning",
            )
        )
    checks.append(
        failed(
            "ensemble_feature_importance_requires_caution",
            tree_ensemble_spec["feature_importance_policy"]["warnings"],
            "feature importances are diagnostics, not causal or stable explanations",
            severity="warning",
        )
    )
    small_slices = [row for row in slice_rows if row["small_n_warning"]]
    if small_slices:
        checks.append(
            failed(
                "ensemble_slice_metrics_have_small_n",
                [
                    {
                        "slice_column": row["slice_column"],
                        "slice_value": row["slice_value"],
                        "row_count": row["row_count"],
                    }
                    for row in small_slices
                ],
                f">= {tree_ensemble_spec['slice_policy']['min_rows_for_reliable_slice']} rows",
                severity="warning",
            )
        )

    blocking_errors = [
        check["id"] for check in checks if check["severity"] == "error" and not check["valid"]
    ]
    warnings = [
        check["id"] for check in checks if check["severity"] == "warning" and not check["valid"]
    ]
    valid = not blocking_errors
    validation_rows = [row for row in all_comparison_rows if row["split"] == "validation"]
    selected_row = next(row for row in validation_rows if row["selected_on_validation"])
    ensemble_validation_row = next(
        row
        for row in validation_rows
        if row["model_id"] == model_id and row["source"] == "15/09-tree-ensemble"
    )
    tree_validation_row = next(
        row
        for row in validation_rows
        if row["model_id"] == tree_diagnostic_spec["candidate"]["model_id"]
        and row["source"] == "15/08-tree-diagnostic"
    )
    selected_ids = sorted(selected_ids_at_budget(validation_ids, validation_scores, budget))
    stability_metric = tree_ensemble_spec["stability_policy"]["metric"]
    stability_values = [float(row[stability_metric]) for row in stability_rows]
    stability_range = rounded(max(stability_values) - min(stability_values))
    top_mdi = next(
        row for row in feature_importance_rows if row["method"] == "mdi" and row["rank"] == 1
    )
    top_permutation = next(
        row
        for row in feature_importance_rows
        if row["method"] == "permutation" and row["rank"] == 1
    )

    serialized_spec = {
        "tree_ensemble_id": tree_ensemble_spec["tree_ensemble_id"],
        "problem_id": problem_spec["problem_id"],
        "sklearn_version": sklearn.__version__,
        "column_transformer_id": column_transformer_spec["column_transformer_id"],
        "linear_baseline_id": linear_baseline_spec["linear_baseline_id"],
        "tree_diagnostic_id": tree_diagnostic_spec["tree_diagnostic_id"],
        "model": {
            "model_id": model_id,
            "class": "RandomForestClassifier",
            "params": tree_ensemble_spec["candidate"]["params"],
            "classes": [int(value) for value in estimator.classes_],
            "n_estimators": len(estimator.estimators_),
            "max_depth": tree_ensemble_spec["candidate"]["params"]["max_depth"],
            "feature_count": len(feature_names),
        },
        "fit_trace": fit_trace,
        "feature_schema": feature_schema_rows,
        "selection": {
            "selected_model_id": selected_row["model_id"],
            "selected_on_split": "validation",
            "test_used_for_selection": False,
            "ensemble_selected_ids_on_validation": selected_ids,
        },
        "stability": {
            "metric": stability_metric,
            "seeds": tree_ensemble_spec["stability_policy"]["seeds"],
            "range": stability_range,
        },
        "feature_importance_policy": tree_ensemble_spec["feature_importance_policy"],
        "slice_policy": tree_ensemble_spec["slice_policy"],
    }
    summary = {
        "tree_ensemble_id": tree_ensemble_spec["tree_ensemble_id"],
        "problem_id": problem_spec["problem_id"],
        "sklearn_version": sklearn.__version__,
        "fit_split": "train",
        "fit_row_count": len(train_ids),
        "selection_split": "validation",
        "final_holdout_split": "test",
        "model_id": model_id,
        "n_estimators": len(estimator.estimators_),
        "max_depth_limit": tree_ensemble_spec["candidate"]["params"]["max_depth"],
        "transformed_feature_count": len(feature_schema_rows),
        "prediction_row_count": len(prediction_rows),
        "selected_model_id": selected_row["model_id"],
        "selected_model_source": selected_row["source"],
        "test_used_for_selection": False,
        "ensemble_validation_precision_at_budget": ensemble_validation_row["precision_at_budget"],
        "tree_validation_precision_at_budget": tree_validation_row["precision_at_budget"],
        "selected_ids_on_validation": selected_ids,
        "stability_metric": stability_metric,
        "stability_range": stability_range,
        "stability_selected_id_sets": sorted({row["selected_ids"] for row in stability_rows}),
        "top_mdi_feature": top_mdi["feature_name"],
        "top_mdi_importance": top_mdi["importance_mean"],
        "top_permutation_feature": top_permutation["feature_name"],
        "top_permutation_importance": top_permutation["importance_mean"],
        "slice_metric_row_count": len(slice_rows),
        "small_n_slice_count": len(small_slices),
        "upstream_warnings": tree_report["summary"].get("warnings", []),
        "blocking_errors": blocking_errors,
        "warnings": warnings,
        "readiness_status": "ready_for_cross_validation_lesson"
        if valid
        else "blocked_by_tree_ensemble_audit",
    }
    report = {
        "valid": valid,
        "problem_id": problem_spec["problem_id"],
        "summary": summary,
        "comparison": all_comparison_rows,
        "stability": stability_rows,
        "feature_importance": feature_importance_rows,
        "slice_metrics": slice_rows,
        "predictions": prediction_rows,
        "serialized_spec": serialized_spec,
        "checks": checks,
    }

    if comparison_output_path is not None:
        write_csv(
            comparison_output_path,
            all_comparison_rows,
            [
                "source",
                "model_id",
                "model_kind",
                "split",
                "row_count",
                "positive_count",
                "negative_count",
                "selection_budget",
                "precision_at_budget",
                "recall_at_budget",
                "average_precision",
                "roc_auc",
                "log_loss",
                "error_cost_at_budget",
                "accuracy_at_0_5",
                "selected_on_validation",
                "selection_rank",
            ],
        )
    if stability_output_path is not None:
        write_csv(
            stability_output_path,
            stability_rows,
            [
                "model_id",
                "seed",
                "split",
                "precision_at_budget",
                "recall_at_budget",
                "average_precision",
                "log_loss",
                "error_cost_at_budget",
                "accuracy_at_0_5",
                "selected_ids",
            ],
        )
    if feature_importance_output_path is not None:
        write_csv(
            feature_importance_output_path,
            feature_importance_rows,
            [
                "method",
                "rank",
                "feature_index",
                "feature_name",
                "importance_mean",
                "importance_std",
                "computed_on_split",
                "warning",
            ],
        )
    if slice_metrics_output_path is not None:
        write_csv(
            slice_metrics_output_path,
            slice_rows,
            [
                "model_id",
                "split",
                "slice_column",
                "slice_value",
                "row_count",
                "positive_count",
                "negative_count",
                "selection_budget",
                "precision_at_budget",
                "recall_at_budget",
                "accuracy_at_0_5",
                "small_n_warning",
            ],
        )
    if predictions_output_path is not None:
        write_csv(
            predictions_output_path,
            prediction_rows,
            [
                "snapshot_id",
                "model_id",
                "model_kind",
                "split",
                "score",
                "score_type",
                "actual_label",
                "predicted_label_at_0_5",
                "selected_at_budget",
                "trained_on_split",
                "generated_at",
            ],
        )
    if serialized_spec_output_path is not None:
        write_json(serialized_spec_output_path, json_ready(serialized_spec))
    if report_output_path is not None:
        write_json(report_output_path, json_ready(report))
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare a tree ensemble against ML baselines")
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--preprocessing-contract", type=Path, required=True)
    parser.add_argument("--pipeline-spec", type=Path, required=True)
    parser.add_argument("--column-transformer-spec", type=Path, required=True)
    parser.add_argument("--linear-baseline-spec", type=Path, required=True)
    parser.add_argument("--tree-diagnostic-spec", type=Path, required=True)
    parser.add_argument("--tree-ensemble-spec", type=Path, required=True)
    parser.add_argument("--features", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--comparison-output", type=Path)
    parser.add_argument("--stability-output", type=Path)
    parser.add_argument("--feature-importance-output", type=Path)
    parser.add_argument("--slice-metrics-output", type=Path)
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
            linear_baseline_spec_path=args.linear_baseline_spec,
            tree_diagnostic_spec_path=args.tree_diagnostic_spec,
            tree_ensemble_spec_path=args.tree_ensemble_spec,
            features_path=args.features,
            labels_path=args.labels,
            manifest_path=args.manifest,
            report_output_path=args.output,
            comparison_output_path=args.comparison_output,
            stability_output_path=args.stability_output,
            feature_importance_output_path=args.feature_importance_output,
            slice_metrics_output_path=args.slice_metrics_output,
            predictions_output_path=args.predictions_output,
            serialized_spec_output_path=args.serialized_spec_output,
        )
    except (
        OSError,
        json.JSONDecodeError,
        ColumnTransformerAuditError,
        LinearBaselineError,
        TreeDiagnosticError,
        TreeEnsembleError,
        KeyError,
        ValueError,
    ) as error:
        report = {
            "valid": False,
            "summary": {
                "blocking_errors": ["tree_ensemble_runtime_error"],
                "warnings": [],
                "readiness_status": "runtime_error",
            },
            "checks": [
                failed(
                    "tree_ensemble_runtime_error",
                    str(error),
                    "readable inputs and fit-able RandomForestClassifier Pipeline",
                )
            ],
        }
        if args.output is not None:
            write_json(args.output, report)

    if args.output is None:
        print(json.dumps(json_ready(report), ensure_ascii=False, indent=2))

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
