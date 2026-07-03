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
from sklearn.metrics import accuracy_score, balanced_accuracy_score
from sklearn.utils.class_weight import compute_class_weight

CV_OUTPUT_ROOT = Path(__file__).resolve().parents[2] / "10-cross-validation" / "outputs"
ENSEMBLE_OUTPUT_ROOT = Path(__file__).resolve().parents[2] / "09-ensembles" / "outputs"
LINEAR_OUTPUT_ROOT = Path(__file__).resolve().parents[2] / "07-linear-models" / "outputs"
COLUMN_OUTPUT_ROOT = Path(__file__).resolve().parents[2] / "06-column-transformer" / "outputs"
for output_root in (CV_OUTPUT_ROOT, ENSEMBLE_OUTPUT_ROOT, LINEAR_OUTPUT_ROOT, COLUMN_OUTPUT_ROOT):
    if str(output_root) not in sys.path:
        sys.path.insert(0, str(output_root))

from column_transformer_auditor import (  # noqa: E402
    ColumnTransformerAuditError,
    failed,
    make_frame,
    make_target,
    passed,
    read_csv,
    read_json,
    rounded,
    rows_by_id,
    write_json,
)
from cross_validation_planner import (  # noqa: E402
    CrossValidationPlannerError,
    parse_label,
    run as run_cv_audit,
)
from linear_baseline_trainer import (  # noqa: E402
    LinearBaselineError,
    cost_weights,
    selected_ids_at_budget,
    selection_budget,
    split_ids,
    split_metric_row,
)
from tree_ensemble_comparator import (  # noqa: E402
    TreeEnsembleError,
    build_ensemble_pipeline,
    positive_scores,
)

GENERATED_AT = "2026-07-03T10:00:00+03:00"


class ImbalancePolicyError(ValueError):
    """Raised when imbalance policy inputs cannot be parsed."""


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


