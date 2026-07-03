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

ENSEMBLE_OUTPUT_ROOT = Path(__file__).resolve().parents[2] / "09-ensembles" / "outputs"
LINEAR_OUTPUT_ROOT = Path(__file__).resolve().parents[2] / "07-linear-models" / "outputs"
COLUMN_OUTPUT_ROOT = Path(__file__).resolve().parents[2] / "06-column-transformer" / "outputs"
for output_root in (ENSEMBLE_OUTPUT_ROOT, LINEAR_OUTPUT_ROOT, COLUMN_OUTPUT_ROOT):
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
from linear_baseline_trainer import (  # noqa: E402
    LinearBaselineError,
    cost_weights,
    selected_ids_at_budget,
    selection_budget,
    split_metric_row,
)
from tree_ensemble_comparator import (  # noqa: E402
    TreeEnsembleError,
    build_ensemble_pipeline,
    positive_scores,
    run as run_tree_ensemble_audit,
)

REQUIRED_FOLD_COLUMNS = {
    "fold_id",
    "fold_order",
    "snapshot_id",
    "user_id",
    "prediction_time",
    "original_split",
    "cv_role",
    "group_key",
    "label",
    "assigned_by_policy",
}
GENERATED_AT = "2026-07-02T14:00:00+03:00"
TINY_FOLD_WARNING_THRESHOLD = 3
TINY_VALIDATION_WARNING_THRESHOLD = 20


class CrossValidationPlannerError(ValueError):
    """Raised when cross-validation planner inputs cannot be parsed."""


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


def parse_label(value: str) -> int:
    normalized = value.strip().lower()
    if normalized == "true":
        return 1
    if normalized == "false":
        return 0
    raise CrossValidationPlannerError(f"expected boolean label, got {value!r}")


def fold_ids(fold_rows: list[dict[str, str]]) -> list[str]:
    return sorted(
        {row["fold_id"] for row in fold_rows},
        key=lambda fold: fold_order(fold_rows, fold),
    )


def fold_order(fold_rows: list[dict[str, str]], fold_id: str) -> int:
    orders = {int(row["fold_order"]) for row in fold_rows if row["fold_id"] == fold_id}
    if len(orders) != 1:
        raise CrossValidationPlannerError(f"fold {fold_id!r} must have exactly one fold_order")
    return orders.pop()


def ids_for_fold(fold_rows: list[dict[str, str]], fold_id: str, role: str) -> list[str]:
    return [
        row["snapshot_id"]
        for row in fold_rows
        if row["fold_id"] == fold_id and row["cv_role"] == role
    ]


def label_values_for_ids(ids: list[str], labels_by_id: dict[str, dict[str, str]]) -> list[int]:
    return [parse_label(labels_by_id[snapshot_id]["churned_14d"]) for snapshot_id in ids]


