from __future__ import annotations

# ruff: noqa: E402, I001

import argparse
import csv
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import sklearn
from sklearn.dummy import DummyClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, average_precision_score, log_loss, roc_auc_score
from sklearn.pipeline import Pipeline

PREVIOUS_OUTPUT_ROOT = Path(__file__).resolve().parents[2] / "06-column-transformer" / "outputs"
if str(PREVIOUS_OUTPUT_ROOT) not in sys.path:
    sys.path.insert(0, str(PREVIOUS_OUTPUT_ROOT))

from column_transformer_auditor import (  # noqa: E402
    ColumnTransformerAuditError,
    build_column_transformer,
    build_feature_schema,
    failed,
    make_frame,
    make_target,
    passed,
    parse_float,
    read_csv,
    read_json,
    rounded,
    rows_by_id,
    run as run_column_transformer_audit,
    split_ids,
    write_json,
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
GENERATED_AT = "2026-07-02T11:00:00+03:00"
TINY_TRAIN_WARNING_THRESHOLD = 20
COEFFICIENT_LIMIT = "conditional_on_preprocessing_regularization_and_tiny_sample_not_causal"


class LinearBaselineError(ValueError):
    """Raised when linear baseline inputs cannot be parsed."""


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def logistic_candidate_ids(linear_baseline_spec: dict[str, Any]) -> list[str]:
    return [
        str(candidate["model_id"])
        for candidate in linear_baseline_spec.get("candidates", [])
        if isinstance(candidate, dict) and candidate.get("kind") == "logistic_regression"
    ]


def candidate_by_id(linear_baseline_spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(candidate.get("model_id")): candidate
        for candidate in linear_baseline_spec.get("candidates", [])
        if isinstance(candidate, dict)
    }


def validate_linear_baseline_spec(
    *,
    problem_spec: dict[str, Any],
    pipeline_spec: dict[str, Any],
    column_transformer_spec: dict[str, Any],
    linear_baseline_spec: dict[str, Any],
) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    expected_identity = {
        "problem_id": problem_spec.get("problem_id"),
        "pipeline_id": pipeline_spec.get("pipeline_id"),
        "column_transformer_id": column_transformer_spec.get("column_transformer_id"),
    }
    for field, expected in expected_identity.items():
        if linear_baseline_spec.get(field) != expected:
            errors.append(
                {"field": field, "observed": linear_baseline_spec.get(field), "expected": expected}
            )

    expected_splits = {
        "fit_split": "train",
        "selection_split": "validation",
        "final_holdout_split": "test",
        "preprocessing_location": "inside_pipeline",
    }
    for field, expected in expected_splits.items():
        if linear_baseline_spec.get(field) != expected:
            errors.append(
                {"field": field, "observed": linear_baseline_spec.get(field), "expected": expected}
            )
    if linear_baseline_spec.get("score_type") != column_transformer_spec.get("score_type"):
        errors.append(
            {
                "field": "score_type",
                "observed": linear_baseline_spec.get("score_type"),
                "expected": column_transformer_spec.get("score_type"),
            }
        )

    candidates = linear_baseline_spec.get("candidates")
    if not isinstance(candidates, list):
        errors.append({"field": "candidates", "reason": "list required"})
        candidates = []
    candidate_kinds = {
        candidate.get("kind") for candidate in candidates if isinstance(candidate, dict)
    }
    candidate_ids = {
        candidate.get("model_id") for candidate in candidates if isinstance(candidate, dict)
    }
    if "dummy_classifier" not in candidate_kinds:
        errors.append({"field": "candidates", "reason": "dummy_classifier candidate required"})
    if "logistic_regression" not in candidate_kinds:
        errors.append({"field": "candidates", "reason": "logistic_regression candidate required"})
    if len(candidate_ids) != len(candidates):
        errors.append({"field": "candidates.model_id", "reason": "unique model_id required"})

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        model_id = candidate.get("model_id")
        params = candidate.get("params") if isinstance(candidate.get("params"), dict) else {}
        if candidate.get("kind") == "dummy_classifier":
            if params.get("strategy") != "prior":
                errors.append(
                    {
                        "field": f"candidates.{model_id}.params.strategy",
                        "observed": params.get("strategy"),
                        "expected": "prior",
                    }
                )
        elif candidate.get("kind") == "logistic_regression":
            if params.get("solver") != "liblinear":
                errors.append(
                    {
                        "field": f"candidates.{model_id}.params.solver",
                        "observed": params.get("solver"),
                        "expected": "liblinear",
                    }
                )
            if params.get("C") is None:
                errors.append({"field": f"candidates.{model_id}.params.C", "reason": "required"})
            if params.get("l1_ratio") != 0.0:
                errors.append(
                    {
                        "field": f"candidates.{model_id}.params.l1_ratio",
                        "observed": params.get("l1_ratio"),
                        "expected": 0.0,
                    }
                )
            if params.get("random_state") is None:
                errors.append(
                    {"field": f"candidates.{model_id}.params.random_state", "reason": "required"}
                )
            regularization = candidate.get("regularization")
            if not isinstance(regularization, dict) or regularization.get("family") != "l2":
                errors.append(
                    {
                        "field": f"candidates.{model_id}.regularization.family",
                        "observed": regularization,
                        "expected": "l2",
                    }
                )

    comparison = linear_baseline_spec.get("comparison")
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

    coefficient_policy = linear_baseline_spec.get("coefficient_policy")
    if not isinstance(coefficient_policy, dict):
        errors.append({"field": "coefficient_policy", "reason": "object required"})
    else:
        if coefficient_policy.get("require_feature_schema") is not True:
            errors.append(
                {
                    "field": "coefficient_policy.require_feature_schema",
                    "observed": coefficient_policy.get("require_feature_schema"),
                    "expected": True,
                }
            )
        limits = coefficient_policy.get("interpretation_limits")
        if not isinstance(limits, list) or len(limits) < 3:
            errors.append(
                {
                    "field": "coefficient_policy.interpretation_limits",
                    "observed": limits,
                    "expected": "at least three explicit limits",
                }
            )

    audit_policy = linear_baseline_spec.get("audit_policy")
    if not isinstance(audit_policy, dict):
        errors.append({"field": "audit_policy", "reason": "object required"})
    else:
        for field in (
            "require_dummy_baseline",
            "require_logistic_baseline",
            "require_validation_only_selection",
            "forbid_test_selection",
            "require_regularization_declared",
            "require_intercept_reported",
            "require_coefficients_join_feature_schema",
            "require_interpretation_limits",
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

    output = linear_baseline_spec.get("output")
    if not isinstance(output, dict):
        errors.append({"field": "output", "reason": "object required"})
    else:
        for field in (
            "comparison_file",
            "coefficient_file",
            "prediction_file",
            "report_file",
            "serialized_spec_file",
        ):
            if not output.get(field):
                errors.append({"field": f"output.{field}", "reason": "required"})

    if errors:
        return failed(
            "linear_baseline_spec_declares_dummy_and_logistic",
            len(errors),
            "dummy and regularized logistic baseline with validation-only selection",
            errors,
        )
    return passed(
        "linear_baseline_spec_declares_dummy_and_logistic",
        {
            "linear_baseline_id": linear_baseline_spec["linear_baseline_id"],
            "candidates": sorted(candidate_ids),
            "selection_split": "validation",
        },
        "dummy floor and regularized logistic baseline are declared",
    )


def validate_manifest_for_linear_baseline(
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
            "split_manifest_supports_linear_baseline_roles",
            len(errors),
            "train fit, validation selection and test final evaluation roles",
            errors,
        )
    return passed(
        "split_manifest_supports_linear_baseline_roles",
        split_counts,
        "manifest exposes correct roles for linear baseline comparison",
    )


def build_candidate_pipeline(
    candidate: dict[str, Any], column_transformer_spec: dict[str, Any]
) -> Pipeline:
    kind = candidate["kind"]
    params = dict(candidate.get("params") or {})
    if kind == "dummy_classifier":
        estimator = DummyClassifier(**params)
    elif kind == "logistic_regression":
        estimator = LogisticRegression(**params)
    else:
        raise LinearBaselineError(f"unsupported candidate kind: {kind}")
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
        raise LinearBaselineError("fitted estimator has no positive class 1") from error
    return pipeline.predict_proba(X)[:, positive_index]


def cost_weights(problem_spec: dict[str, Any]) -> tuple[float, float]:
    weights = problem_spec.get("metric_policy", {}).get("cost_weights", {})
    return float(weights.get("false_positive", 1.0)), float(weights.get("false_negative", 5.0))


def selection_budget(problem_spec: dict[str, Any]) -> int:
    decision_budget = problem_spec.get("decision_budget")
    if not isinstance(decision_budget, dict):
        return 0
    return int(decision_budget.get("max_actions", 0))


def selected_ids_at_budget(ids: list[str], scores: np.ndarray, budget: int) -> set[str]:
    ranked = sorted(zip(ids, scores.tolist(), strict=True), key=lambda item: (-item[1], item[0]))
    return {snapshot_id for snapshot_id, _score in ranked[:budget]}


def split_metric_row(
    *,
    model_id: str,
    model_kind: str,
    split: str,
    ids: list[str],
    y_true: np.ndarray,
    scores: np.ndarray,
    budget: int,
    false_positive_cost: float,
    false_negative_cost: float,
) -> dict[str, Any]:
    selected_ids = selected_ids_at_budget(ids, scores, budget)
    y_pred_budget = np.array([1 if snapshot_id in selected_ids else 0 for snapshot_id in ids])
    y_pred_threshold = (scores >= 0.5).astype(int)
    positives = int(y_true.sum())
    negatives = int(len(y_true) - positives)
    tp = int(((y_true == 1) & (y_pred_budget == 1)).sum())
    fp = int(((y_true == 0) & (y_pred_budget == 1)).sum())
    fn = int(((y_true == 1) & (y_pred_budget == 0)).sum())
    tn = int(((y_true == 0) & (y_pred_budget == 0)).sum())
    precision = tp / max(1, len(selected_ids))
    recall = None if positives == 0 else tp / positives
    probability_matrix = np.column_stack([1 - scores, scores])
    auc = None
    ap = None
    if len(set(y_true.tolist())) > 1:
        auc = rounded(float(roc_auc_score(y_true, scores)))
        ap = rounded(float(average_precision_score(y_true, scores)))
    return {
        "model_id": model_id,
        "model_kind": model_kind,
        "split": split,
        "row_count": len(ids),
        "positive_count": positives,
        "negative_count": negatives,
        "selection_budget": budget,
        "log_loss": rounded(float(log_loss(y_true, probability_matrix, labels=[0, 1]))),
        "average_precision": ap,
        "roc_auc": auc,
        "precision_at_budget": rounded(precision),
        "recall_at_budget": None if recall is None else rounded(recall),
        "tp_at_budget": tp,
        "fp_at_budget": fp,
        "fn_at_budget": fn,
        "tn_at_budget": tn,
        "error_cost_at_budget": rounded(fp * false_positive_cost + fn * false_negative_cost),
        "accuracy_at_0_5": rounded(float(accuracy_score(y_true, y_pred_threshold))),
        "selected_on_validation": False,
        "selection_rank": "",
    }


def prediction_rows_for_split(
    *,
    model_id: str,
    model_kind: str,
    split: str,
    ids: list[str],
    y_true: np.ndarray,
    scores: np.ndarray,
    score_type: str,
    budget: int,
) -> list[dict[str, Any]]:
    selected_ids = selected_ids_at_budget(ids, scores, budget)
    rows: list[dict[str, Any]] = []
    for snapshot_id, label, score in zip(ids, y_true.tolist(), scores.tolist(), strict=True):
        rows.append(
            {
                "snapshot_id": snapshot_id,
                "model_id": model_id,
                "model_kind": model_kind,
                "split": split,
                "score": rounded(float(score)),
                "score_type": score_type,
                "actual_label": int(label),
                "predicted_label_at_0_5": int(score >= 0.5),
                "selected_at_budget": int(snapshot_id in selected_ids),
                "trained_on_split": "train",
                "generated_at": GENERATED_AT,
            }
        )
    return rows


def metric_sort_key(row: dict[str, Any]) -> tuple[float, float, float, float, str]:
    average_precision = (
        -float(row["average_precision"]) if row["average_precision"] is not None else 0.0
    )
    return (
        -float(row["precision_at_budget"]),
        float(row["error_cost_at_budget"]),
        average_precision,
        float(row["log_loss"]),
        str(row["model_id"]),
    )


def select_model(comparison_rows: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    validation_rows = [row for row in comparison_rows if row["split"] == "validation"]
    ranked = sorted(validation_rows, key=metric_sort_key)
    selected_model_id = str(ranked[0]["model_id"])
    rank_by_model = {str(row["model_id"]): rank for rank, row in enumerate(ranked, start=1)}
    for row in comparison_rows:
        if row["split"] == "validation":
            row["selection_rank"] = rank_by_model[str(row["model_id"])]
            row["selected_on_validation"] = row["model_id"] == selected_model_id
        else:
            row["selection_rank"] = ""
            row["selected_on_validation"] = False
    return selected_model_id, comparison_rows


def build_coefficient_rows(
    *,
    model_id: str,
    estimator: LogisticRegression,
    feature_schema_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    coefficients = estimator.coef_[0].tolist()
    base_rows: list[dict[str, Any]] = []
    intercept = rounded(float(estimator.intercept_[0]))
    for schema_row, coefficient in zip(feature_schema_rows, coefficients, strict=True):
        value = float(coefficient)
        direction = "positive_churn_risk" if value > 0 else "negative_churn_risk"
        if math.isclose(value, 0.0, abs_tol=1e-12):
            direction = "near_zero"
        base_rows.append(
            {
                "model_id": model_id,
                "feature_position": int(schema_row["position"]),
                "feature_name": schema_row["feature_name"],
                "source_route": schema_row["source_route"],
                "source_column": schema_row["source_column"],
                "source_category": schema_row["source_category"],
                "coefficient": rounded(value),
                "abs_coefficient": rounded(abs(value)),
                "odds_multiplier_per_unit": rounded(math.exp(value)),
                "direction": direction,
                "model_intercept": intercept,
                "regularization": "l2_l1_ratio_0_C_1",
                "interpretation_limit": COEFFICIENT_LIMIT,
            }
        )
    ranked = sorted(base_rows, key=lambda row: (-row["abs_coefficient"], row["feature_name"]))
    rank_by_name = {row["feature_name"]: rank for rank, row in enumerate(ranked, start=1)}
    for row in base_rows:
        row["coefficient_rank_by_abs"] = rank_by_name[row["feature_name"]]
    return sorted(base_rows, key=lambda row: row["coefficient_rank_by_abs"])


def validate_fit_trace(trace: list[dict[str, Any]], train_ids: list[str]) -> dict[str, Any]:
    bad_fit_events = [
        event
        for event in trace
        if event["event"] == "pipeline.fit" and event["snapshot_ids"] != train_ids
    ]
    if bad_fit_events:
        return failed(
            "linear_baseline_fit_uses_train_only",
            bad_fit_events,
            "every candidate fit receives exactly train split ids",
        )
    return passed(
        "linear_baseline_fit_uses_train_only",
        {"fit_split": "train", "fit_snapshot_ids": train_ids},
        "all baseline candidates fit on train only",
    )


def validate_selection(
    selected_model_id: str, comparison_rows: list[dict[str, Any]]
) -> dict[str, Any]:
    selected_rows = [row for row in comparison_rows if row["selected_on_validation"]]
    bad_rows = [row for row in selected_rows if row["split"] != "validation"]
    if bad_rows:
        return failed(
            "validation_selection_does_not_peek_at_test",
            bad_rows,
            "selection flag may be assigned from validation ranking only",
        )
    validation_selected = [
        row
        for row in selected_rows
        if row["split"] == "validation" and row["model_id"] == selected_model_id
    ]
    if len(validation_selected) != 1:
        return failed(
            "validation_selection_does_not_peek_at_test",
            selected_model_id,
            "exactly one validation row selects the model",
        )
    return passed(
        "validation_selection_does_not_peek_at_test",
        {"selected_model_id": selected_model_id, "used_split": "validation"},
        "model selection used validation metrics only",
    )


def validate_prediction_rows(
    prediction_rows: list[dict[str, Any]],
    manifest_rows: list[dict[str, str]],
    candidate_ids: list[str],
) -> dict[str, Any]:
    scored_ids = [
        row["snapshot_id"] for row in manifest_rows if row["split"] in {"validation", "test"}
    ]
    expected_pairs = {
        (model_id, snapshot_id) for model_id in candidate_ids for snapshot_id in scored_ids
    }
    observed_pairs = [(row["model_id"], row["snapshot_id"]) for row in prediction_rows]
    errors: list[dict[str, Any]] = []
    if len(observed_pairs) != len(set(observed_pairs)):
        errors.append({"reason": "duplicate model/snapshot prediction rows"})
    missing = sorted(expected_pairs - set(observed_pairs))
    extra = sorted(set(observed_pairs) - expected_pairs)
    if missing:
        errors.append({"reason": "missing predictions", "sample": missing[:5]})
    if extra:
        errors.append({"reason": "unexpected predictions", "sample": extra[:5]})
    for row in prediction_rows:
        score = parse_float(row["score"])
        if score < 0 or score > 1:
            errors.append({"snapshot_id": row["snapshot_id"], "reason": "score outside [0, 1]"})
        if row["split"] == "train":
            errors.append({"snapshot_id": row["snapshot_id"], "reason": "train prediction emitted"})
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
            "dummy_and_logistic_predictions_cover_validation_and_test",
            len(errors),
            "one probability row per candidate and validation/test snapshot only",
            errors,
        )
    return passed(
        "dummy_and_logistic_predictions_cover_validation_and_test",
        {"rows": len(prediction_rows), "candidate_count": len(candidate_ids)},
        "dummy and logistic baselines scored validation/test only",
    )


def validate_coefficients(
    coefficient_rows: list[dict[str, Any]],
    feature_schema_rows: list[dict[str, Any]],
    linear_baseline_spec: dict[str, Any],
) -> dict[str, Any]:
    logistic_ids = logistic_candidate_ids(linear_baseline_spec)
    expected_count = len(logistic_ids) * len(feature_schema_rows)
    expected_names = {row["feature_name"] for row in feature_schema_rows}
    errors: list[dict[str, Any]] = []
    if len(coefficient_rows) != expected_count:
        errors.append(
            {
                "reason": "wrong coefficient row count",
                "observed": len(coefficient_rows),
                "expected": expected_count,
            }
        )
    for model_id in logistic_ids:
        names = {row["feature_name"] for row in coefficient_rows if row["model_id"] == model_id}
        if names != expected_names:
            errors.append(
                {
                    "model_id": model_id,
                    "reason": "feature schema mismatch",
                    "missing": sorted(expected_names - names),
                    "extra": sorted(names - expected_names),
                }
            )
    missing_limits = [
        row["feature_name"] for row in coefficient_rows if not row["interpretation_limit"]
    ]
    if missing_limits:
        errors.append({"reason": "missing interpretation limit", "sample": missing_limits[:5]})
    if errors:
        return failed(
            "coefficient_table_matches_feature_schema",
            len(errors),
            "one coefficient per transformed logistic feature with interpretation limit",
            errors,
        )
    return passed(
        "coefficient_table_matches_feature_schema",
        {"rows": len(coefficient_rows), "feature_count": len(feature_schema_rows)},
        "logistic coefficients are joined to transformed feature schema",
    )


def metric_by_model(
    comparison_rows: list[dict[str, Any]], split: str, metric: str
) -> dict[str, float | None]:
    return {str(row["model_id"]): row[metric] for row in comparison_rows if row["split"] == split}


def run(
    *,
    spec_path: Path,
    preprocessing_contract_path: Path,
    pipeline_spec_path: Path,
    column_transformer_spec_path: Path,
    linear_baseline_spec_path: Path,
    features_path: Path,
    labels_path: Path,
    manifest_path: Path,
    report_output_path: Path | None = None,
    comparison_output_path: Path | None = None,
    coefficients_output_path: Path | None = None,
    predictions_output_path: Path | None = None,
    serialized_spec_output_path: Path | None = None,
) -> dict[str, Any]:
    problem_spec = read_json(spec_path)
    pipeline_spec = read_json(pipeline_spec_path)
    column_transformer_spec = read_json(column_transformer_spec_path)
    linear_baseline_spec = read_json(linear_baseline_spec_path)
    feature_rows, _feature_columns = read_csv(features_path)
    labels, _label_columns = read_csv(labels_path)
    manifest_rows, manifest_columns = read_csv(manifest_path)

    checks: list[dict[str, Any]] = [
        validate_linear_baseline_spec(
            problem_spec=problem_spec,
            pipeline_spec=pipeline_spec,
            column_transformer_spec=column_transformer_spec,
            linear_baseline_spec=linear_baseline_spec,
        ),
        validate_manifest_for_linear_baseline(manifest_rows, manifest_columns),
    ]
    upstream_report = run_column_transformer_audit(
        spec_path=spec_path,
        preprocessing_contract_path=preprocessing_contract_path,
        pipeline_spec_path=pipeline_spec_path,
        column_transformer_spec_path=column_transformer_spec_path,
        features_path=features_path,
        labels_path=labels_path,
        manifest_path=manifest_path,
    )
    if upstream_report.get("valid"):
        checks.append(
            passed(
                "upstream_column_transformer_audit_is_valid",
                {
                    "column_transformer_id": column_transformer_spec.get("column_transformer_id"),
                    "readiness_status": upstream_report["summary"].get("readiness_status"),
                    "transformed_feature_count": upstream_report["summary"].get(
                        "transformed_feature_count"
                    ),
                },
                "ColumnTransformer handoff is valid",
            )
        )
    else:
        checks.append(
            failed(
                "upstream_column_transformer_audit_is_valid",
                upstream_report.get("summary", {}).get("blocking_errors", []),
                "valid ColumnTransformer report before linear baseline fit",
                upstream_report.get("checks", []),
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
                "linear_baseline_id": linear_baseline_spec.get("linear_baseline_id"),
                "blocking_errors": blocking_errors,
                "warnings": [],
                "readiness_status": "blocked_before_linear_baseline_fit",
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
                "train_split_has_both_classes_for_linear_baseline",
                sorted(set(y_train.tolist())),
                "binary train labels",
            )
        )
        report = {
            "valid": False,
            "problem_id": problem_spec.get("problem_id"),
            "summary": {
                "linear_baseline_id": linear_baseline_spec.get("linear_baseline_id"),
                "blocking_errors": ["train_split_has_both_classes_for_linear_baseline"],
                "warnings": [],
                "readiness_status": "blocked_before_linear_baseline_fit",
            },
            "checks": checks,
        }
        if report_output_path is not None:
            write_json(report_output_path, report)
        return report

    false_positive_cost, false_negative_cost = cost_weights(problem_spec)
    budget = selection_budget(problem_spec)
    candidates = list(linear_baseline_spec["candidates"])
    candidate_ids = [str(candidate["model_id"]) for candidate in candidates]
    comparison_rows: list[dict[str, Any]] = []
    prediction_rows: list[dict[str, Any]] = []
    coefficient_rows: list[dict[str, Any]] = []
    fit_trace: list[dict[str, Any]] = []
    model_summaries: list[dict[str, Any]] = []
    logistic_intercepts: dict[str, list[float]] = {}
    feature_schema_rows: list[dict[str, Any]] | None = None

    for candidate in candidates:
        model_id = str(candidate["model_id"])
        model_kind = str(candidate["kind"])
        pipeline = build_candidate_pipeline(candidate, column_transformer_spec)
        pipeline.fit(X_train, y_train)
        preprocess = pipeline.named_steps["preprocess"]
        estimator = pipeline.named_steps["estimator"]
        feature_names_out = [str(value) for value in preprocess.get_feature_names_out()]
        current_feature_schema = build_feature_schema(feature_names_out, column_transformer_spec)
        if feature_schema_rows is None:
            feature_schema_rows = current_feature_schema
        fit_trace.append(
            {
                "event": "pipeline.fit",
                "model_id": model_id,
                "split": "train",
                "snapshot_ids": train_ids,
                "row_count": len(train_ids),
                "fits_column_transformer": True,
                "fits_estimator": True,
            }
        )

        for split, ids in (("validation", validation_ids), ("test", test_ids)):
            X_split = make_frame(ids, feature_rows_by_id, column_transformer_spec)
            y_split = make_target(ids, labels_by_id, problem_spec)
            scores = positive_scores(pipeline, X_split)
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
            comparison_rows.append(
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
            prediction_rows.extend(
                prediction_rows_for_split(
                    model_id=model_id,
                    model_kind=model_kind,
                    split=split,
                    ids=ids,
                    y_true=y_split,
                    scores=scores,
                    score_type=linear_baseline_spec["score_type"],
                    budget=budget,
                )
            )

        if model_kind == "dummy_classifier":
            model_summaries.append(
                {
                    "model_id": model_id,
                    "class": "DummyClassifier",
                    "params": candidate["params"],
                    "classes": [int(value) for value in estimator.classes_],
                    "class_prior": [rounded(float(value)) for value in estimator.class_prior_],
                    "feature_count": len(feature_names_out),
                }
            )
        elif model_kind == "logistic_regression":
            logistic_intercepts[model_id] = [
                rounded(float(value)) for value in estimator.intercept_
            ]
            coefficient_rows.extend(
                build_coefficient_rows(
                    model_id=model_id,
                    estimator=estimator,
                    feature_schema_rows=current_feature_schema,
                )
            )
            model_summaries.append(
                {
                    "model_id": model_id,
                    "class": "LogisticRegression",
                    "params": candidate["params"],
                    "regularization": candidate.get("regularization"),
                    "classes": [int(value) for value in estimator.classes_],
                    "coef_shape": list(estimator.coef_.shape),
                    "intercept": logistic_intercepts[model_id],
                    "feature_count": len(feature_names_out),
                }
            )

    if feature_schema_rows is None:
        raise LinearBaselineError("no candidates were fitted")

    selected_model_id, comparison_rows = select_model(comparison_rows)
    checks.append(validate_fit_trace(fit_trace, train_ids))
    checks.append(validate_selection(selected_model_id, comparison_rows))
    checks.append(validate_prediction_rows(prediction_rows, manifest_rows, candidate_ids))
    checks.append(
        validate_coefficients(coefficient_rows, feature_schema_rows, linear_baseline_spec)
    )

    upstream_warnings = upstream_report["summary"].get("warnings", [])
    unknown_events = upstream_report["summary"].get("unknown_category_events", [])
    if unknown_events:
        checks.append(
            failed(
                "linear_baseline_unknown_categories_bucketed",
                len(unknown_events),
                "unknown validation/test categories routed through the ColumnTransformer bucket",
                unknown_events,
                severity="warning",
            )
        )
    if len(train_ids) < TINY_TRAIN_WARNING_THRESHOLD:
        checks.append(
            failed(
                "tiny_linear_baseline_training_sample_expected",
                len(train_ids),
                f">= {TINY_TRAIN_WARNING_THRESHOLD} train rows for production baseline selection",
                severity="warning",
            )
        )

    validation_precision = metric_by_model(comparison_rows, "validation", "precision_at_budget")
    dummy_precision = validation_precision.get("dummy_prior")
    logistic_precisions = [
        value for model_id, value in validation_precision.items() if model_id in logistic_intercepts
    ]
    if dummy_precision is not None and logistic_precisions:
        best_logistic_precision = max(
            float(value) for value in logistic_precisions if value is not None
        )
        if best_logistic_precision <= float(dummy_precision):
            checks.append(
                failed(
                    "linear_baseline_does_not_beat_dummy_on_tiny_validation",
                    {
                        "dummy_prior_precision_at_budget": dummy_precision,
                        "best_logistic_precision_at_budget": rounded(best_logistic_precision),
                    },
                    "regularized logistic should beat dummy before production promotion",
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
    top_positive = sorted(
        coefficient_rows,
        key=lambda row: (-row["coefficient"], row["feature_name"]),
    )[:3]
    top_negative = sorted(
        coefficient_rows,
        key=lambda row: (row["coefficient"], row["feature_name"]),
    )[:3]

    serialized_spec = {
        "linear_baseline_id": linear_baseline_spec["linear_baseline_id"],
        "problem_id": problem_spec["problem_id"],
        "sklearn_version": sklearn.__version__,
        "column_transformer_id": column_transformer_spec["column_transformer_id"],
        "candidate_models": model_summaries,
        "selection": {
            "selected_model_id": selected_model_id,
            "selection_split": "validation",
            "primary_metric": linear_baseline_spec["comparison"]["primary_metric"],
            "tie_breakers": linear_baseline_spec["comparison"]["tie_breakers"],
            "test_used_for_selection": False,
        },
        "fit_trace": fit_trace,
        "feature_schema": feature_schema_rows,
    }

    summary = {
        "linear_baseline_id": linear_baseline_spec["linear_baseline_id"],
        "problem_id": problem_spec["problem_id"],
        "sklearn_version": sklearn.__version__,
        "fit_split": "train",
        "fit_row_count": len(train_ids),
        "selection_split": "validation",
        "final_holdout_split": "test",
        "candidate_model_ids": candidate_ids,
        "selected_model_id": selected_model_id,
        "selection_budget": budget,
        "primary_metric": linear_baseline_spec["comparison"]["primary_metric"],
        "logistic_intercepts": logistic_intercepts,
        "transformed_feature_count": len(feature_schema_rows),
        "coefficient_row_count": len(coefficient_rows),
        "prediction_row_count": len(prediction_rows),
        "validation_metrics": {
            metric: metric_by_model(comparison_rows, "validation", metric)
            for metric in (
                "precision_at_budget",
                "recall_at_budget",
                "average_precision",
                "log_loss",
                "error_cost_at_budget",
                "accuracy_at_0_5",
            )
        },
        "test_metrics": {
            metric: metric_by_model(comparison_rows, "test", metric)
            for metric in (
                "precision_at_budget",
                "recall_at_budget",
                "average_precision",
                "log_loss",
                "error_cost_at_budget",
                "accuracy_at_0_5",
            )
        },
        "top_positive_coefficients": [
            {
                "feature_name": row["feature_name"],
                "coefficient": row["coefficient"],
                "source_column": row["source_column"],
            }
            for row in top_positive
        ],
        "top_negative_coefficients": [
            {
                "feature_name": row["feature_name"],
                "coefficient": row["coefficient"],
                "source_column": row["source_column"],
            }
            for row in top_negative
        ],
        "coefficient_interpretation_limits": linear_baseline_spec["coefficient_policy"][
            "interpretation_limits"
        ],
        "upstream_warnings": upstream_warnings,
        "blocking_errors": blocking_errors,
        "warnings": warnings,
        "readiness_status": "ready_for_tree_diagnostics_lesson"
        if valid
        else "blocked_by_linear_baseline_audit",
    }
    report = {
        "valid": valid,
        "problem_id": problem_spec["problem_id"],
        "summary": summary,
        "comparison": comparison_rows,
        "coefficients": coefficient_rows,
        "predictions": prediction_rows,
        "serialized_spec": serialized_spec,
        "checks": checks,
    }

    if comparison_output_path is not None:
        write_csv(
            comparison_output_path,
            comparison_rows,
            [
                "model_id",
                "model_kind",
                "split",
                "row_count",
                "positive_count",
                "negative_count",
                "selection_budget",
                "log_loss",
                "average_precision",
                "roc_auc",
                "precision_at_budget",
                "recall_at_budget",
                "tp_at_budget",
                "fp_at_budget",
                "fn_at_budget",
                "tn_at_budget",
                "error_cost_at_budget",
                "accuracy_at_0_5",
                "selected_on_validation",
                "selection_rank",
            ],
        )
    if coefficients_output_path is not None:
        write_csv(
            coefficients_output_path,
            coefficient_rows,
            [
                "model_id",
                "feature_position",
                "feature_name",
                "source_route",
                "source_column",
                "source_category",
                "coefficient",
                "abs_coefficient",
                "odds_multiplier_per_unit",
                "direction",
                "model_intercept",
                "regularization",
                "interpretation_limit",
                "coefficient_rank_by_abs",
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
        write_json(serialized_spec_output_path, serialized_spec)
    if report_output_path is not None:
        write_json(report_output_path, report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Train and audit dummy/logistic linear baselines")
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--preprocessing-contract", type=Path, required=True)
    parser.add_argument("--pipeline-spec", type=Path, required=True)
    parser.add_argument("--column-transformer-spec", type=Path, required=True)
    parser.add_argument("--linear-baseline-spec", type=Path, required=True)
    parser.add_argument("--features", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--comparison-output", type=Path)
    parser.add_argument("--coefficients-output", type=Path)
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
            features_path=args.features,
            labels_path=args.labels,
            manifest_path=args.manifest,
            report_output_path=args.output,
            comparison_output_path=args.comparison_output,
            coefficients_output_path=args.coefficients_output,
            predictions_output_path=args.predictions_output,
            serialized_spec_output_path=args.serialized_spec_output,
        )
    except (
        OSError,
        json.JSONDecodeError,
        ColumnTransformerAuditError,
        LinearBaselineError,
        KeyError,
        ValueError,
    ) as error:
        report = {
            "valid": False,
            "summary": {
                "blocking_errors": ["linear_baseline_runtime_error"],
                "warnings": [],
                "readiness_status": "runtime_error",
            },
            "checks": [
                failed(
                    "linear_baseline_runtime_error",
                    str(error),
                    "readable inputs and fit-able dummy/logistic Pipeline baselines",
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
