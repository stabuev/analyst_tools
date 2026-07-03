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
from sklearn.metrics import brier_score_loss, log_loss

IMBALANCE_OUTPUT_ROOT = Path(__file__).resolve().parents[2] / "11-imbalanced-data" / "outputs"
LINEAR_OUTPUT_ROOT = Path(__file__).resolve().parents[2] / "07-linear-models" / "outputs"
COLUMN_OUTPUT_ROOT = Path(__file__).resolve().parents[2] / "06-column-transformer" / "outputs"
for output_root in (IMBALANCE_OUTPUT_ROOT, LINEAR_OUTPUT_ROOT, COLUMN_OUTPUT_ROOT):
    if str(output_root) not in sys.path:
        sys.path.insert(0, str(output_root))

from column_transformer_auditor import (  # noqa: E402
    ColumnTransformerAuditError,
    failed,
    passed,
    read_json,
    rounded,
    write_json,
)
from imbalance_policy_evaluator import (  # noqa: E402
    ImbalancePolicyError,
    binary_metrics_from_predictions,
    json_ready,
    run as run_imbalance_audit,
)
from linear_baseline_trainer import (  # noqa: E402
    LinearBaselineError,
    cost_weights,
    selected_ids_at_budget,
    selection_budget,
)

GENERATED_AT = "2026-07-03T10:00:00+03:00"