def validate_cv_plan_spec(
    *,
    problem_spec: dict[str, Any],
    pipeline_spec: dict[str, Any],
    column_transformer_spec: dict[str, Any],
    linear_baseline_spec: dict[str, Any],
    tree_diagnostic_spec: dict[str, Any],
    tree_ensemble_spec: dict[str, Any],
    cv_plan_spec: dict[str, Any],
) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    expected_identity = {
        "problem_id": problem_spec.get("problem_id"),
        "pipeline_id": pipeline_spec.get("pipeline_id"),
        "column_transformer_id": column_transformer_spec.get("column_transformer_id"),
        "linear_baseline_id": linear_baseline_spec.get("linear_baseline_id"),
        "tree_diagnostic_id": tree_diagnostic_spec.get("tree_diagnostic_id"),
        "tree_ensemble_id": tree_ensemble_spec.get("tree_ensemble_id"),
    }
    for field, expected in expected_identity.items():
        if cv_plan_spec.get(field) != expected:
            errors.append(
                {"field": field, "observed": cv_plan_spec.get(field), "expected": expected}
            )

    if cv_plan_spec.get("model_selection_pool_splits") != ["train", "validation"]:
        errors.append(
            {
                "field": "model_selection_pool_splits",
                "observed": cv_plan_spec.get("model_selection_pool_splits"),
                "expected": ["train", "validation"],
            }
        )
    if cv_plan_spec.get("final_holdout_split") != "test":
        errors.append(
            {
                "field": "final_holdout_split",
                "observed": cv_plan_spec.get("final_holdout_split"),
                "expected": "test",
            }
        )
    if cv_plan_spec.get("score_type") != column_transformer_spec.get("score_type"):
        errors.append(
            {
                "field": "score_type",
                "observed": cv_plan_spec.get("score_type"),
                "expected": column_transformer_spec.get("score_type"),
            }
        )

    strategy = cv_plan_spec.get("cv_strategy")
    if not isinstance(strategy, dict):
        errors.append({"field": "cv_strategy", "reason": "object required"})
    else:
        expected_strategy = {
            "kind": "predeclared_time_ordered_group_folds",
            "train_role": "cv_train",
            "validation_role": "cv_validation",
            "group_key": "user_id",
            "time_key": "prediction_time",
        }
        for field, expected in expected_strategy.items():
            if strategy.get(field) != expected:
                errors.append(
                    {
                        "field": f"cv_strategy.{field}",
                        "observed": strategy.get(field),
                        "expected": expected,
                    }
                )
        if not isinstance(strategy.get("n_splits"), int) or strategy["n_splits"] < 2:
            errors.append(
                {
                    "field": "cv_strategy.n_splits",
                    "observed": strategy.get("n_splits"),
                    "expected": "integer >= 2",
                }
            )
        if strategy.get("forbid_future_train_rows") is not True:
            errors.append(
                {
                    "field": "cv_strategy.forbid_future_train_rows",
                    "observed": strategy.get("forbid_future_train_rows"),
                    "expected": True,
                }
            )

    scoring = cv_plan_spec.get("scoring")
    if not isinstance(scoring, dict):
        errors.append({"field": "scoring", "reason": "object required"})
    else:
        if scoring.get("primary_metric") != "precision_at_budget":
            errors.append(
                {
                    "field": "scoring.primary_metric",
                    "observed": scoring.get("primary_metric"),
                    "expected": "precision_at_budget",
                }
            )
        if scoring.get("primary_metric") != tree_ensemble_spec.get("comparison", {}).get(
            "primary_metric"
        ):
            errors.append(
                {
                    "field": "scoring.aligned_with",
                    "observed": scoring.get("primary_metric"),
                    "expected": tree_ensemble_spec.get("comparison", {}).get("primary_metric"),
                }
            )
        if scoring.get("requires_proba") is not True:
            errors.append(
                {
                    "field": "scoring.requires_proba",
                    "observed": scoring.get("requires_proba"),
                    "expected": True,
                }
            )
        if scoring.get("budget_source") != "problem_spec.decision_budget.max_actions":
            errors.append(
                {
                    "field": "scoring.budget_source",
                    "observed": scoring.get("budget_source"),
                    "expected": "problem_spec.decision_budget.max_actions",
                }
            )

    candidate_source = cv_plan_spec.get("candidate_source")
    if not isinstance(candidate_source, dict):
        errors.append({"field": "candidate_source", "reason": "object required"})
    else:
        expected_candidate = tree_ensemble_spec.get("candidate", {})
        for field in ("model_id", "kind"):
            if candidate_source.get(field) != expected_candidate.get(field):
                errors.append(
                    {
                        "field": f"candidate_source.{field}",
                        "observed": candidate_source.get(field),
                        "expected": expected_candidate.get(field),
                    }
                )

    audit_policy = cv_plan_spec.get("audit_policy")
    if not isinstance(audit_policy, dict):
        errors.append({"field": "audit_policy", "reason": "object required"})
    else:
        for field in (
            "require_ensemble_handoff",
            "require_fold_manifest",
            "require_group_isolation",
            "require_temporal_order",
            "require_class_coverage_per_fold",
            "require_scoring_alignment",
            "forbid_test_rows_in_cv",
            "forbid_fit_on_cv_validation",
            "forbid_default_integer_cv",
        ):
            if audit_policy.get(field) is not True:
                errors.append(
                    {
                        "field": f"audit_policy.{field}",
                        "observed": audit_policy.get(field),
                        "expected": True,
                    }
                )

    output = cv_plan_spec.get("output")
    if not isinstance(output, dict):
        errors.append({"field": "output", "reason": "object required"})
    else:
        for field in (
            "fold_manifest_file",
            "score_file",
            "prediction_file",
            "audit_file",
            "report_file",
            "serialized_spec_file",
        ):
            if not output.get(field):
                errors.append({"field": f"output.{field}", "reason": "required"})

    if errors:
        return failed(
            "cv_plan_spec_declares_group_time_scoring_contract",
            len(errors),
            "predeclared group/time folds, scoring policy and no-test-peeking contract",
            errors,
        )
    return passed(
        "cv_plan_spec_declares_group_time_scoring_contract",
        {
            "cv_plan_id": cv_plan_spec["cv_plan_id"],
            "n_splits": cv_plan_spec["cv_strategy"]["n_splits"],
            "primary_metric": cv_plan_spec["scoring"]["primary_metric"],
        },
        "cross-validation planning contract is explicit",
    )