def validate_imbalance_policy_spec(
    *,
    problem_spec: dict[str, Any],
    pipeline_spec: dict[str, Any],
    column_transformer_spec: dict[str, Any],
    linear_baseline_spec: dict[str, Any],
    tree_diagnostic_spec: dict[str, Any],
    tree_ensemble_spec: dict[str, Any],
    cv_plan_spec: dict[str, Any],
    imbalance_policy_spec: dict[str, Any],
) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    expected_identity = {
        "problem_id": problem_spec.get("problem_id"),
        "pipeline_id": pipeline_spec.get("pipeline_id"),
        "column_transformer_id": column_transformer_spec.get("column_transformer_id"),
        "linear_baseline_id": linear_baseline_spec.get("linear_baseline_id"),
        "tree_diagnostic_id": tree_diagnostic_spec.get("tree_diagnostic_id"),
        "tree_ensemble_id": tree_ensemble_spec.get("tree_ensemble_id"),
        "cv_plan_id": cv_plan_spec.get("cv_plan_id"),
    }
    for field, expected in expected_identity.items():
        if imbalance_policy_spec.get(field) != expected:
            errors.append(
                {
                    "field": field,
                    "observed": imbalance_policy_spec.get(field),
                    "expected": expected,
                }
            )

    expected_splits = {
        "fit_split": "train",
        "selection_split": "validation",
        "final_holdout_split": "test",
    }
    for field, expected in expected_splits.items():
        if imbalance_policy_spec.get(field) != expected:
            errors.append(
                {"field": field, "observed": imbalance_policy_spec.get(field), "expected": expected}
            )
    if imbalance_policy_spec.get("score_type") != column_transformer_spec.get("score_type"):
        errors.append(
            {
                "field": "score_type",
                "observed": imbalance_policy_spec.get("score_type"),
                "expected": column_transformer_spec.get("score_type"),
            }
        )

    distribution = imbalance_policy_spec.get("distribution")
    if not isinstance(distribution, dict):
        errors.append({"field": "distribution", "reason": "object required"})
    else:
        if distribution.get("label_column") != problem_spec["target_definition"]["target_column"]:
            errors.append(
                {
                    "field": "distribution.label_column",
                    "observed": distribution.get("label_column"),
                    "expected": problem_spec["target_definition"]["target_column"],
                }
            )
        if distribution.get("warn_if_positive_rate_below") is None:
            errors.append(
                {"field": "distribution.warn_if_positive_rate_below", "reason": "required"}
            )

    trap = imbalance_policy_spec.get("accuracy_trap")
    if not isinstance(trap, dict):
        errors.append({"field": "accuracy_trap", "reason": "object required"})
    else:
        expected_trap = {
            "strategy": "predict_negative_class",
            "accuracy_is_diagnostic_only": True,
            "blocking_if_primary_metric_accuracy": True,
            "must_report_positive_recall": True,
            "must_report_balanced_accuracy": True,
        }
        for field, expected in expected_trap.items():
            if trap.get(field) != expected:
                errors.append(
                    {
                        "field": f"accuracy_trap.{field}",
                        "observed": trap.get(field),
                        "expected": expected,
                    }
                )
        if trap.get("evaluate_splits") != ["validation", "test"]:
            errors.append(
                {
                    "field": "accuracy_trap.evaluate_splits",
                    "observed": trap.get("evaluate_splits"),
                    "expected": ["validation", "test"],
                }
            )

    class_weight_policy = imbalance_policy_spec.get("class_weight_policy")
    if not isinstance(class_weight_policy, dict):
        errors.append({"field": "class_weight_policy", "reason": "object required"})
    else:
        expected_candidate = tree_ensemble_spec.get("candidate", {})
        if class_weight_policy.get("source_model_id") != expected_candidate.get("model_id"):
            errors.append(
                {
                    "field": "class_weight_policy.source_model_id",
                    "observed": class_weight_policy.get("source_model_id"),
                    "expected": expected_candidate.get("model_id"),
                }
            )
        if class_weight_policy.get("class_weight") != "balanced":
            errors.append(
                {
                    "field": "class_weight_policy.class_weight",
                    "observed": class_weight_policy.get("class_weight"),
                    "expected": "balanced",
                }
            )
        if class_weight_policy.get("compute_on") != "fit_split_only":
            errors.append(
                {
                    "field": "class_weight_policy.compute_on",
                    "observed": class_weight_policy.get("compute_on"),
                    "expected": "fit_split_only",
                }
            )
        if class_weight_policy.get("forbid_computing_weights_on_validation_or_test") is not True:
            errors.append(
                {
                    "field": "class_weight_policy.forbid_computing_weights_on_validation_or_test",
                    "observed": class_weight_policy.get(
                        "forbid_computing_weights_on_validation_or_test"
                    ),
                    "expected": True,
                }
            )

    resampling_policy = imbalance_policy_spec.get("resampling_policy")
    if not isinstance(resampling_policy, dict):
        errors.append({"field": "resampling_policy", "reason": "object required"})
    else:
        if resampling_policy.get("forbid_resampling_validation_or_test") is not True:
            errors.append(
                {
                    "field": "resampling_policy.forbid_resampling_validation_or_test",
                    "observed": resampling_policy.get("forbid_resampling_validation_or_test"),
                    "expected": True,
                }
            )

    threshold_policy = imbalance_policy_spec.get("threshold_policy")
    if not isinstance(threshold_policy, dict):
        errors.append({"field": "threshold_policy", "reason": "object required"})
    else:
        expected_threshold = {
            "selection_data": "validation",
            "budget_source": "problem_spec.decision_budget.max_actions",
            "primary_decision_rule": "rank_top_k_within_scoring_batch",
            "fixed_threshold_role": "diagnostic_only_until_calibration",
        }
        for field, expected in expected_threshold.items():
            if threshold_policy.get(field) != expected:
                errors.append(
                    {
                        "field": f"threshold_policy.{field}",
                        "observed": threshold_policy.get(field),
                        "expected": expected,
                    }
                )
        thresholds = threshold_policy.get("candidate_thresholds")
        if not isinstance(thresholds, list) or not thresholds:
            errors.append({"field": "threshold_policy.candidate_thresholds", "reason": "required"})

    comparison = imbalance_policy_spec.get("comparison")
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
        forbidden = set(comparison.get("forbidden_primary_metrics") or [])
        if not {"accuracy", "accuracy_at_0_5"}.issubset(forbidden):
            errors.append(
                {
                    "field": "comparison.forbidden_primary_metrics",
                    "observed": sorted(forbidden),
                    "expected": ["accuracy", "accuracy_at_0_5"],
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

    audit_policy = imbalance_policy_spec.get("audit_policy")
    if not isinstance(audit_policy, dict):
        errors.append({"field": "audit_policy", "reason": "object required"})
    else:
        for field in (
            "require_cv_handoff",
            "require_class_distribution_report",
            "require_accuracy_trap_report",
            "require_class_weight_fit_scope",
            "require_threshold_budget_report",
            "forbid_accuracy_as_primary_metric",
            "forbid_resampling_validation_or_test",
            "forbid_threshold_selection_on_test",
            "forbid_test_selection",
        ):
            if audit_policy.get(field) is not True:
                errors.append(
                    {
                        "field": f"audit_policy.{field}",
                        "observed": audit_policy.get(field),
                        "expected": True,
                    }
                )

    output = imbalance_policy_spec.get("output")
    if not isinstance(output, dict):
        errors.append({"field": "output", "reason": "object required"})
    else:
        for field in (
            "distribution_file",
            "baseline_trap_file",
            "threshold_file",
            "prediction_file",
            "audit_file",
            "report_file",
            "serialized_spec_file",
        ):
            if not output.get(field):
                errors.append({"field": f"output.{field}", "reason": "required"})

    if errors:
        return failed(
            "imbalance_policy_spec_declares_accuracy_weight_threshold_contract",
            len(errors),
            "imbalance policy with accuracy trap, fit-only class weights and validation threshold",
            errors,
        )
    return passed(
        "imbalance_policy_spec_declares_accuracy_weight_threshold_contract",
        {
            "imbalance_policy_id": imbalance_policy_spec["imbalance_policy_id"],
            "primary_metric": imbalance_policy_spec["comparison"]["primary_metric"],
            "class_weight": imbalance_policy_spec["class_weight_policy"]["class_weight"],
        },
        "imbalance policy contract is explicit",
    )


def label_for_id(snapshot_id: str, labels_by_id: dict[str, dict[str, str]]) -> int:
    return parse_label(labels_by_id[snapshot_id]["churned_14d"])


def class_counts(ids: list[str], labels_by_id: dict[str, dict[str, str]]) -> dict[str, Any]:
    labels = [label_for_id(snapshot_id, labels_by_id) for snapshot_id in ids]
    positives = sum(labels)
    negatives = len(labels) - positives
    positive_rate = positives / len(labels) if labels else 0.0
    ratio = None if positives == 0 else negatives / positives
    return {
        "row_count": len(labels),
        "positive_count": positives,
        "negative_count": negatives,
        "positive_rate": rounded(positive_rate),
        "negative_to_positive_ratio": None if ratio is None else rounded(ratio),
    }


def build_distribution_rows(
    *,
    manifest_rows: list[dict[str, str]],
    fold_rows: list[dict[str, str]],
    labels_by_id: dict[str, dict[str, str]],
    warning_threshold: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    split_map = {"all_eligible": [row["snapshot_id"] for row in manifest_rows]}
    for split in ("train", "validation", "test"):
        split_map[split] = [row["snapshot_id"] for row in manifest_rows if row["split"] == split]
    for group_id, ids in split_map.items():
        counts = class_counts(ids, labels_by_id)
        rows.append(
            {
                "scope": "split",
                "group_id": group_id,
                **counts,
                "warning_triggered": counts["positive_rate"] < warning_threshold,
            }
        )

    role_rows: dict[str, list[int]] = {"cv_train": [], "cv_validation": []}
    for row in fold_rows:
        role_rows[row["cv_role"]].append(parse_label(row["label"]))
    for role, labels in role_rows.items():
        positives = sum(labels)
        negatives = len(labels) - positives
        positive_rate = positives / len(labels) if labels else 0.0
        ratio = None if positives == 0 else negatives / positives
        rows.append(
            {
                "scope": "cv_role",
                "group_id": role,
                "row_count": len(labels),
                "positive_count": positives,
                "negative_count": negatives,
                "positive_rate": rounded(positive_rate),
                "negative_to_positive_ratio": None if ratio is None else rounded(ratio),
                "warning_triggered": positive_rate < warning_threshold,
            }
        )
    return rows


def confusion_counts(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, int]:
    return {
        "tp": int(((y_true == 1) & (y_pred == 1)).sum()),
        "fp": int(((y_true == 0) & (y_pred == 1)).sum()),
        "fn": int(((y_true == 1) & (y_pred == 0)).sum()),
        "tn": int(((y_true == 0) & (y_pred == 0)).sum()),
    }


def binary_metrics_from_predictions(
    *,
    split: str,
    ids: list[str],
    y_true: np.ndarray,
    y_pred: np.ndarray,
    false_positive_cost: float,
    false_negative_cost: float,
) -> dict[str, Any]:
    counts = confusion_counts(y_true, y_pred)
    positive_count = int(y_true.sum())
    negative_count = int(len(y_true) - positive_count)
    selected = int(y_pred.sum())
    precision = None if selected == 0 else counts["tp"] / selected
    recall = None if positive_count == 0 else counts["tp"] / positive_count
    negative_recall = None if negative_count == 0 else counts["tn"] / negative_count
    return {
        "split": split,
        "row_count": len(ids),
        "positive_count": positive_count,
        "negative_count": negative_count,
        "action_count": selected,
        "accuracy": rounded(float(accuracy_score(y_true, y_pred))),
        "balanced_accuracy": rounded(float(balanced_accuracy_score(y_true, y_pred))),
        "positive_recall": None if recall is None else rounded(recall),
        "negative_recall": None if negative_recall is None else rounded(negative_recall),
        "precision": None if precision is None else rounded(precision),
        "tp": counts["tp"],
        "fp": counts["fp"],
        "fn": counts["fn"],
        "tn": counts["tn"],
        "error_cost": rounded(
            counts["fp"] * false_positive_cost + counts["fn"] * false_negative_cost
        ),
    }


def build_accuracy_trap_rows(
    *,
    split_to_ids: dict[str, list[str]],
    labels_by_id: dict[str, dict[str, str]],
    false_positive_cost: float,
    false_negative_cost: float,
    baseline_model_id: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for split in ("validation", "test"):
        ids = split_to_ids[split]
        y_true = np.array([label_for_id(snapshot_id, labels_by_id) for snapshot_id in ids])
        y_pred = np.zeros(len(ids), dtype=int)
        metrics = binary_metrics_from_predictions(
            split=split,
            ids=ids,
            y_true=y_true,
            y_pred=y_pred,
            false_positive_cost=false_positive_cost,
            false_negative_cost=false_negative_cost,
        )
        rows.append(
            {
                "model_id": baseline_model_id,
                "strategy": "predict_negative_class",
                **metrics,
                "accuracy_role": "diagnostic_only",
                "trap_detected": metrics["accuracy"] >= 0.75 and metrics["positive_recall"] == 0.0,
            }
        )
    return rows


def build_candidate_spec(
    tree_ensemble_spec: dict[str, Any], *, model_id: str, class_weight: str | None
) -> dict[str, Any]:
    candidate_spec = json.loads(json.dumps(tree_ensemble_spec))
    candidate_spec["candidate"]["model_id"] = model_id
    candidate_spec["candidate"]["params"]["class_weight"] = class_weight
    return candidate_spec


def candidate_metric_rows(
    *,
    candidate_spec: dict[str, Any],
    column_transformer_spec: dict[str, Any],
    problem_spec: dict[str, Any],
    feature_rows_by_id: dict[str, dict[str, str]],
    labels_by_id: dict[str, dict[str, str]],
    train_ids: list[str],
    split_to_ids: dict[str, list[str]],
    budget: int,
    false_positive_cost: float,
    false_negative_cost: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    model_id = candidate_spec["candidate"]["model_id"]
    model_kind = candidate_spec["candidate"]["kind"]
    class_weight = candidate_spec["candidate"]["params"].get("class_weight")
    pipeline = build_ensemble_pipeline(candidate_spec, column_transformer_spec)
    pipeline.fit(
        make_frame(train_ids, feature_rows_by_id, column_transformer_spec),
        make_target(train_ids, labels_by_id, problem_spec),
    )
    metric_rows: list[dict[str, Any]] = []
    prediction_rows: list[dict[str, Any]] = []
    scores_by_split: dict[str, Any] = {}
    for split in ("validation", "test"):
        ids = split_to_ids[split]
        X = make_frame(ids, feature_rows_by_id, column_transformer_spec)
        y_true = make_target(ids, labels_by_id, problem_spec)
        scores = positive_scores(pipeline, X)
        metric = split_metric_row(
            model_id=model_id,
            model_kind=model_kind,
            split=split,
            ids=ids,
            y_true=y_true,
            scores=scores,
            budget=min(budget, len(ids)),
            false_positive_cost=false_positive_cost,
            false_negative_cost=false_negative_cost,
        )
        y_pred_threshold = (scores >= 0.5).astype(int)
        metric["balanced_accuracy_at_0_5"] = rounded(
            float(balanced_accuracy_score(y_true, y_pred_threshold))
        )
        metric["class_weight"] = "none" if class_weight is None else str(class_weight)
        metric["selected_ids"] = ",".join(sorted(selected_ids_at_budget(ids, scores, budget)))
        metric_rows.append(metric)

        selected_set = selected_ids_at_budget(ids, scores, budget)
        for snapshot_id, label, score in zip(ids, y_true.tolist(), scores.tolist(), strict=True):
            prediction_rows.append(
                {
                    "split": split,
                    "snapshot_id": snapshot_id,
                    "model_id": model_id,
                    "model_kind": model_kind,
                    "class_weight": "none" if class_weight is None else str(class_weight),
                    "score": rounded(float(score)),
                    "score_type": candidate_spec["score_type"],
                    "actual_label": int(label),
                    "selected_at_budget": int(snapshot_id in selected_set),
                    "predicted_at_0_5": int(score >= 0.5),
                    "trained_on_split": "train",
                    "generated_at": GENERATED_AT,
                }
            )
        scores_by_split[split] = {"ids": ids, "scores": scores, "labels": y_true}
    return metric_rows, prediction_rows, scores_by_split


def rank_validation_candidates(
    rows: list[dict[str, Any]], primary_metric: str
) -> list[dict[str, Any]]:
    ranked = sorted(
        [row for row in rows if row["split"] == "validation"],
        key=lambda row: (
            -float(row[primary_metric]),
            float(row["error_cost_at_budget"]),
            float(row["log_loss"]),
            row["model_id"],
        ),
    )
    rank_by_model = {row["model_id"]: rank for rank, row in enumerate(ranked, start=1)}
    selected_by_model = {row["model_id"]: rank == 1 for rank, row in enumerate(ranked, start=1)}
    enriched: list[dict[str, Any]] = []
    for row in rows:
        copied = dict(row)
        copied["selection_rank"] = rank_by_model.get(row["model_id"], "")
        copied["selected_on_validation"] = selected_by_model.get(row["model_id"], False)
        enriched.append(copied)
    return enriched


def threshold_metrics(
    *,
    split: str,
    ids: list[str],
    y_true: np.ndarray,
    scores: np.ndarray,
    threshold: float | None,
    budget: int,
    false_positive_cost: float,
    false_negative_cost: float,
) -> dict[str, Any]:
    if threshold is None:
        selected_ids = selected_ids_at_budget(ids, scores, budget)
        y_pred = np.array([1 if snapshot_id in selected_ids else 0 for snapshot_id in ids])
        decision_rule = "rank_top_k_within_scoring_batch"
        threshold_value: float | str = ""
    else:
        y_pred = (scores >= threshold).astype(int)
        decision_rule = "fixed_threshold"
        threshold_value = threshold
    metrics = binary_metrics_from_predictions(
        split=split,
        ids=ids,
        y_true=y_true,
        y_pred=y_pred,
        false_positive_cost=false_positive_cost,
        false_negative_cost=false_negative_cost,
    )
    selected = [
        snapshot_id
        for snapshot_id, pred in zip(ids, y_pred.tolist(), strict=True)
        if int(pred) == 1
    ]
    return {
        "decision_rule": decision_rule,
        "threshold": threshold_value,
        **metrics,
        "selection_budget": budget,
        "budget_exceeded": metrics["action_count"] > budget,
        "selected_ids": ",".join(selected),
    }


def build_threshold_rows(
    *,
    selected_model_id: str,
    scores_by_split: dict[str, Any],
    thresholds: list[float],
    budget: int,
    false_positive_cost: float,
    false_negative_cost: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for split in ("validation", "test"):
        payload = scores_by_split[split]
        rows.append(
            {
                "model_id": selected_model_id,
                **threshold_metrics(
                    split=split,
                    ids=payload["ids"],
                    y_true=payload["labels"],
                    scores=payload["scores"],
                    threshold=None,
                    budget=min(budget, len(payload["ids"])),
                    false_positive_cost=false_positive_cost,
                    false_negative_cost=false_negative_cost,
                ),
                "threshold_role": "primary_budget_rule",
            }
        )
        for threshold in thresholds:
            rows.append(
                {
                    "model_id": selected_model_id,
                    **threshold_metrics(
                        split=split,
                        ids=payload["ids"],
                        y_true=payload["labels"],
                        scores=payload["scores"],
                        threshold=float(threshold),
                        budget=min(budget, len(payload["ids"])),
                        false_positive_cost=false_positive_cost,
                        false_negative_cost=false_negative_cost,
                    ),
                    "threshold_role": "diagnostic_only_until_calibration",
                }
            )
    return rows


def build_audit_rows(checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for check in checks:
        rows.append(
            {
                "check_id": check["id"],
                "severity": check["severity"],
                "valid": check["valid"],
                "observed": json.dumps(json_ready(check["observed"]), ensure_ascii=False),
                "expected": json.dumps(json_ready(check["expected"]), ensure_ascii=False),
            }
        )
    return rows


def run(
    *,
    spec_path: Path,
    preprocessing_contract_path: Path,
    pipeline_spec_path: Path,
    column_transformer_spec_path: Path,
    linear_baseline_spec_path: Path,
    tree_diagnostic_spec_path: Path,
    tree_ensemble_spec_path: Path,
    cv_plan_spec_path: Path,
    imbalance_policy_spec_path: Path,
    features_path: Path,
    labels_path: Path,
    manifest_path: Path,
    cv_fold_manifest_path: Path,
    report_output_path: Path | None = None,
    distribution_output_path: Path | None = None,
    baseline_trap_output_path: Path | None = None,
    threshold_output_path: Path | None = None,
    predictions_output_path: Path | None = None,
    audit_output_path: Path | None = None,
    serialized_spec_output_path: Path | None = None,
) -> dict[str, Any]:
    problem_spec = read_json(spec_path)
    pipeline_spec = read_json(pipeline_spec_path)
    column_transformer_spec = read_json(column_transformer_spec_path)
    linear_baseline_spec = read_json(linear_baseline_spec_path)
    tree_diagnostic_spec = read_json(tree_diagnostic_spec_path)
    tree_ensemble_spec = read_json(tree_ensemble_spec_path)
    cv_plan_spec = read_json(cv_plan_spec_path)
    imbalance_policy_spec = read_json(imbalance_policy_spec_path)
    feature_rows, _feature_columns = read_csv(features_path)
    labels, _label_columns = read_csv(labels_path)
    manifest_rows, _manifest_columns = read_csv(manifest_path)
    fold_rows, _fold_columns = read_csv(cv_fold_manifest_path)

    labels_by_id = rows_by_id(labels)
    feature_rows_by_id = rows_by_id(feature_rows)
    checks: list[dict[str, Any]] = [
        validate_imbalance_policy_spec(
            problem_spec=problem_spec,
            pipeline_spec=pipeline_spec,
            column_transformer_spec=column_transformer_spec,
            linear_baseline_spec=linear_baseline_spec,
            tree_diagnostic_spec=tree_diagnostic_spec,
            tree_ensemble_spec=tree_ensemble_spec,
            cv_plan_spec=cv_plan_spec,
            imbalance_policy_spec=imbalance_policy_spec,
        )
    ]

    cv_report = run_cv_audit(
        spec_path=spec_path,
        preprocessing_contract_path=preprocessing_contract_path,
        pipeline_spec_path=pipeline_spec_path,
        column_transformer_spec_path=column_transformer_spec_path,
        linear_baseline_spec_path=linear_baseline_spec_path,
        tree_diagnostic_spec_path=tree_diagnostic_spec_path,
        tree_ensemble_spec_path=tree_ensemble_spec_path,
        cv_plan_spec_path=cv_plan_spec_path,
        features_path=features_path,
        labels_path=labels_path,
        manifest_path=manifest_path,
        cv_fold_manifest_path=cv_fold_manifest_path,
    )
    if cv_report.get("valid"):
        checks.append(
            passed(
                "upstream_cv_audit_is_valid",
                {
                    "cv_plan_id": cv_plan_spec.get("cv_plan_id"),
                    "readiness_status": cv_report["summary"].get("readiness_status"),
                },
                "cross-validation handoff is valid",
            )
        )
    else:
        checks.append(
            failed(
                "upstream_cv_audit_is_valid",
                cv_report.get("summary", {}).get("blocking_errors", []),
                "valid cross-validation report before imbalance policy",
                cv_report.get("checks", []),
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
                "imbalance_policy_id": imbalance_policy_spec.get("imbalance_policy_id"),
                "blocking_errors": blocking_errors,
                "warnings": [],
                "readiness_status": "blocked_before_imbalance_evaluation",
            },
            "checks": checks,
        }
        if report_output_path is not None:
            write_json(report_output_path, json_ready(report))
        return report

    warning_threshold = float(
        imbalance_policy_spec["distribution"]["warn_if_positive_rate_below"]
    )
    distribution_rows = build_distribution_rows(
        manifest_rows=manifest_rows,
        fold_rows=fold_rows,
        labels_by_id=labels_by_id,
        warning_threshold=warning_threshold,
    )
    checks.append(
        passed(
            "imbalance_class_distribution_reported",
            {"rows": len(distribution_rows)},
            "class distribution is reported by split and CV role",
        )
    )
    low_positive = [row for row in distribution_rows if row["warning_triggered"]]
    if low_positive:
        checks.append(
            failed(
                "imbalance_positive_rate_below_threshold",
                [
                    {
                        "scope": row["scope"],
                        "group_id": row["group_id"],
                        "positive_rate": row["positive_rate"],
                    }
                    for row in low_positive
                ],
                f">= {warning_threshold} positive rate for stable tiny diagnostics",
                severity="warning",
            )
        )

    split_to_ids = {
        "train": split_ids(manifest_rows, "train"),
        "validation": split_ids(manifest_rows, "validation"),
        "test": split_ids(manifest_rows, "test"),
    }
    budget = selection_budget(problem_spec)
    false_positive_cost, false_negative_cost = cost_weights(problem_spec)
    baseline_trap_rows = build_accuracy_trap_rows(
        split_to_ids=split_to_ids,
        labels_by_id=labels_by_id,
        false_positive_cost=false_positive_cost,
        false_negative_cost=false_negative_cost,
        baseline_model_id=imbalance_policy_spec["accuracy_trap"]["baseline_model_id"],
    )
    checks.append(
        passed(
            "imbalance_accuracy_trap_reported",
            {"rows": len(baseline_trap_rows)},
            "accuracy trap report includes recall and balanced accuracy",
        )
    )
    trap_rows = [row for row in baseline_trap_rows if row["trap_detected"]]
    if trap_rows:
        checks.append(
            failed(
                "accuracy_trap_detected_on_test",
                [
                    {
                        "split": row["split"],
                        "accuracy": row["accuracy"],
                        "positive_recall": row["positive_recall"],
                    }
                    for row in trap_rows
                ],
                "accuracy should not be interpreted without positive recall",
                severity="warning",
            )
        )

    train_labels = make_target(split_to_ids["train"], labels_by_id, problem_spec)
    class_weight_values = compute_class_weight(
        class_weight="balanced",
        classes=np.array([0, 1]),
        y=train_labels,
    )
    class_weight_report = {
        "computed_on": "train",
        "class_0": rounded(float(class_weight_values[0])),
        "class_1": rounded(float(class_weight_values[1])),
        "formula": imbalance_policy_spec["class_weight_policy"]["formula"],
    }
    checks.append(
        passed(
            "imbalance_class_weight_computed_on_fit_split",
            class_weight_report,
            "class weights are computed on fit split only",
        )
    )
    checks.append(
        passed(
            "imbalance_accuracy_not_primary_metric",
            {
                "primary_metric": imbalance_policy_spec["comparison"]["primary_metric"],
                "forbidden": imbalance_policy_spec["comparison"]["forbidden_primary_metrics"],
            },
            "accuracy is diagnostic-only for imbalance",
        )
    )
    checks.append(
        passed(
            "imbalance_resampling_not_applied_to_validation_or_test",
            imbalance_policy_spec["resampling_policy"],
            "no validation/test resampling is allowed",
        )
    )
    checks.append(
        passed(
            "imbalance_threshold_selection_uses_validation",
            imbalance_policy_spec["threshold_policy"]["selection_data"],
            "validation",
        )
    )

    candidates = [
        build_candidate_spec(
            tree_ensemble_spec,
            model_id="random_forest_depth2_unweighted",
            class_weight=None,
        ),
        build_candidate_spec(
            tree_ensemble_spec,
            model_id=imbalance_policy_spec["class_weight_policy"]["candidate_model_id"],
            class_weight="balanced",
        ),
    ]
    comparison_rows: list[dict[str, Any]] = []
    prediction_rows: list[dict[str, Any]] = []
    scores_by_model: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        metrics, predictions, scores_by_split = candidate_metric_rows(
            candidate_spec=candidate,
            column_transformer_spec=column_transformer_spec,
            problem_spec=problem_spec,
            feature_rows_by_id=feature_rows_by_id,
            labels_by_id=labels_by_id,
            train_ids=split_to_ids["train"],
            split_to_ids=split_to_ids,
            budget=budget,
            false_positive_cost=false_positive_cost,
            false_negative_cost=false_negative_cost,
        )
        comparison_rows.extend(metrics)
        prediction_rows.extend(predictions)
        scores_by_model[candidate["candidate"]["model_id"]] = scores_by_split

    comparison_rows = rank_validation_candidates(
        comparison_rows, imbalance_policy_spec["comparison"]["primary_metric"]
    )
    selected_model_id = next(
        row["model_id"]
        for row in comparison_rows
        if row["split"] == "validation" and row["selected_on_validation"]
    )
    threshold_rows = build_threshold_rows(
        selected_model_id=selected_model_id,
        scores_by_split=scores_by_model[selected_model_id],
        thresholds=imbalance_policy_spec["threshold_policy"]["candidate_thresholds"],
        budget=budget,
        false_positive_cost=false_positive_cost,
        false_negative_cost=false_negative_cost,
    )
    checks.append(
        passed(
            "imbalance_threshold_budget_reported",
            {"rows": len(threshold_rows), "selected_model_id": selected_model_id},
            "threshold and top-k budget diagnostics are reported",
        )
    )

    validation_by_model = {
        row["model_id"]: row for row in comparison_rows if row["split"] == "validation"
    }
    test_by_model = {row["model_id"]: row for row in comparison_rows if row["split"] == "test"}
    weighted_validation = validation_by_model[selected_model_id]
    weighted_test = test_by_model[selected_model_id]
    if weighted_validation["precision_at_budget"] > validation_by_model[
        "random_forest_depth2_unweighted"
    ]["precision_at_budget"] and weighted_test["precision_at_budget"] == 0.0:
        checks.append(
            failed(
                "class_weight_improves_validation_not_test_expected",
                {
                    "validation_precision_at_budget": weighted_validation["precision_at_budget"],
                    "test_precision_at_budget": weighted_test["precision_at_budget"],
                },
                "class weight improvement should be validated beyond tiny validation",
                severity="warning",
            )
        )
    fixed_threshold_violations = [
        row
        for row in threshold_rows
        if row["split"] == "test"
        and row["decision_rule"] == "fixed_threshold"
        and row["budget_exceeded"]
    ]
    if fixed_threshold_violations:
        checks.append(
            failed(
                "fixed_threshold_can_exceed_offer_budget",
                [
                    {
                        "threshold": row["threshold"],
                        "action_count": row["action_count"],
                        "selection_budget": row["selection_budget"],
                    }
                    for row in fixed_threshold_violations
                ],
                "fixed threshold should not be assumed to preserve batch budget",
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
    serialized_spec = {
        "imbalance_policy_id": imbalance_policy_spec["imbalance_policy_id"],
        "problem_id": problem_spec["problem_id"],
        "sklearn_version": sklearn.__version__,
        "class_weight_policy": {
            **imbalance_policy_spec["class_weight_policy"],
            "computed_weights": class_weight_report,
        },
        "resampling_policy": imbalance_policy_spec["resampling_policy"],
        "threshold_policy": imbalance_policy_spec["threshold_policy"],
        "selected_model_id": selected_model_id,
        "fit_trace": [
            {
                "event": "pipeline.fit",
                "model_id": candidate["candidate"]["model_id"],
                "class_weight": candidate["candidate"]["params"].get("class_weight"),
                "fit_split": "train",
                "fit_ids": split_to_ids["train"],
                "validation_ids_seen": [],
                "test_ids_seen": [],
            }
            for candidate in candidates
        ],
        "test_used_for_selection": False,
    }
    test_trap = next(row for row in baseline_trap_rows if row["split"] == "test")
    topk_test = next(
        row
        for row in threshold_rows
        if row["split"] == "test" and row["decision_rule"] == "rank_top_k_within_scoring_batch"
    )
    fixed_threshold_05_test = next(
        row
        for row in threshold_rows
        if row["split"] == "test"
        and row["decision_rule"] == "fixed_threshold"
        and row["threshold"] == 0.5
    )
    summary = {
        "imbalance_policy_id": imbalance_policy_spec["imbalance_policy_id"],
        "problem_id": problem_spec["problem_id"],
        "sklearn_version": sklearn.__version__,
        "selected_model_id": selected_model_id,
        "selected_model_class_weight": "balanced",
        "primary_metric": imbalance_policy_spec["comparison"]["primary_metric"],
        "fit_positive_rate": class_counts(split_to_ids["train"], labels_by_id)["positive_rate"],
        "test_positive_rate": class_counts(split_to_ids["test"], labels_by_id)["positive_rate"],
        "always_negative_test_accuracy": test_trap["accuracy"],
        "always_negative_test_positive_recall": test_trap["positive_recall"],
        "validation_precision_at_budget": weighted_validation["precision_at_budget"],
        "test_precision_at_budget": weighted_test["precision_at_budget"],
        "test_top_k_selected_ids": topk_test["selected_ids"].split(","),
        "test_fixed_threshold_0_5_action_count": fixed_threshold_05_test["action_count"],
        "test_used_for_selection": False,
        "blocking_errors": blocking_errors,
        "warnings": warnings,
        "readiness_status": "ready_for_calibration_lesson"
        if valid
        else "blocked_by_imbalance_policy_audit",
    }
    report = {
        "valid": valid,
        "problem_id": problem_spec["problem_id"],
        "summary": summary,
        "distribution": distribution_rows,
        "baseline_trap": baseline_trap_rows,
        "comparison": comparison_rows,
        "thresholds": threshold_rows,
        "predictions": prediction_rows,
        "audit": build_audit_rows(checks),
        "serialized_spec": serialized_spec,
        "checks": checks,
    }

    if distribution_output_path is not None:
        write_csv(
            distribution_output_path,
            distribution_rows,
            [
                "scope",
                "group_id",
                "row_count",
                "positive_count",
                "negative_count",
                "positive_rate",
                "negative_to_positive_ratio",
                "warning_triggered",
            ],
        )
    if baseline_trap_output_path is not None:
        write_csv(
            baseline_trap_output_path,
            baseline_trap_rows,
            [
                "model_id",
                "strategy",
                "split",
                "row_count",
                "positive_count",
                "negative_count",
                "action_count",
                "accuracy",
                "balanced_accuracy",
                "positive_recall",
                "negative_recall",
                "precision",
                "tp",
                "fp",
                "fn",
                "tn",
                "error_cost",
                "accuracy_role",
                "trap_detected",
            ],
        )
    if threshold_output_path is not None:
        write_csv(
            threshold_output_path,
            threshold_rows,
            [
                "model_id",
                "decision_rule",
                "threshold",
                "split",
                "row_count",
                "positive_count",
                "negative_count",
                "action_count",
                "accuracy",
                "balanced_accuracy",
                "positive_recall",
                "negative_recall",
                "precision",
                "tp",
                "fp",
                "fn",
                "tn",
                "error_cost",
                "selection_budget",
                "budget_exceeded",
                "selected_ids",
                "threshold_role",
            ],
        )
    if predictions_output_path is not None:
        write_csv(
            predictions_output_path,
            prediction_rows,
            [
                "split",
                "snapshot_id",
                "model_id",
                "model_kind",
                "class_weight",
                "score",
                "score_type",
                "actual_label",
                "selected_at_budget",
                "predicted_at_0_5",
                "trained_on_split",
                "generated_at",
            ],
        )
    if audit_output_path is not None:
        write_csv(
            audit_output_path,
            report["audit"],
            ["check_id", "severity", "valid", "observed", "expected"],
        )
    if serialized_spec_output_path is not None:
        write_json(serialized_spec_output_path, json_ready(serialized_spec))
    if report_output_path is not None:
        write_json(report_output_path, json_ready(report))
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate imbalance policy for ML baseline")
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--preprocessing-contract", type=Path, required=True)
    parser.add_argument("--pipeline-spec", type=Path, required=True)
    parser.add_argument("--column-transformer-spec", type=Path, required=True)
    parser.add_argument("--linear-baseline-spec", type=Path, required=True)
    parser.add_argument("--tree-diagnostic-spec", type=Path, required=True)
    parser.add_argument("--tree-ensemble-spec", type=Path, required=True)
    parser.add_argument("--cv-plan-spec", type=Path, required=True)
    parser.add_argument("--imbalance-policy-spec", type=Path, required=True)
    parser.add_argument("--features", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--cv-fold-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--distribution-output", type=Path)
    parser.add_argument("--baseline-trap-output", type=Path)
    parser.add_argument("--threshold-output", type=Path)
    parser.add_argument("--predictions-output", type=Path)
    parser.add_argument("--audit-output", type=Path)
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
            cv_plan_spec_path=args.cv_plan_spec,
            imbalance_policy_spec_path=args.imbalance_policy_spec,
            features_path=args.features,
            labels_path=args.labels,
            manifest_path=args.manifest,
            cv_fold_manifest_path=args.cv_fold_manifest,
            report_output_path=args.output,
            distribution_output_path=args.distribution_output,
            baseline_trap_output_path=args.baseline_trap_output,
            threshold_output_path=args.threshold_output,
            predictions_output_path=args.predictions_output,
            audit_output_path=args.audit_output,
            serialized_spec_output_path=args.serialized_spec_output,
        )
    except (
        OSError,
        json.JSONDecodeError,
        ColumnTransformerAuditError,
        LinearBaselineError,
        TreeEnsembleError,
        CrossValidationPlannerError,
        ImbalancePolicyError,
        KeyError,
        ValueError,
    ) as error:
        report = {
            "valid": False,
            "summary": {
                "blocking_errors": ["imbalance_policy_runtime_error"],
                "warnings": [],
                "readiness_status": "runtime_error",
            },
            "checks": [
                failed(
                    "imbalance_policy_runtime_error",
                    str(error),
                    "readable inputs and fit-able imbalance policy candidates",
                )
            ],
        }
        if args.output is not None:
            write_json(args.output, json_ready(report))

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