class CalibrationPolicyError(ValueError):
    """Raised when calibration policy inputs cannot be parsed."""


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def validate_calibration_policy_spec(
    *,
    problem_spec: dict[str, Any],
    pipeline_spec: dict[str, Any],
    column_transformer_spec: dict[str, Any],
    linear_baseline_spec: dict[str, Any],
    tree_diagnostic_spec: dict[str, Any],
    tree_ensemble_spec: dict[str, Any],
    cv_plan_spec: dict[str, Any],
    imbalance_policy_spec: dict[str, Any],
    calibration_policy_spec: dict[str, Any],
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
        "imbalance_policy_id": imbalance_policy_spec.get("imbalance_policy_id"),
    }
    for field, expected in expected_identity.items():
        if calibration_policy_spec.get(field) != expected:
            errors.append(
                {
                    "field": field,
                    "observed": calibration_policy_spec.get(field),
                    "expected": expected,
                }
            )

    expected_splits = {
        "fit_split": "train",
        "calibration_split": "validation",
        "evaluation_split": "test",
    }
    for field, expected in expected_splits.items():
        if calibration_policy_spec.get(field) != expected:
            errors.append(
                {"field": field, "observed": calibration_policy_spec.get(field), "expected": expected}
            )
    if calibration_policy_spec.get("score_type") != column_transformer_spec.get("score_type"):
        errors.append(
            {
                "field": "score_type",
                "observed": calibration_policy_spec.get("score_type"),
                "expected": column_transformer_spec.get("score_type"),
            }
        )
    expected_model = imbalance_policy_spec.get("class_weight_policy", {}).get("candidate_model_id")
    if calibration_policy_spec.get("source_model_id") != expected_model:
        errors.append(
            {
                "field": "source_model_id",
                "observed": calibration_policy_spec.get("source_model_id"),
                "expected": expected_model,
            }
        )
    if not calibration_policy_spec.get("calibrated_score_type"):
        errors.append({"field": "calibrated_score_type", "reason": "required"})

    method = calibration_policy_spec.get("calibration_method")
    if not isinstance(method, dict):
        errors.append({"field": "calibration_method", "reason": "object required"})
    else:
        if method.get("kind") != "validation_bin_map_with_laplace_smoothing":
            errors.append(
                {
                    "field": "calibration_method.kind",
                    "observed": method.get("kind"),
                    "expected": "validation_bin_map_with_laplace_smoothing",
                }
            )
        edges = method.get("bin_edges")
        if not isinstance(edges, list) or len(edges) < 3:
            errors.append({"field": "calibration_method.bin_edges", "reason": "at least 3 edges"})
        else:
            numeric_edges = [float(edge) for edge in edges]
            if numeric_edges[0] != 0.0 or numeric_edges[-1] != 1.0:
                errors.append(
                    {
                        "field": "calibration_method.bin_edges",
                        "observed": edges,
                        "expected": "starts at 0.0 and ends at 1.0",
                    }
                )
            if numeric_edges != sorted(numeric_edges) or len(set(numeric_edges)) != len(numeric_edges):
                errors.append(
                    {
                        "field": "calibration_method.bin_edges",
                        "observed": edges,
                        "expected": "strictly increasing",
                    }
                )
        if float(method.get("smoothing_alpha", 0.0)) <= 0.0:
            errors.append(
                {
                    "field": "calibration_method.smoothing_alpha",
                    "observed": method.get("smoothing_alpha"),
                    "expected": "> 0",
                }
            )
        if method.get("prior_source") != "calibration_split_positive_rate":
            errors.append(
                {
                    "field": "calibration_method.prior_source",
                    "observed": method.get("prior_source"),
                    "expected": "calibration_split_positive_rate",
                }
            )

    metrics = calibration_policy_spec.get("metrics")
    if not isinstance(metrics, dict):
        errors.append({"field": "metrics", "reason": "object required"})
    else:
        proper = set(metrics.get("proper_scoring_rules") or [])
        diagnostics = set(metrics.get("diagnostics") or [])
        if not {"brier_score", "log_loss"}.issubset(proper):
            errors.append(
                {
                    "field": "metrics.proper_scoring_rules",
                    "observed": sorted(proper),
                    "expected": ["brier_score", "log_loss"],
                }
            )
        if "calibration_bins" not in diagnostics:
            errors.append(
                {
                    "field": "metrics.diagnostics",
                    "observed": sorted(diagnostics),
                    "expected": "calibration_bins",
                }
            )

    threshold_policy = calibration_policy_spec.get("threshold_policy")
    if not isinstance(threshold_policy, dict):
        errors.append({"field": "threshold_policy", "reason": "object required"})
    else:
        expected_threshold = {
            "selection_data": "validation",
            "evaluation_data": "test",
            "primary_decision_rule": "rank_top_k_within_scoring_batch",
            "fixed_threshold_role": "calibration_impact_diagnostic",
            "forbid_threshold_selection_on_test": True,
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

    audit_policy = calibration_policy_spec.get("audit_policy")
    if not isinstance(audit_policy, dict):
        errors.append({"field": "audit_policy", "reason": "object required"})
    else:
        for field in (
            "require_imbalance_handoff",
            "require_independent_calibration_split",
            "require_calibration_bins",
            "require_brier_score",
            "require_log_loss",
            "require_threshold_impact_report",
            "forbid_fit_on_calibration_or_test",
            "forbid_calibration_on_test",
            "forbid_test_threshold_selection",
            "warn_small_calibration_sample",
        ):
            if audit_policy.get(field) is not True:
                errors.append(
                    {
                        "field": f"audit_policy.{field}",
                        "observed": audit_policy.get(field),
                        "expected": True,
                    }
                )

    output = calibration_policy_spec.get("output")
    if not isinstance(output, dict):
        errors.append({"field": "output", "reason": "object required"})
    else:
        for field in (
            "bin_file",
            "metric_file",
            "prediction_file",
            "threshold_file",
            "audit_file",
            "report_file",
            "serialized_spec_file",
        ):
            if not output.get(field):
                errors.append({"field": f"output.{field}", "reason": "required"})

    if errors:
        return failed(
            "calibration_policy_spec_declares_probability_contract",
            len(errors),
            "calibration policy with validation bin map, proper scores and test isolation",
            errors,
        )
    return passed(
        "calibration_policy_spec_declares_probability_contract",
        {
            "calibration_policy_id": calibration_policy_spec["calibration_policy_id"],
            "source_model_id": calibration_policy_spec["source_model_id"],
            "method": calibration_policy_spec["calibration_method"]["kind"],
        },
        "calibration policy contract is explicit",
    )


def bin_for_score(score: float, edges: list[float]) -> dict[str, Any]:
    for index, (lower, upper) in enumerate(zip(edges[:-1], edges[1:], strict=True), start=1):
        is_last = index == len(edges) - 1
        if score >= lower and (score < upper or (is_last and score <= upper)):
            return {
                "bin_id": f"bin_{index}",
                "bin_index": index,
                "lower": lower,
                "upper": upper,
            }
    raise CalibrationPolicyError(f"score {score} is outside calibration bin edges")


def prediction_payload(
    imbalance_report: dict[str, Any], *, source_model_id: str
) -> dict[str, dict[str, list[Any]]]:
    rows = [
        row
        for row in imbalance_report.get("predictions", [])
        if row.get("model_id") == source_model_id and row.get("split") in {"validation", "test"}
    ]
    if not rows:
        raise CalibrationPolicyError(f"no predictions for source_model_id={source_model_id}")
    payload: dict[str, dict[str, list[Any]]] = {}
    for split in ("validation", "test"):
        split_rows = sorted(
            [row for row in rows if row["split"] == split],
            key=lambda row: row["snapshot_id"],
        )
        payload[split] = {
            "ids": [row["snapshot_id"] for row in split_rows],
            "labels": np.array([int(row["actual_label"]) for row in split_rows], dtype=int),
            "scores": np.array([float(row["score"]) for row in split_rows], dtype=float),
            "rows": split_rows,
        }
    return payload


def build_bin_map(
    *,
    ids: list[str],
    labels: np.ndarray,
    scores: np.ndarray,
    edges: list[float],
    alpha: float,
) -> tuple[list[dict[str, Any]], float]:
    positive_rate = float(labels.mean()) if len(labels) else 0.0
    records: list[dict[str, Any]] = []
    for index, (lower, upper) in enumerate(zip(edges[:-1], edges[1:], strict=True), start=1):
        bin_id = f"bin_{index}"
        members = [
            position
            for position, score in enumerate(scores.tolist())
            if bin_for_score(float(score), edges)["bin_id"] == bin_id
        ]
        row_count = len(members)
        positive_count = int(labels[members].sum()) if members else 0
        negative_count = row_count - positive_count
        fraction_positive = None if row_count == 0 else positive_count / row_count
        mean_uncalibrated = None if row_count == 0 else float(scores[members].mean())
        calibrated_probability = (positive_count + alpha * positive_rate) / (row_count + alpha)
        records.append(
            {
                "bin_id": bin_id,
                "bin_index": index,
                "lower": rounded(lower),
                "upper": rounded(upper),
                "calibration_row_count": row_count,
                "calibration_positive_count": positive_count,
                "calibration_negative_count": negative_count,
                "calibration_fraction_positive": None
                if fraction_positive is None
                else rounded(fraction_positive),
                "calibration_mean_uncalibrated_score": None
                if mean_uncalibrated is None
                else rounded(mean_uncalibrated),
                "calibrated_probability": rounded(calibrated_probability),
                "smoothing_alpha": rounded(alpha),
                "prior_positive_rate": rounded(positive_rate),
                "calibration_ids": ",".join(ids[position] for position in members),
            }
        )
    return records, positive_rate


def calibrated_probability(score: float, edges: list[float], bin_map: list[dict[str, Any]]) -> float:
    assigned = bin_for_score(score, edges)
    record = next(row for row in bin_map if row["bin_id"] == assigned["bin_id"])
    return float(record["calibrated_probability"])


def build_prediction_rows(
    *,
    payload: dict[str, dict[str, list[Any]]],
    source_model_id: str,
    score_type: str,
    calibrated_score_type: str,
    budget: int,
    edges: list[float],
    bin_map: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for split in ("validation", "test"):
        ids = payload[split]["ids"]
        labels = payload[split]["labels"]
        scores = payload[split]["scores"]
        calibrated_scores = np.array(
            [calibrated_probability(float(score), edges, bin_map) for score in scores.tolist()]
        )
        selected_uncalibrated = selected_ids_at_budget(ids, scores, min(budget, len(ids)))
        selected_calibrated = selected_ids_at_budget(ids, calibrated_scores, min(budget, len(ids)))
        for snapshot_id, label, score, calibrated_score in zip(
            ids, labels.tolist(), scores.tolist(), calibrated_scores.tolist(), strict=True
        ):
            assigned = bin_for_score(float(score), edges)
            bin_record = next(row for row in bin_map if row["bin_id"] == assigned["bin_id"])
            rows.append(
                {
                    "split": split,
                    "snapshot_id": snapshot_id,
                    "model_id": source_model_id,
                    "score_type": score_type,
                    "calibrated_score_type": calibrated_score_type,
                    "uncalibrated_score": rounded(float(score)),
                    "calibrated_score": rounded(float(calibrated_score)),
                    "actual_label": int(label),
                    "bin_id": assigned["bin_id"],
                    "bin_lower": assigned["lower"],
                    "bin_upper": assigned["upper"],
                    "calibration_bin_probability": bin_record["calibrated_probability"],
                    "selected_at_budget_uncalibrated": int(snapshot_id in selected_uncalibrated),
                    "selected_at_budget_calibrated": int(snapshot_id in selected_calibrated),
                    "predicted_at_0_5_uncalibrated": int(score >= 0.5),
                    "predicted_at_0_5_calibrated": int(calibrated_score >= 0.5),
                    "trained_on_split": "train",
                    "calibrated_on_split": "validation",
                    "test_used_for_calibration": False,
                    "generated_at": GENERATED_AT,
                }
            )
    return rows


def build_calibration_bin_rows(
    *,
    payload: dict[str, dict[str, list[Any]]],
    edges: list[float],
    bin_map: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for split in ("validation", "test"):
        labels = payload[split]["labels"]
        scores = payload[split]["scores"]
        for bin_record in bin_map:
            members = [
                position
                for position, score in enumerate(scores.tolist())
                if bin_for_score(float(score), edges)["bin_id"] == bin_record["bin_id"]
            ]
            row_count = len(members)
            positive_count = int(labels[members].sum()) if members else 0
            negative_count = row_count - positive_count
            fraction_positive = None if row_count == 0 else positive_count / row_count
            mean_uncalibrated = None if row_count == 0 else float(scores[members].mean())
            calibrated_probability_value = float(bin_record["calibrated_probability"])
            rows.append(
                {
                    "split": split,
                    "bin_id": bin_record["bin_id"],
                    "lower": bin_record["lower"],
                    "upper": bin_record["upper"],
                    "row_count": row_count,
                    "positive_count": positive_count,
                    "negative_count": negative_count,
                    "fraction_positive": None
                    if fraction_positive is None
                    else rounded(fraction_positive),
                    "mean_uncalibrated_score": None
                    if mean_uncalibrated is None
                    else rounded(mean_uncalibrated),
                    "calibrated_probability_from_validation": rounded(
                        calibrated_probability_value
                    ),
                    "absolute_uncalibrated_gap": None
                    if fraction_positive is None or mean_uncalibrated is None
                    else rounded(abs(fraction_positive - mean_uncalibrated)),
                    "absolute_calibrated_gap": None
                    if fraction_positive is None
                    else rounded(abs(fraction_positive - calibrated_probability_value)),
                    "learned_on_split": "validation",
                }
            )
    return rows


def expected_calibration_error(labels: np.ndarray, scores: np.ndarray, edges: list[float]) -> float:
    total = len(labels)
    if total == 0:
        return 0.0
    ece = 0.0
    for index in range(1, len(edges)):
        bin_id = f"bin_{index}"
        members = [
            position
            for position, score in enumerate(scores.tolist())
            if bin_for_score(float(score), edges)["bin_id"] == bin_id
        ]
        if not members:
            continue
        fraction_positive = float(labels[members].mean())
        mean_score = float(scores[members].mean())
        ece += (len(members) / total) * abs(fraction_positive - mean_score)
    return ece


def metric_row(
    *,
    split: str,
    probability_source: str,
    labels: np.ndarray,
    scores: np.ndarray,
    edges: list[float],
) -> dict[str, Any]:
    probability_matrix = np.column_stack([1 - scores, scores])
    positive_count = int(labels.sum())
    negative_count = len(labels) - positive_count
    return {
        "split": split,
        "probability_source": probability_source,
        "row_count": len(labels),
        "positive_count": positive_count,
        "negative_count": negative_count,
        "brier_score": rounded(float(brier_score_loss(labels, scores))),
        "log_loss": rounded(float(log_loss(labels, probability_matrix, labels=[0, 1]))),
        "expected_calibration_error": rounded(expected_calibration_error(labels, scores, edges)),
        "score_min": rounded(float(scores.min())),
        "score_max": rounded(float(scores.max())),
        "score_mean": rounded(float(scores.mean())),
    }


def build_metric_rows(
    *,
    payload: dict[str, dict[str, list[Any]]],
    edges: list[float],
    bin_map: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for split in ("validation", "test"):
        labels = payload[split]["labels"]
        uncalibrated_scores = payload[split]["scores"]
        calibrated_scores = np.array(
            [
                calibrated_probability(float(score), edges, bin_map)
                for score in uncalibrated_scores.tolist()
            ]
        )
        rows.append(
            metric_row(
                split=split,
                probability_source="uncalibrated",
                labels=labels,
                scores=uncalibrated_scores,
                edges=edges,
            )
        )
        rows.append(
            metric_row(
                split=split,
                probability_source="calibrated",
                labels=labels,
                scores=calibrated_scores,
                edges=edges,
            )
        )
    return rows


def ranked_ids_at_budget(ids: list[str], scores: np.ndarray, budget: int) -> list[str]:
    ranked = sorted(zip(ids, scores.tolist(), strict=True), key=lambda item: (-item[1], item[0]))
    return [snapshot_id for snapshot_id, _score in ranked[:budget]]


def threshold_metrics(
    *,
    split: str,
    probability_source: str,
    ids: list[str],
    labels: np.ndarray,
    scores: np.ndarray,
    threshold: float | None,
    budget: int,
    false_positive_cost: float,
    false_negative_cost: float,
) -> dict[str, Any]:
    if threshold is None:
        selected = ranked_ids_at_budget(ids, scores, budget)
        selected_set = set(selected)
        y_pred = np.array([1 if snapshot_id in selected_set else 0 for snapshot_id in ids])
        decision_rule = "rank_top_k_within_scoring_batch"
        threshold_value: float | str = ""
    else:
        y_pred = (scores >= threshold).astype(int)
        decision_rule = "fixed_threshold"
        threshold_value = threshold
        selected = [
            snapshot_id
            for snapshot_id, pred in zip(ids, y_pred.tolist(), strict=True)
            if int(pred) == 1
        ]
    metrics = binary_metrics_from_predictions(
        split=split,
        ids=ids,
        y_true=labels,
        y_pred=y_pred,
        false_positive_cost=false_positive_cost,
        false_negative_cost=false_negative_cost,
    )
    return {
        "probability_source": probability_source,
        "decision_rule": decision_rule,
        "threshold": threshold_value,
        **metrics,
        "selection_budget": budget,
        "budget_exceeded": metrics["action_count"] > budget,
        "selected_ids": ",".join(selected),
    }


def build_threshold_rows(
    *,
    payload: dict[str, dict[str, list[Any]]],
    thresholds: list[float],
    budget: int,
    false_positive_cost: float,
    false_negative_cost: float,
    edges: list[float],
    bin_map: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for split in ("validation", "test"):
        ids = payload[split]["ids"]
        labels = payload[split]["labels"]
        uncalibrated_scores = payload[split]["scores"]
        calibrated_scores = np.array(
            [
                calibrated_probability(float(score), edges, bin_map)
                for score in uncalibrated_scores.tolist()
            ]
        )
        for probability_source, scores in (
            ("uncalibrated", uncalibrated_scores),
            ("calibrated", calibrated_scores),
        ):
            rows.append(
                {
                    **threshold_metrics(
                        split=split,
                        probability_source=probability_source,
                        ids=ids,
                        labels=labels,
                        scores=scores,
                        threshold=None,
                        budget=min(budget, len(ids)),
                        false_positive_cost=false_positive_cost,
                        false_negative_cost=false_negative_cost,
                    ),
                    "threshold_role": "primary_budget_rule",
                }
            )
            for threshold in thresholds:
                rows.append(
                    {
                        **threshold_metrics(
                            split=split,
                            probability_source=probability_source,
                            ids=ids,
                            labels=labels,
                            scores=scores,
                            threshold=float(threshold),
                            budget=min(budget, len(ids)),
                            false_positive_cost=false_positive_cost,
                            false_negative_cost=false_negative_cost,
                        ),
                        "threshold_role": "calibration_impact_diagnostic",
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
    calibration_policy_spec_path: Path,
    features_path: Path,
    labels_path: Path,
    manifest_path: Path,
    cv_fold_manifest_path: Path,
    report_output_path: Path | None = None,
    bin_output_path: Path | None = None,
    metric_output_path: Path | None = None,
    predictions_output_path: Path | None = None,
    threshold_output_path: Path | None = None,
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
    calibration_policy_spec = read_json(calibration_policy_spec_path)
    checks: list[dict[str, Any]] = [
        validate_calibration_policy_spec(
            problem_spec=problem_spec,
            pipeline_spec=pipeline_spec,
            column_transformer_spec=column_transformer_spec,
            linear_baseline_spec=linear_baseline_spec,
            tree_diagnostic_spec=tree_diagnostic_spec,
            tree_ensemble_spec=tree_ensemble_spec,
            cv_plan_spec=cv_plan_spec,
            imbalance_policy_spec=imbalance_policy_spec,
            calibration_policy_spec=calibration_policy_spec,
        )
    ]

    imbalance_report = run_imbalance_audit(
        spec_path=spec_path,
        preprocessing_contract_path=preprocessing_contract_path,
        pipeline_spec_path=pipeline_spec_path,
        column_transformer_spec_path=column_transformer_spec_path,
        linear_baseline_spec_path=linear_baseline_spec_path,
        tree_diagnostic_spec_path=tree_diagnostic_spec_path,
        tree_ensemble_spec_path=tree_ensemble_spec_path,
        cv_plan_spec_path=cv_plan_spec_path,
        imbalance_policy_spec_path=imbalance_policy_spec_path,
        features_path=features_path,
        labels_path=labels_path,
        manifest_path=manifest_path,
        cv_fold_manifest_path=cv_fold_manifest_path,
    )
    if imbalance_report.get("valid") and (
        imbalance_report.get("summary", {}).get("readiness_status")
        == "ready_for_calibration_lesson"
    ):
        checks.append(
            passed(
                "upstream_imbalance_handoff_is_valid",
                {
                    "imbalance_policy_id": imbalance_policy_spec.get("imbalance_policy_id"),
                    "selected_model_id": imbalance_report["summary"].get("selected_model_id"),
                    "readiness_status": imbalance_report["summary"].get("readiness_status"),
                },
                "imbalance handoff is valid and ready for calibration",
            )
        )
    else:
        checks.append(
            failed(
                "upstream_imbalance_handoff_is_valid",
                imbalance_report.get("summary", {}).get("blocking_errors", []),
                "valid imbalance report with ready_for_calibration_lesson",
                imbalance_report.get("checks", []),
            )
        )

    independent_splits = {
        calibration_policy_spec.get("fit_split"),
        calibration_policy_spec.get("calibration_split"),
        calibration_policy_spec.get("evaluation_split"),
    }
    if independent_splits == {"train", "validation", "test"}:
        checks.append(
            passed(
                "calibration_split_is_independent",
                {
                    "fit_split": calibration_policy_spec.get("fit_split"),
                    "calibration_split": calibration_policy_spec.get("calibration_split"),
                    "evaluation_split": calibration_policy_spec.get("evaluation_split"),
                },
                "fit, calibration and evaluation roles are separate",
            )
        )
    else:
        checks.append(
            failed(
                "calibration_split_is_independent",
                sorted(str(value) for value in independent_splits),
                ["train", "validation", "test"],
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
                "calibration_policy_id": calibration_policy_spec.get("calibration_policy_id"),
                "blocking_errors": blocking_errors,
                "warnings": [],
                "readiness_status": "blocked_before_calibration",
            },
            "checks": checks,
        }
        if report_output_path is not None:
            write_json(report_output_path, json_ready(report))
        return report

    source_model_id = calibration_policy_spec["source_model_id"]
    method = calibration_policy_spec["calibration_method"]
    edges = [float(edge) for edge in method["bin_edges"]]
    alpha = float(method["smoothing_alpha"])
    payload = prediction_payload(imbalance_report, source_model_id=source_model_id)
    calibration_ids = payload["validation"]["ids"]
    calibration_labels = payload["validation"]["labels"]
    calibration_scores = payload["validation"]["scores"]
    bin_map, prior_positive_rate = build_bin_map(
        ids=calibration_ids,
        labels=calibration_labels,
        scores=calibration_scores,
        edges=edges,
        alpha=alpha,
    )

    min_calibration_rows = int(method["min_calibration_rows"])
    min_rows_per_bin = int(method["min_rows_per_bin"])
    if len(calibration_ids) < min_calibration_rows:
        checks.append(
            failed(
                "calibration_sample_below_minimum",
                len(calibration_ids),
                f">= {min_calibration_rows} calibration rows",
                severity="warning",
            )
        )
    sparse_bins = [
        {
            "bin_id": row["bin_id"],
            "row_count": row["calibration_row_count"],
        }
        for row in bin_map
        if row["calibration_row_count"] < min_rows_per_bin
    ]
    if sparse_bins:
        checks.append(
            failed(
                "calibration_bins_below_min_rows",
                sparse_bins,
                f">= {min_rows_per_bin} calibration rows per bin",
                severity="warning",
            )
        )
    single_class_bins = [
        {
            "bin_id": row["bin_id"],
            "positive_count": row["calibration_positive_count"],
            "negative_count": row["calibration_negative_count"],
        }
        for row in bin_map
        if row["calibration_row_count"] > 0
        and (
            row["calibration_positive_count"] == 0
            or row["calibration_negative_count"] == 0
        )
    ]
    if method.get("warn_if_bin_has_single_class") and single_class_bins:
        checks.append(
            failed(
                "calibration_bins_missing_class_coverage",
                single_class_bins,
                "each non-empty calibration bin should contain both classes",
                severity="warning",
            )
        )

    checks.append(
        passed(
            "calibration_not_fitted_on_test",
            {"calibration_split": "validation", "test_used_for_calibration": False},
            "test split is held out from calibration fit",
        )
    )

    prediction_rows = build_prediction_rows(
        payload=payload,
        source_model_id=source_model_id,
        score_type=calibration_policy_spec["score_type"],
        calibrated_score_type=calibration_policy_spec["calibrated_score_type"],
        budget=selection_budget(problem_spec),
        edges=edges,
        bin_map=bin_map,
    )
    bin_rows = build_calibration_bin_rows(payload=payload, edges=edges, bin_map=bin_map)
    metric_rows = build_metric_rows(payload=payload, edges=edges, bin_map=bin_map)
    false_positive_cost, false_negative_cost = cost_weights(problem_spec)
    threshold_rows = build_threshold_rows(
        payload=payload,
        thresholds=calibration_policy_spec["threshold_policy"]["candidate_thresholds"],
        budget=selection_budget(problem_spec),
        false_positive_cost=false_positive_cost,
        false_negative_cost=false_negative_cost,
        edges=edges,
        bin_map=bin_map,
    )

    checks.append(
        passed(
            "calibration_bins_reported",
            {"rows": len(bin_rows), "bin_count": len(bin_map)},
            "calibration bins are reported for validation and test",
        )
    )
    checks.append(
        passed(
            "calibration_brier_and_log_loss_reported",
            {"rows": len(metric_rows), "metrics": ["brier_score", "log_loss"]},
            "proper scoring rules are reported for calibrated and uncalibrated scores",
        )
    )
    checks.append(
        passed(
            "calibration_threshold_impact_reported",
            {"rows": len(threshold_rows)},
            "threshold impact report is available",
        )
    )

    fixed_test_uncalibrated = next(
        row
        for row in threshold_rows
        if row["split"] == "test"
        and row["probability_source"] == "uncalibrated"
        and row["decision_rule"] == "fixed_threshold"
        and row["threshold"] == 0.5
    )
    fixed_test_calibrated = next(
        row
        for row in threshold_rows
        if row["split"] == "test"
        and row["probability_source"] == "calibrated"
        and row["decision_rule"] == "fixed_threshold"
        and row["threshold"] == 0.5
    )
    if fixed_test_uncalibrated["action_count"] != fixed_test_calibrated["action_count"]:
        checks.append(
            failed(
                "fixed_threshold_action_count_changes_after_calibration",
                {
                    "uncalibrated_action_count": fixed_test_uncalibrated["action_count"],
                    "calibrated_action_count": fixed_test_calibrated["action_count"],
                },
                "fixed thresholds should be re-audited after calibration",
                severity="warning",
            )
        )

    metric_lookup = {
        (row["split"], row["probability_source"]): row
        for row in metric_rows
    }
    if (
        metric_lookup[("test", "calibrated")]["brier_score"]
        < metric_lookup[("test", "uncalibrated")]["brier_score"]
    ):
        checks.append(
            failed(
                "tiny_test_improvement_is_not_production_claim",
                {
                    "uncalibrated_test_brier": metric_lookup[("test", "uncalibrated")][
                        "brier_score"
                    ],
                    "calibrated_test_brier": metric_lookup[("test", "calibrated")][
                        "brier_score"
                    ],
                },
                "tiny test improvement should be treated as a smoke test, not a launch claim",
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
    threshold_lookup = {
        (row["split"], row["probability_source"], row["decision_rule"], row["threshold"]): row
        for row in threshold_rows
    }
    test_topk_uncalibrated = threshold_lookup[
        ("test", "uncalibrated", "rank_top_k_within_scoring_batch", "")
    ]
    test_topk_calibrated = threshold_lookup[
        ("test", "calibrated", "rank_top_k_within_scoring_batch", "")
    ]
    serialized_spec = {
        "calibration_policy_id": calibration_policy_spec["calibration_policy_id"],
        "problem_id": problem_spec["problem_id"],
        "sklearn_version": sklearn.__version__,
        "source_model_id": source_model_id,
        "score_type": calibration_policy_spec["score_type"],
        "calibrated_score_type": calibration_policy_spec["calibrated_score_type"],
        "calibration_method": {
            **method,
            "prior_positive_rate": rounded(prior_positive_rate),
            "learned_bin_map": bin_map,
        },
        "fit_trace": [
            {
                "event": "base_model_fit",
                "fit_split": "train",
                "source": "imbalance_policy_handoff",
                "calibration_ids_seen": [],
                "test_ids_seen": [],
            },
            {
                "event": "calibration_bin_map_fit",
                "fit_split": "validation",
                "calibration_ids": calibration_ids,
                "test_ids_seen": [],
            },
        ],
        "test_used_for_calibration": False,
        "threshold_policy": calibration_policy_spec["threshold_policy"],
    }
    summary = {
        "calibration_policy_id": calibration_policy_spec["calibration_policy_id"],
        "problem_id": problem_spec["problem_id"],
        "sklearn_version": sklearn.__version__,
        "source_model_id": source_model_id,
        "calibration_method": method["kind"],
        "calibration_split": calibration_policy_spec["calibration_split"],
        "evaluation_split": calibration_policy_spec["evaluation_split"],
        "calibration_row_count": len(calibration_ids),
        "calibration_prior_positive_rate": rounded(prior_positive_rate),
        "uncalibrated_validation_brier": metric_lookup[("validation", "uncalibrated")][
            "brier_score"
        ],
        "calibrated_validation_brier": metric_lookup[("validation", "calibrated")][
            "brier_score"
        ],
        "uncalibrated_test_brier": metric_lookup[("test", "uncalibrated")]["brier_score"],
        "calibrated_test_brier": metric_lookup[("test", "calibrated")]["brier_score"],
        "uncalibrated_test_log_loss": metric_lookup[("test", "uncalibrated")]["log_loss"],
        "calibrated_test_log_loss": metric_lookup[("test", "calibrated")]["log_loss"],
        "uncalibrated_test_precision_at_budget": test_topk_uncalibrated["precision"],
        "calibrated_test_precision_at_budget": test_topk_calibrated["precision"],
        "test_uncalibrated_top_k_selected_ids": test_topk_uncalibrated["selected_ids"].split(","),
        "test_calibrated_top_k_selected_ids": test_topk_calibrated["selected_ids"].split(","),
        "test_fixed_threshold_0_5_action_count_uncalibrated": fixed_test_uncalibrated[
            "action_count"
        ],
        "test_fixed_threshold_0_5_action_count_calibrated": fixed_test_calibrated[
            "action_count"
        ],
        "test_used_for_calibration": False,
        "blocking_errors": blocking_errors,
        "warnings": warnings,
        "readiness_status": "ready_for_leakage_lesson"
        if valid
        else "blocked_by_calibration_policy_audit",
    }
    report = {
        "valid": valid,
        "problem_id": problem_spec["problem_id"],
        "summary": summary,
        "calibration_bins": bin_rows,
        "metrics": metric_rows,
        "predictions": prediction_rows,
        "threshold_impact": threshold_rows,
        "audit": build_audit_rows(checks),
        "serialized_spec": serialized_spec,
        "checks": checks,
    }

    if bin_output_path is not None:
        write_csv(
            bin_output_path,
            bin_rows,
            [
                "split",
                "bin_id",
                "lower",
                "upper",
                "row_count",
                "positive_count",
                "negative_count",
                "fraction_positive",
                "mean_uncalibrated_score",
                "calibrated_probability_from_validation",
                "absolute_uncalibrated_gap",
                "absolute_calibrated_gap",
                "learned_on_split",
            ],
        )
    if metric_output_path is not None:
        write_csv(
            metric_output_path,
            metric_rows,
            [
                "split",
                "probability_source",
                "row_count",
                "positive_count",
                "negative_count",
                "brier_score",
                "log_loss",
                "expected_calibration_error",
                "score_min",
                "score_max",
                "score_mean",
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
                "score_type",
                "calibrated_score_type",
                "uncalibrated_score",
                "calibrated_score",
                "actual_label",
                "bin_id",
                "bin_lower",
                "bin_upper",
                "calibration_bin_probability",
                "selected_at_budget_uncalibrated",
                "selected_at_budget_calibrated",
                "predicted_at_0_5_uncalibrated",
                "predicted_at_0_5_calibrated",
                "trained_on_split",
                "calibrated_on_split",
                "test_used_for_calibration",
                "generated_at",
            ],
        )
    if threshold_output_path is not None:
        write_csv(
            threshold_output_path,
            threshold_rows,
            [
                "probability_source",
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
    parser = argparse.ArgumentParser(description="Audit probability calibration for ML baseline")
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--preprocessing-contract", type=Path, required=True)
    parser.add_argument("--pipeline-spec", type=Path, required=True)
    parser.add_argument("--column-transformer-spec", type=Path, required=True)
    parser.add_argument("--linear-baseline-spec", type=Path, required=True)
    parser.add_argument("--tree-diagnostic-spec", type=Path, required=True)
    parser.add_argument("--tree-ensemble-spec", type=Path, required=True)
    parser.add_argument("--cv-plan-spec", type=Path, required=True)
    parser.add_argument("--imbalance-policy-spec", type=Path, required=True)
    parser.add_argument("--calibration-policy-spec", type=Path, required=True)
    parser.add_argument("--features", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--cv-fold-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--bin-output", type=Path)
    parser.add_argument("--metric-output", type=Path)
    parser.add_argument("--predictions-output", type=Path)
    parser.add_argument("--threshold-output", type=Path)
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
            calibration_policy_spec_path=args.calibration_policy_spec,
            features_path=args.features,
            labels_path=args.labels,
            manifest_path=args.manifest,
            cv_fold_manifest_path=args.cv_fold_manifest,
            report_output_path=args.output,
            bin_output_path=args.bin_output,
            metric_output_path=args.metric_output,
            predictions_output_path=args.predictions_output,
            threshold_output_path=args.threshold_output,
            audit_output_path=args.audit_output,
            serialized_spec_output_path=args.serialized_spec_output,
        )
    except (
        OSError,
        json.JSONDecodeError,
        ColumnTransformerAuditError,
        LinearBaselineError,
        ImbalancePolicyError,
        CalibrationPolicyError,
        KeyError,
        ValueError,
    ) as error:
        report = {
            "valid": False,
            "summary": {
                "blocking_errors": ["calibration_policy_runtime_error"],
                "warnings": [],
                "readiness_status": "runtime_error",
            },
            "checks": [
                failed(
                    "calibration_policy_runtime_error",
                    str(error),
                    "readable inputs and valid calibration policy",
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