def validate_fold_manifest_schema(
    fold_rows: list[dict[str, str]],
    columns: list[str],
    cv_plan_spec: dict[str, Any],
) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    missing = sorted(REQUIRED_FOLD_COLUMNS - set(columns))
    if missing:
        errors.append({"reason": "missing fold columns", "sample": missing})
    fold_id_values = sorted({row.get("fold_id", "") for row in fold_rows if row.get("fold_id")})
    if len(fold_id_values) != cv_plan_spec.get("cv_strategy", {}).get("n_splits"):
        errors.append(
            {
                "field": "fold_id",
                "observed": fold_id_values,
                "expected": cv_plan_spec.get("cv_strategy", {}).get("n_splits"),
            }
        )
    for fold_id in fold_id_values:
        roles = {row.get("cv_role") for row in fold_rows if row.get("fold_id") == fold_id}
        if roles != {"cv_train", "cv_validation"}:
            errors.append({"fold_id": fold_id, "observed_roles": sorted(roles)})
    if errors:
        return failed(
            "cv_fold_manifest_has_required_shape",
            len(errors),
            "fold rows with train and validation roles for every declared fold",
            errors,
        )
    return passed(
        "cv_fold_manifest_has_required_shape",
        {"folds": fold_id_values, "rows": len(fold_rows)},
        "fold manifest has the required shape",
    )


def validate_no_test_rows(
    fold_rows: list[dict[str, str]], manifest_rows: list[dict[str, str]]
) -> dict[str, Any]:
    test_ids = {row["snapshot_id"] for row in manifest_rows if row["split"] == "test"}
    bad_rows = [
        {
            "fold_id": row["fold_id"],
            "snapshot_id": row["snapshot_id"],
            "original_split": row["original_split"],
        }
        for row in fold_rows
        if row["snapshot_id"] in test_ids or row["original_split"] == "test"
    ]
    if bad_rows:
        return failed(
            "cv_fold_manifest_excludes_final_test",
            len(bad_rows),
            "no final holdout test rows inside cross-validation folds",
            bad_rows,
        )
    return passed(
        "cv_fold_manifest_excludes_final_test",
        {"test_ids_excluded": sorted(test_ids), "cv_rows": len(fold_rows)},
        "final holdout test rows are not used in CV",
    )


def validate_group_isolation(fold_rows: list[dict[str, str]]) -> dict[str, Any]:
    violations: list[dict[str, Any]] = []
    for fold_id in fold_ids(fold_rows):
        train_groups = {
            row["group_key"]
            for row in fold_rows
            if row["fold_id"] == fold_id and row["cv_role"] == "cv_train"
        }
        validation_groups = {
            row["group_key"]
            for row in fold_rows
            if row["fold_id"] == fold_id and row["cv_role"] == "cv_validation"
        }
        overlap = sorted(train_groups & validation_groups)
        if overlap:
            violations.append({"fold_id": fold_id, "overlap": overlap})
    if violations:
        return failed(
            "cv_group_isolation_respected",
            len(violations),
            "no group appears in both train and validation for a fold",
            violations,
        )
    return passed(
        "cv_group_isolation_respected",
        {"folds": fold_ids(fold_rows)},
        "groups are isolated inside every fold",
    )


def validate_temporal_order(fold_rows: list[dict[str, str]]) -> dict[str, Any]:
    violations: list[dict[str, Any]] = []
    observed: list[dict[str, Any]] = []
    for fold_id in fold_ids(fold_rows):
        train_times = [
            row["prediction_time"]
            for row in fold_rows
            if row["fold_id"] == fold_id and row["cv_role"] == "cv_train"
        ]
        validation_times = [
            row["prediction_time"]
            for row in fold_rows
            if row["fold_id"] == fold_id and row["cv_role"] == "cv_validation"
        ]
        max_train_time = max(train_times)
        min_validation_time = min(validation_times)
        observed.append(
            {
                "fold_id": fold_id,
                "max_train_time": max_train_time,
                "min_validation_time": min_validation_time,
            }
        )
        if max_train_time > min_validation_time:
            violations.append(observed[-1])
    if violations:
        return failed(
            "cv_temporal_order_respected",
            len(violations),
            "no fold trains on rows later than its validation rows",
            violations,
        )
    return passed(
        "cv_temporal_order_respected",
        observed,
        "folds do not train on future rows",
    )


def validate_class_coverage(
    fold_rows: list[dict[str, str]], labels_by_id: dict[str, dict[str, str]]
) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    observed: list[dict[str, Any]] = []
    for fold_id in fold_ids(fold_rows):
        for role in ("cv_train", "cv_validation"):
            ids = ids_for_fold(fold_rows, fold_id, role)
            labels = label_values_for_ids(ids, labels_by_id)
            label_set = sorted(set(labels))
            observed.append({"fold_id": fold_id, "cv_role": role, "labels": label_set})
            if label_set != [0, 1]:
                errors.append({"fold_id": fold_id, "cv_role": role, "labels": label_set})
    if errors:
        return failed(
            "cv_folds_have_binary_class_coverage",
            len(errors),
            "each train and validation fold contains both classes",
            errors,
        )
    return passed(
        "cv_folds_have_binary_class_coverage",
        observed,
        "each fold role contains both target classes",
    )


def validate_fold_labels(
    fold_rows: list[dict[str, str]], labels_by_id: dict[str, dict[str, str]]
) -> dict[str, Any]:
    mismatches: list[dict[str, Any]] = []
    for row in fold_rows:
        expected = labels_by_id[row["snapshot_id"]]["churned_14d"].lower()
        if row["label"].lower() != expected:
            mismatches.append(
                {
                    "fold_id": row["fold_id"],
                    "snapshot_id": row["snapshot_id"],
                    "observed": row["label"],
                    "expected": expected,
                }
            )
    if mismatches:
        return failed(
            "cv_fold_labels_match_target_table",
            len(mismatches),
            "fold manifest labels match ml_labels.csv",
            mismatches,
        )
    return passed(
        "cv_fold_labels_match_target_table",
        {"rows": len(fold_rows)},
        "fold labels match target table",
    )


def validate_scoring_alignment(
    cv_plan_spec: dict[str, Any], tree_ensemble_spec: dict[str, Any]
) -> dict[str, Any]:
    observed = cv_plan_spec["scoring"]["primary_metric"]
    expected = tree_ensemble_spec["comparison"]["primary_metric"]
    if observed != expected:
        return failed(
            "cv_scoring_policy_matches_model_selection_metric",
            observed,
            expected,
        )
    return passed(
        "cv_scoring_policy_matches_model_selection_metric",
        {"primary_metric": observed, "requires_proba": cv_plan_spec["scoring"]["requires_proba"]},
        "CV scoring aligns with model-selection metric",
    )


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


def normalized_fold_rows(fold_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    role_order = {"cv_train": 0, "cv_validation": 1}
    for row in sorted(
        fold_rows,
        key=lambda item: (
            int(item["fold_order"]),
            role_order[item["cv_role"]],
            item["snapshot_id"],
        ),
    ):
        rows.append(
            {
                "fold_id": row["fold_id"],
                "fold_order": int(row["fold_order"]),
                "snapshot_id": row["snapshot_id"],
                "user_id": row["user_id"],
                "prediction_time": row["prediction_time"],
                "original_split": row["original_split"],
                "cv_role": row["cv_role"],
                "group_key": row["group_key"],
                "label": int(parse_label(row["label"])),
                "assigned_by_policy": row["assigned_by_policy"],
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
    features_path: Path,
    labels_path: Path,
    manifest_path: Path,
    cv_fold_manifest_path: Path,
    report_output_path: Path | None = None,
    fold_manifest_output_path: Path | None = None,
    score_output_path: Path | None = None,
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
    feature_rows, _feature_columns = read_csv(features_path)
    labels, _label_columns = read_csv(labels_path)
    manifest_rows, _manifest_columns = read_csv(manifest_path)
    fold_rows, fold_columns = read_csv(cv_fold_manifest_path)

    labels_by_id = rows_by_id(labels)
    checks: list[dict[str, Any]] = [
        validate_cv_plan_spec(
            problem_spec=problem_spec,
            pipeline_spec=pipeline_spec,
            column_transformer_spec=column_transformer_spec,
            linear_baseline_spec=linear_baseline_spec,
            tree_diagnostic_spec=tree_diagnostic_spec,
            tree_ensemble_spec=tree_ensemble_spec,
            cv_plan_spec=cv_plan_spec,
        ),
        validate_fold_manifest_schema(fold_rows, fold_columns, cv_plan_spec),
        validate_no_test_rows(fold_rows, manifest_rows),
        validate_group_isolation(fold_rows),
        validate_temporal_order(fold_rows),
        validate_class_coverage(fold_rows, labels_by_id),
        validate_fold_labels(fold_rows, labels_by_id),
        validate_scoring_alignment(cv_plan_spec, tree_ensemble_spec),
    ]
    ensemble_report = run_tree_ensemble_audit(
        spec_path=spec_path,
        preprocessing_contract_path=preprocessing_contract_path,
        pipeline_spec_path=pipeline_spec_path,
        column_transformer_spec_path=column_transformer_spec_path,
        linear_baseline_spec_path=linear_baseline_spec_path,
        tree_diagnostic_spec_path=tree_diagnostic_spec_path,
        tree_ensemble_spec_path=tree_ensemble_spec_path,
        features_path=features_path,
        labels_path=labels_path,
        manifest_path=manifest_path,
    )
    if ensemble_report.get("valid"):
        checks.append(
            passed(
                "upstream_tree_ensemble_audit_is_valid",
                {
                    "tree_ensemble_id": tree_ensemble_spec.get("tree_ensemble_id"),
                    "readiness_status": ensemble_report["summary"].get("readiness_status"),
                },
                "tree ensemble handoff is valid",
            )
        )
    else:
        checks.append(
            failed(
                "upstream_tree_ensemble_audit_is_valid",
                ensemble_report.get("summary", {}).get("blocking_errors", []),
                "valid tree ensemble report before cross-validation planning",
                ensemble_report.get("checks", []),
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
                "cv_plan_id": cv_plan_spec.get("cv_plan_id"),
                "blocking_errors": blocking_errors,
                "warnings": [],
                "readiness_status": "blocked_before_cv_fit",
            },
            "checks": checks,
        }
        if report_output_path is not None:
            write_json(report_output_path, report)
        return report

    feature_rows_by_id = rows_by_id(feature_rows)
    budget = selection_budget(problem_spec)
    false_positive_cost, false_negative_cost = cost_weights(problem_spec)
    model_id = tree_ensemble_spec["candidate"]["model_id"]
    model_kind = tree_ensemble_spec["candidate"]["kind"]
    score_rows: list[dict[str, Any]] = []
    prediction_rows: list[dict[str, Any]] = []
    fit_trace: list[dict[str, Any]] = []

    for fold_id in fold_ids(fold_rows):
        order = fold_order(fold_rows, fold_id)
        train_ids = ids_for_fold(fold_rows, fold_id, "cv_train")
        validation_ids = ids_for_fold(fold_rows, fold_id, "cv_validation")
        X_train = make_frame(train_ids, feature_rows_by_id, column_transformer_spec)
        y_train = make_target(train_ids, labels_by_id, problem_spec)
        X_validation = make_frame(validation_ids, feature_rows_by_id, column_transformer_spec)
        y_validation = make_target(validation_ids, labels_by_id, problem_spec)
        pipeline = build_ensemble_pipeline(tree_ensemble_spec, column_transformer_spec)
        pipeline.fit(X_train, y_train)
        scores = positive_scores(pipeline, X_validation)
        selected_ids = sorted(selected_ids_at_budget(validation_ids, scores, budget))
        metric = split_metric_row(
            model_id=model_id,
            model_kind=model_kind,
            split="cv_validation",
            ids=validation_ids,
            y_true=y_validation,
            scores=scores,
            budget=min(budget, len(validation_ids)),
            false_positive_cost=false_positive_cost,
            false_negative_cost=false_negative_cost,
        )
        score_rows.append(
            {
                "fold_id": fold_id,
                "fold_order": order,
                "model_id": model_id,
                "model_kind": model_kind,
                "train_row_count": len(train_ids),
                "validation_row_count": len(validation_ids),
                "train_positive_count": int(y_train.sum()),
                "validation_positive_count": int(y_validation.sum()),
                "selection_budget": min(budget, len(validation_ids)),
                "precision_at_budget": metric["precision_at_budget"],
                "recall_at_budget": metric["recall_at_budget"],
                "average_precision": metric["average_precision"],
                "roc_auc": metric["roc_auc"],
                "log_loss": metric["log_loss"],
                "error_cost_at_budget": metric["error_cost_at_budget"],
                "accuracy_at_0_5": metric["accuracy_at_0_5"],
                "selected_ids": ",".join(selected_ids),
            }
        )
        fit_trace.append(
            {
                "event": "pipeline.fit",
                "fold_id": fold_id,
                "model_id": model_id,
                "train_ids": train_ids,
                "validation_ids": validation_ids,
                "fits_column_transformer": True,
                "fits_estimator": True,
                "test_ids_seen": [],
            }
        )
        selected_set = set(selected_ids)
        for snapshot_id, label, score in zip(
            validation_ids, y_validation.tolist(), scores.tolist(), strict=True
        ):
            prediction_rows.append(
                {
                    "fold_id": fold_id,
                    "fold_order": order,
                    "snapshot_id": snapshot_id,
                    "model_id": model_id,
                    "model_kind": model_kind,
                    "cv_role": "cv_validation",
                    "score": rounded(float(score)),
                    "score_type": cv_plan_spec["score_type"],
                    "actual_label": int(label),
                    "selected_at_budget": int(snapshot_id in selected_set),
                    "trained_on_role": "cv_train",
                    "generated_at": GENERATED_AT,
                }
            )

    if len(score_rows) < TINY_FOLD_WARNING_THRESHOLD:
        checks.append(
            failed(
                "tiny_cv_fold_count_expected",
                len(score_rows),
                f">= {TINY_FOLD_WARNING_THRESHOLD} folds for production CV",
                severity="warning",
            )
        )
    small_validation_folds = [
        row for row in score_rows if row["validation_row_count"] < TINY_VALIDATION_WARNING_THRESHOLD
    ]
    if small_validation_folds:
        checks.append(
            failed(
                "tiny_cv_validation_sample_expected",
                [
                    {"fold_id": row["fold_id"], "validation_row_count": row["validation_row_count"]}
                    for row in small_validation_folds
                ],
                f">= {TINY_VALIDATION_WARNING_THRESHOLD} validation rows per production fold",
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
    precision_values = [float(row["precision_at_budget"]) for row in score_rows]
    log_loss_values = [float(row["log_loss"]) for row in score_rows]
    serialized_spec = {
        "cv_plan_id": cv_plan_spec["cv_plan_id"],
        "problem_id": problem_spec["problem_id"],
        "sklearn_version": sklearn.__version__,
        "tree_ensemble_id": tree_ensemble_spec["tree_ensemble_id"],
        "model": {
            "model_id": model_id,
            "class": "RandomForestClassifier",
            "params": tree_ensemble_spec["candidate"]["params"],
        },
        "fold_strategy": cv_plan_spec["cv_strategy"],
        "scoring": cv_plan_spec["scoring"],
        "fit_trace": fit_trace,
        "test_used_in_cv": False,
        "sklearn_cv_iterator_compatible": True,
    }
    summary = {
        "cv_plan_id": cv_plan_spec["cv_plan_id"],
        "problem_id": problem_spec["problem_id"],
        "sklearn_version": sklearn.__version__,
        "fold_count": len(score_rows),
        "model_id": model_id,
        "primary_metric": cv_plan_spec["scoring"]["primary_metric"],
        "mean_precision_at_budget": rounded(float(np.mean(precision_values))),
        "std_precision_at_budget": rounded(float(np.std(precision_values))),
        "mean_log_loss": rounded(float(np.mean(log_loss_values))),
        "cv_validation_row_count": len(prediction_rows),
        "final_holdout_split": cv_plan_spec["final_holdout_split"],
        "test_used_in_cv": False,
        "blocking_errors": blocking_errors,
        "warnings": warnings,
        "readiness_status": "ready_for_imbalance_lesson"
        if valid
        else "blocked_by_cv_plan_audit",
    }
    report = {
        "valid": valid,
        "problem_id": problem_spec["problem_id"],
        "summary": summary,
        "fold_manifest": normalized_fold_rows(fold_rows),
        "scores": score_rows,
        "predictions": prediction_rows,
        "audit": build_audit_rows(checks),
        "serialized_spec": serialized_spec,
        "checks": checks,
    }

    if fold_manifest_output_path is not None:
        write_csv(
            fold_manifest_output_path,
            report["fold_manifest"],
            [
                "fold_id",
                "fold_order",
                "snapshot_id",
                "user_id",
                "prediction_time",
                "original_split",
                "cv_role",
                "group_key",
                "label",
                "assigned_by_policy",
            ],
        )
    if score_output_path is not None:
        write_csv(
            score_output_path,
            score_rows,
            [
                "fold_id",
                "fold_order",
                "model_id",
                "model_kind",
                "train_row_count",
                "validation_row_count",
                "train_positive_count",
                "validation_positive_count",
                "selection_budget",
                "precision_at_budget",
                "recall_at_budget",
                "average_precision",
                "roc_auc",
                "log_loss",
                "error_cost_at_budget",
                "accuracy_at_0_5",
                "selected_ids",
            ],
        )
    if predictions_output_path is not None:
        write_csv(
            predictions_output_path,
            prediction_rows,
            [
                "fold_id",
                "fold_order",
                "snapshot_id",
                "model_id",
                "model_kind",
                "cv_role",
                "score",
                "score_type",
                "actual_label",
                "selected_at_budget",
                "trained_on_role",
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
    parser = argparse.ArgumentParser(description="Plan and audit group/time-aware CV folds")
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--preprocessing-contract", type=Path, required=True)
    parser.add_argument("--pipeline-spec", type=Path, required=True)
    parser.add_argument("--column-transformer-spec", type=Path, required=True)
    parser.add_argument("--linear-baseline-spec", type=Path, required=True)
    parser.add_argument("--tree-diagnostic-spec", type=Path, required=True)
    parser.add_argument("--tree-ensemble-spec", type=Path, required=True)
    parser.add_argument("--cv-plan-spec", type=Path, required=True)
    parser.add_argument("--features", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--cv-fold-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--fold-manifest-output", type=Path)
    parser.add_argument("--score-output", type=Path)
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
            features_path=args.features,
            labels_path=args.labels,
            manifest_path=args.manifest,
            cv_fold_manifest_path=args.cv_fold_manifest,
            report_output_path=args.output,
            fold_manifest_output_path=args.fold_manifest_output,
            score_output_path=args.score_output,
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
        KeyError,
        ValueError,
    ) as error:
        report = {
            "valid": False,
            "summary": {
                "blocking_errors": ["cv_planner_runtime_error"],
                "warnings": [],
                "readiness_status": "runtime_error",
            },
            "checks": [
                failed(
                    "cv_planner_runtime_error",
                    str(error),
                    "readable inputs and fit-able group/time-aware cross-validation folds",
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
