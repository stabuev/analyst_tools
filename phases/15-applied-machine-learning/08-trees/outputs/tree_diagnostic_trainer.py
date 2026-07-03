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
from sklearn.pipeline import Pipeline
from sklearn.tree import DecisionTreeClassifier, export_text

LINEAR_OUTPUT_ROOT = Path(__file__).resolve().parents[2] / "07-linear-models" / "outputs"
COLUMN_OUTPUT_ROOT = Path(__file__).resolve().parents[2] / "06-column-transformer" / "outputs"
for output_root in (LINEAR_OUTPUT_ROOT, COLUMN_OUTPUT_ROOT):
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
    parse_float,
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
    metric_by_model,
    prediction_rows_for_split,
    run as run_linear_baseline_audit,
    selection_budget,
    split_metric_row,
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
GENERATED_AT = "2026-07-02T12:00:00+03:00"
TINY_TRAIN_WARNING_THRESHOLD = 20


class TreeDiagnosticError(ValueError):
    """Raised when tree diagnostic inputs cannot be parsed."""


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value if value.endswith("\n") else value + "\n", encoding="utf-8")


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


def validate_tree_diagnostic_spec(
    *,
    problem_spec: dict[str, Any],
    pipeline_spec: dict[str, Any],
    column_transformer_spec: dict[str, Any],
    linear_baseline_spec: dict[str, Any],
    tree_diagnostic_spec: dict[str, Any],
) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    expected_identity = {
        "problem_id": problem_spec.get("problem_id"),
        "pipeline_id": pipeline_spec.get("pipeline_id"),
        "column_transformer_id": column_transformer_spec.get("column_transformer_id"),
        "linear_baseline_id": linear_baseline_spec.get("linear_baseline_id"),
    }
    for field, expected in expected_identity.items():
        if tree_diagnostic_spec.get(field) != expected:
            errors.append(
                {"field": field, "observed": tree_diagnostic_spec.get(field), "expected": expected}
            )

    expected_splits = {
        "fit_split": "train",
        "final_holdout_split": "test",
        "diagnostic_role": "non_linear_shape_probe_not_production_promotion",
    }
    for field, expected in expected_splits.items():
        if tree_diagnostic_spec.get(field) != expected:
            errors.append(
                {"field": field, "observed": tree_diagnostic_spec.get(field), "expected": expected}
            )
    if tree_diagnostic_spec.get("diagnostic_splits") != ["train", "validation"]:
        errors.append(
            {
                "field": "diagnostic_splits",
                "observed": tree_diagnostic_spec.get("diagnostic_splits"),
                "expected": ["train", "validation"],
            }
        )
    if tree_diagnostic_spec.get("score_type") != column_transformer_spec.get("score_type"):
        errors.append(
            {
                "field": "score_type",
                "observed": tree_diagnostic_spec.get("score_type"),
                "expected": column_transformer_spec.get("score_type"),
            }
        )

    comparison = tree_diagnostic_spec.get("comparison")
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

    candidate = tree_diagnostic_spec.get("candidate")
    if not isinstance(candidate, dict) or candidate.get("kind") != "decision_tree_classifier":
        errors.append(
            {
                "field": "candidate.kind",
                "observed": candidate.get("kind") if isinstance(candidate, dict) else candidate,
                "expected": "decision_tree_classifier",
            }
        )
    else:
        params = candidate.get("params") if isinstance(candidate.get("params"), dict) else {}
        if params.get("criterion") not in {"gini", "entropy", "log_loss"}:
            errors.append(
                {
                    "field": "candidate.params.criterion",
                    "observed": params.get("criterion"),
                    "expected": "gini, entropy or log_loss",
                }
            )
        max_depth = params.get("max_depth")
        if not isinstance(max_depth, int) or max_depth < 1 or max_depth > 3:
            errors.append(
                {
                    "field": "candidate.params.max_depth",
                    "observed": max_depth,
                    "expected": "integer between 1 and 3 for diagnostic tree",
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

    overfit_policy = tree_diagnostic_spec.get("overfit_policy")
    if not isinstance(overfit_policy, dict):
        errors.append({"field": "overfit_policy", "reason": "object required"})
    else:
        if overfit_policy.get("compare_split_pair") != ["train", "validation"]:
            errors.append(
                {
                    "field": "overfit_policy.compare_split_pair",
                    "observed": overfit_policy.get("compare_split_pair"),
                    "expected": ["train", "validation"],
                }
            )
        thresholds = overfit_policy.get("warning_thresholds")
        if not isinstance(thresholds, dict):
            errors.append(
                {"field": "overfit_policy.warning_thresholds", "reason": "object required"}
            )
        else:
            for metric in ("accuracy_at_0_5", "precision_at_budget", "log_loss"):
                if thresholds.get(metric) is None:
                    errors.append(
                        {
                            "field": f"overfit_policy.warning_thresholds.{metric}",
                            "reason": "required",
                        }
                    )

    rule_export = tree_diagnostic_spec.get("rule_export")
    if not isinstance(rule_export, dict):
        errors.append({"field": "rule_export", "reason": "object required"})
    else:
        if rule_export.get("method") != "sklearn.tree.export_text":
            errors.append(
                {
                    "field": "rule_export.method",
                    "observed": rule_export.get("method"),
                    "expected": "sklearn.tree.export_text",
                }
            )
        if rule_export.get("require_feature_names") is not True:
            errors.append(
                {
                    "field": "rule_export.require_feature_names",
                    "observed": rule_export.get("require_feature_names"),
                    "expected": True,
                }
            )
        limits = rule_export.get("interpretation_limits")
        if not isinstance(limits, list) or len(limits) < 3:
            errors.append(
                {
                    "field": "rule_export.interpretation_limits",
                    "observed": limits,
                    "expected": "at least three explicit limits",
                }
            )

    audit_policy = tree_diagnostic_spec.get("audit_policy")
    if not isinstance(audit_policy, dict):
        errors.append({"field": "audit_policy", "reason": "object required"})
    else:
        for field in (
            "require_linear_baseline_handoff",
            "require_depth_limit",
            "require_min_samples_leaf",
            "require_random_state",
            "require_train_validation_gap",
            "require_rule_export",
            "require_feature_schema_alignment",
            "forbid_fit_on_validation_or_test",
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

    output = tree_diagnostic_spec.get("output")
    if not isinstance(output, dict):
        errors.append({"field": "output", "reason": "object required"})
    else:
        for field in (
            "prediction_file",
            "overfit_file",
            "node_file",
            "rules_file",
            "report_file",
            "serialized_spec_file",
        ):
            if not output.get(field):
                errors.append({"field": f"output.{field}", "reason": "required"})

    if errors:
        return failed(
            "tree_diagnostic_spec_declares_constrained_tree",
            len(errors),
            "depth-limited DecisionTreeClassifier with rule export and gap policy",
            errors,
        )
    return passed(
        "tree_diagnostic_spec_declares_constrained_tree",
        {
            "tree_diagnostic_id": tree_diagnostic_spec["tree_diagnostic_id"],
            "model_id": tree_diagnostic_spec["candidate"]["model_id"],
            "max_depth": tree_diagnostic_spec["candidate"]["params"]["max_depth"],
        },
        "diagnostic tree contract is explicit",
    )


def validate_manifest_for_tree_diagnostic(
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
            "split_manifest_supports_tree_diagnostic_roles",
            len(errors),
            "train fit, validation diagnostics and test final evaluation roles",
            errors,
        )
    return passed(
        "split_manifest_supports_tree_diagnostic_roles",
        split_counts,
        "manifest exposes correct roles for tree diagnostics",
    )


def build_tree_pipeline(
    tree_diagnostic_spec: dict[str, Any], column_transformer_spec: dict[str, Any]
) -> Pipeline:
    candidate = tree_diagnostic_spec["candidate"]
    params = dict(candidate.get("params") or {})
    estimator = DecisionTreeClassifier(**params)
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
        raise TreeDiagnosticError("fitted tree has no positive class 1") from error
    return pipeline.predict_proba(X)[:, positive_index]


def node_depths(estimator: DecisionTreeClassifier) -> dict[int, int]:
    children_left = estimator.tree_.children_left
    children_right = estimator.tree_.children_right
    stack = [(0, 0)]
    depths: dict[int, int] = {}
    while stack:
        node_id, depth = stack.pop()
        depths[node_id] = depth
        left = int(children_left[node_id])
        right = int(children_right[node_id])
        if left != right:
            stack.append((left, depth + 1))
            stack.append((right, depth + 1))
    return depths


def build_node_rows(
    estimator: DecisionTreeClassifier, feature_names: list[str]
) -> list[dict[str, Any]]:
    tree = estimator.tree_
    depths = node_depths(estimator)
    rows: list[dict[str, Any]] = []
    for node_id in range(tree.node_count):
        feature_index = int(tree.feature[node_id])
        is_leaf = int(tree.children_left[node_id]) == int(tree.children_right[node_id])
        class_counts = tree.value[node_id][0].tolist()
        predicted_class = int(estimator.classes_[int(np.argmax(class_counts))])
        rows.append(
            {
                "node_id": node_id,
                "depth": depths[node_id],
                "is_leaf": is_leaf,
                "feature_name": "" if is_leaf else feature_names[feature_index],
                "threshold": "" if is_leaf else rounded(float(tree.threshold[node_id])),
                "left_child": "" if is_leaf else int(tree.children_left[node_id]),
                "right_child": "" if is_leaf else int(tree.children_right[node_id]),
                "impurity": rounded(float(tree.impurity[node_id])),
                "n_node_samples": int(tree.n_node_samples[node_id]),
                "weighted_n_node_samples": rounded(float(tree.weighted_n_node_samples[node_id])),
                "class_0_count": rounded(float(class_counts[0])),
                "class_1_count": rounded(float(class_counts[1])),
                "predicted_class": predicted_class,
            }
        )
    return rows


def tree_rule_text(
    estimator: DecisionTreeClassifier,
    feature_names: list[str],
    tree_diagnostic_spec: dict[str, Any],
) -> str:
    rule_export = tree_diagnostic_spec["rule_export"]
    return export_text(
        estimator,
        feature_names=feature_names,
        max_depth=int(rule_export["max_depth"]),
        show_weights=bool(rule_export["show_weights"]),
        decimals=int(rule_export["decimals"]),
    )


def metrics_by_split(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row["split"]): row for row in rows}


def build_overfit_rows(
    metric_rows: list[dict[str, Any]], tree_diagnostic_spec: dict[str, Any]
) -> list[dict[str, Any]]:
    by_split = metrics_by_split(metric_rows)
    thresholds = tree_diagnostic_spec["overfit_policy"]["warning_thresholds"]
    rows: list[dict[str, Any]] = []
    for metric in tree_diagnostic_spec["overfit_policy"]["metrics"]:
        train_value = float(by_split["train"][metric])
        validation_value = float(by_split["validation"][metric])
        if metric == "log_loss":
            gap = validation_value - train_value
        else:
            gap = train_value - validation_value
        threshold = float(thresholds[metric])
        rows.append(
            {
                "model_id": tree_diagnostic_spec["candidate"]["model_id"],
                "metric": metric,
                "train": rounded(train_value),
                "validation": rounded(validation_value),
                "test": rounded(float(by_split["test"][metric])),
                "train_validation_gap": rounded(gap),
                "warning_threshold": threshold,
                "warning_triggered": gap >= threshold,
            }
        )
    return rows


def validate_fit_trace(trace: list[dict[str, Any]], train_ids: list[str]) -> dict[str, Any]:
    bad_fit_events = [
        event
        for event in trace
        if event["event"] == "pipeline.fit" and event["snapshot_ids"] != train_ids
    ]
    if bad_fit_events:
        return failed(
            "tree_fit_uses_train_only",
            bad_fit_events,
            "tree Pipeline.fit receives exactly train split ids",
        )
    return passed(
        "tree_fit_uses_train_only",
        {"fit_split": "train", "fit_snapshot_ids": train_ids},
        "diagnostic tree fit used train only",
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
        score = parse_float(row["score"])
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
            "tree_predictions_cover_train_validation_and_test",
            len(errors),
            "one tree probability row per train/validation/test snapshot",
            errors,
        )
    return passed(
        "tree_predictions_cover_train_validation_and_test",
        {"rows": len(prediction_rows), "model_id": model_id},
        "tree scored train for gap diagnostics and validation/test for evaluation",
    )


def validate_tree_structure(
    estimator: DecisionTreeClassifier, tree_diagnostic_spec: dict[str, Any]
) -> dict[str, Any]:
    params = tree_diagnostic_spec["candidate"]["params"]
    max_depth_limit = int(params["max_depth"])
    min_samples_leaf = int(params["min_samples_leaf"])
    leaf_node_ids = np.where(estimator.tree_.children_left == -1)[0]
    min_leaf_observed = int(min(estimator.tree_.n_node_samples[leaf_node_ids].tolist()))
    errors: list[dict[str, Any]] = []
    if estimator.get_depth() > max_depth_limit:
        errors.append(
            {
                "field": "depth",
                "observed": estimator.get_depth(),
                "expected": f"<= {max_depth_limit}",
            }
        )
    if min_leaf_observed < min_samples_leaf:
        errors.append(
            {
                "field": "min_leaf_samples",
                "observed": min_leaf_observed,
                "expected": f">= {min_samples_leaf}",
            }
        )
    if errors:
        return failed(
            "tree_depth_and_leaf_constraints_respected",
            len(errors),
            "fitted tree depth and leaf sizes respect diagnostic constraints",
            errors,
        )
    return passed(
        "tree_depth_and_leaf_constraints_respected",
        {
            "actual_depth": estimator.get_depth(),
            "leaf_count": estimator.get_n_leaves(),
            "min_leaf_samples": min_leaf_observed,
        },
        "tree stayed within declared constraints",
    )


def validate_rules(rules: str, feature_names: list[str]) -> dict[str, Any]:
    used_feature_names = [feature for feature in feature_names if feature in rules]
    if not rules.strip() or not used_feature_names:
        return failed(
            "tree_rules_exported_with_feature_names",
            {"rule_length": len(rules), "used_feature_names": used_feature_names},
            "readable rules with transformed feature names",
        )
    return passed(
        "tree_rules_exported_with_feature_names",
        {"line_count": len(rules.splitlines()), "used_feature_names": used_feature_names},
        "tree rules include transformed feature names",
    )


def validate_overfit_rows(overfit_rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not overfit_rows:
        return failed(
            "train_validation_gap_reported",
            [],
            "overfit rows for declared metrics",
        )
    return passed(
        "train_validation_gap_reported",
        {
            "metrics": [row["metric"] for row in overfit_rows],
            "triggered": [row["metric"] for row in overfit_rows if row["warning_triggered"]],
        },
        "train-validation gaps are reported",
    )


def validate_feature_schema(
    feature_schema_rows: list[dict[str, Any]], node_rows: list[dict[str, Any]]
) -> dict[str, Any]:
    known_features = {row["feature_name"] for row in feature_schema_rows}
    split_features = {row["feature_name"] for row in node_rows if row["feature_name"]}
    unknown = sorted(split_features - known_features)
    if unknown:
        return failed(
            "tree_rules_align_with_transformed_feature_schema",
            unknown,
            "split features must come from ColumnTransformer feature schema",
        )
    return passed(
        "tree_rules_align_with_transformed_feature_schema",
        {"split_features": sorted(split_features), "feature_count": len(feature_schema_rows)},
        "tree split features align with transformed schema",
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
    features_path: Path,
    labels_path: Path,
    manifest_path: Path,
    report_output_path: Path | None = None,
    overfit_output_path: Path | None = None,
    node_output_path: Path | None = None,
    rules_output_path: Path | None = None,
    predictions_output_path: Path | None = None,
    serialized_spec_output_path: Path | None = None,
) -> dict[str, Any]:
    problem_spec = read_json(spec_path)
    pipeline_spec = read_json(pipeline_spec_path)
    column_transformer_spec = read_json(column_transformer_spec_path)
    linear_baseline_spec = read_json(linear_baseline_spec_path)
    tree_diagnostic_spec = read_json(tree_diagnostic_spec_path)
    feature_rows, _feature_columns = read_csv(features_path)
    labels, _label_columns = read_csv(labels_path)
    manifest_rows, manifest_columns = read_csv(manifest_path)

    checks: list[dict[str, Any]] = [
        validate_tree_diagnostic_spec(
            problem_spec=problem_spec,
            pipeline_spec=pipeline_spec,
            column_transformer_spec=column_transformer_spec,
            linear_baseline_spec=linear_baseline_spec,
            tree_diagnostic_spec=tree_diagnostic_spec,
        ),
        validate_manifest_for_tree_diagnostic(manifest_rows, manifest_columns),
    ]
    upstream_report = run_linear_baseline_audit(
        spec_path=spec_path,
        preprocessing_contract_path=preprocessing_contract_path,
        pipeline_spec_path=pipeline_spec_path,
        column_transformer_spec_path=column_transformer_spec_path,
        linear_baseline_spec_path=linear_baseline_spec_path,
        features_path=features_path,
        labels_path=labels_path,
        manifest_path=manifest_path,
    )
    if upstream_report.get("valid"):
        checks.append(
            passed(
                "upstream_linear_baseline_audit_is_valid",
                {
                    "linear_baseline_id": linear_baseline_spec.get("linear_baseline_id"),
                    "selected_model_id": upstream_report["summary"].get("selected_model_id"),
                    "readiness_status": upstream_report["summary"].get("readiness_status"),
                },
                "linear baseline handoff is valid",
            )
        )
    else:
        checks.append(
            failed(
                "upstream_linear_baseline_audit_is_valid",
                upstream_report.get("summary", {}).get("blocking_errors", []),
                "valid linear baseline report before tree diagnostic fit",
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
                "tree_diagnostic_id": tree_diagnostic_spec.get("tree_diagnostic_id"),
                "blocking_errors": blocking_errors,
                "warnings": [],
                "readiness_status": "blocked_before_tree_fit",
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
                "train_split_has_both_classes_for_tree_diagnostic",
                sorted(set(y_train.tolist())),
                "binary train labels",
            )
        )
        report = {
            "valid": False,
            "problem_id": problem_spec.get("problem_id"),
            "summary": {
                "tree_diagnostic_id": tree_diagnostic_spec.get("tree_diagnostic_id"),
                "blocking_errors": ["train_split_has_both_classes_for_tree_diagnostic"],
                "warnings": [],
                "readiness_status": "blocked_before_tree_fit",
            },
            "checks": checks,
        }
        if report_output_path is not None:
            write_json(report_output_path, report)
        return report

    pipeline = build_tree_pipeline(tree_diagnostic_spec, column_transformer_spec)
    pipeline.fit(X_train, y_train)
    preprocess = pipeline.named_steps["preprocess"]
    estimator: DecisionTreeClassifier = pipeline.named_steps["estimator"]
    feature_names = [str(value) for value in preprocess.get_feature_names_out()]
    feature_schema_rows = build_feature_schema(feature_names, column_transformer_spec)
    false_positive_cost, false_negative_cost = cost_weights(problem_spec)
    budget = selection_budget(problem_spec)
    model_id = tree_diagnostic_spec["candidate"]["model_id"]
    model_kind = tree_diagnostic_spec["candidate"]["kind"]

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
    for split, ids in (("train", train_ids), ("validation", validation_ids), ("test", test_ids)):
        X_split = make_frame(ids, feature_rows_by_id, column_transformer_spec)
        y_split = make_target(ids, labels_by_id, problem_spec)
        scores = positive_scores(pipeline, X_split)
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
            score_type=tree_diagnostic_spec["score_type"],
            budget=budget,
        )
        for row in split_prediction_rows:
            row["generated_at"] = GENERATED_AT
        prediction_rows.extend(split_prediction_rows)

    rules = tree_rule_text(estimator, feature_names, tree_diagnostic_spec)
    node_rows = build_node_rows(estimator, feature_names)
    overfit_rows = build_overfit_rows(metric_rows, tree_diagnostic_spec)
    checks.append(validate_fit_trace(fit_trace, train_ids))
    checks.append(validate_predictions(prediction_rows, manifest_rows, model_id))
    checks.append(validate_tree_structure(estimator, tree_diagnostic_spec))
    checks.append(validate_rules(rules, feature_names))
    checks.append(validate_overfit_rows(overfit_rows))
    checks.append(validate_feature_schema(feature_schema_rows, node_rows))

    unknown_warning = first_warning_check(
        upstream_report, "linear_baseline_unknown_categories_bucketed"
    )
    if unknown_warning is not None and not unknown_warning.get("valid", True):
        checks.append(
            failed(
                "tree_unknown_categories_bucketed",
                unknown_warning.get("observed"),
                "unknown validation/test categories inherited explicit ColumnTransformer bucket",
                unknown_warning.get("sample", []),
                severity="warning",
            )
        )
    if len(train_ids) < TINY_TRAIN_WARNING_THRESHOLD:
        checks.append(
            failed(
                "tiny_tree_training_sample_expected",
                len(train_ids),
                f">= {TINY_TRAIN_WARNING_THRESHOLD} train rows for production tree diagnostics",
                severity="warning",
            )
        )

    triggered_gaps = [row for row in overfit_rows if row["warning_triggered"]]
    if triggered_gaps:
        checks.append(
            failed(
                "tree_train_validation_gap_exceeds_threshold",
                [
                    {
                        "metric": row["metric"],
                        "train_validation_gap": row["train_validation_gap"],
                        "warning_threshold": row["warning_threshold"],
                    }
                    for row in triggered_gaps
                ],
                "train-validation gap below warning thresholds",
                severity="warning",
            )
        )

    selected_baseline_id = upstream_report["summary"]["selected_model_id"]
    baseline_validation_precision = upstream_report["summary"]["validation_metrics"][
        "precision_at_budget"
    ][selected_baseline_id]
    tree_validation_precision = metric_by_model(metric_rows, "validation", "precision_at_budget")[
        model_id
    ]
    if float(tree_validation_precision) < float(baseline_validation_precision):
        checks.append(
            failed(
                "tree_diagnostic_worse_than_selected_baseline_on_validation",
                {
                    "tree_precision_at_budget": tree_validation_precision,
                    "selected_baseline_id": selected_baseline_id,
                    "selected_baseline_precision_at_budget": baseline_validation_precision,
                },
                "diagnostic tree should not be promoted when it is worse than selected baseline",
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
    by_split = metrics_by_split(metric_rows)
    train_validation_gaps = {row["metric"]: row["train_validation_gap"] for row in overfit_rows}
    split_features = sorted({row["feature_name"] for row in node_rows if row["feature_name"]})
    serialized_spec = {
        "tree_diagnostic_id": tree_diagnostic_spec["tree_diagnostic_id"],
        "problem_id": problem_spec["problem_id"],
        "sklearn_version": sklearn.__version__,
        "column_transformer_id": column_transformer_spec["column_transformer_id"],
        "linear_baseline_id": linear_baseline_spec["linear_baseline_id"],
        "model": {
            "model_id": model_id,
            "class": "DecisionTreeClassifier",
            "params": tree_diagnostic_spec["candidate"]["params"],
            "classes": [int(value) for value in estimator.classes_],
            "actual_depth": estimator.get_depth(),
            "leaf_count": estimator.get_n_leaves(),
            "node_count": int(estimator.tree_.node_count),
            "split_features": split_features,
        },
        "fit_trace": fit_trace,
        "feature_schema": feature_schema_rows,
        "baseline_reference": {
            "selected_baseline_id": selected_baseline_id,
            "selected_on_split": "validation",
            "test_used_for_selection": False,
        },
        "rule_export": {
            "method": tree_diagnostic_spec["rule_export"]["method"],
            "line_count": len(rules.splitlines()),
            "interpretation_limits": tree_diagnostic_spec["rule_export"]["interpretation_limits"],
        },
    }
    summary = {
        "tree_diagnostic_id": tree_diagnostic_spec["tree_diagnostic_id"],
        "problem_id": problem_spec["problem_id"],
        "sklearn_version": sklearn.__version__,
        "fit_split": "train",
        "fit_row_count": len(train_ids),
        "diagnostic_splits": tree_diagnostic_spec["diagnostic_splits"],
        "final_holdout_split": "test",
        "model_id": model_id,
        "max_depth_limit": tree_diagnostic_spec["candidate"]["params"]["max_depth"],
        "actual_tree_depth": estimator.get_depth(),
        "leaf_count": estimator.get_n_leaves(),
        "node_count": int(estimator.tree_.node_count),
        "transformed_feature_count": len(feature_schema_rows),
        "prediction_row_count": len(prediction_rows),
        "rule_line_count": len(rules.splitlines()),
        "split_features": split_features,
        "selected_linear_baseline_id": selected_baseline_id,
        "baseline_validation_precision_at_budget": baseline_validation_precision,
        "tree_validation_precision_at_budget": tree_validation_precision,
        "train_metrics": {
            metric: by_split["train"][metric]
            for metric in (
                "precision_at_budget",
                "recall_at_budget",
                "average_precision",
                "log_loss",
                "error_cost_at_budget",
                "accuracy_at_0_5",
            )
        },
        "validation_metrics": {
            metric: by_split["validation"][metric]
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
            metric: by_split["test"][metric]
            for metric in (
                "precision_at_budget",
                "recall_at_budget",
                "average_precision",
                "log_loss",
                "error_cost_at_budget",
                "accuracy_at_0_5",
            )
        },
        "train_validation_gaps": train_validation_gaps,
        "rule_interpretation_limits": tree_diagnostic_spec["rule_export"]["interpretation_limits"],
        "upstream_warnings": upstream_report["summary"].get("warnings", []),
        "blocking_errors": blocking_errors,
        "warnings": warnings,
        "readiness_status": "ready_for_tree_ensemble_lesson"
        if valid
        else "blocked_by_tree_diagnostic_audit",
    }
    report = {
        "valid": valid,
        "problem_id": problem_spec["problem_id"],
        "summary": summary,
        "metrics": metric_rows,
        "overfit": overfit_rows,
        "nodes": node_rows,
        "rules": rules,
        "predictions": prediction_rows,
        "serialized_spec": serialized_spec,
        "checks": checks,
    }

    if overfit_output_path is not None:
        write_csv(
            overfit_output_path,
            overfit_rows,
            [
                "model_id",
                "metric",
                "train",
                "validation",
                "test",
                "train_validation_gap",
                "warning_threshold",
                "warning_triggered",
            ],
        )
    if node_output_path is not None:
        write_csv(
            node_output_path,
            node_rows,
            [
                "node_id",
                "depth",
                "is_leaf",
                "feature_name",
                "threshold",
                "left_child",
                "right_child",
                "impurity",
                "n_node_samples",
                "weighted_n_node_samples",
                "class_0_count",
                "class_1_count",
                "predicted_class",
            ],
        )
    if rules_output_path is not None:
        write_text(rules_output_path, rules)
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
    parser = argparse.ArgumentParser(description="Train and audit a diagnostic decision tree")
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--preprocessing-contract", type=Path, required=True)
    parser.add_argument("--pipeline-spec", type=Path, required=True)
    parser.add_argument("--column-transformer-spec", type=Path, required=True)
    parser.add_argument("--linear-baseline-spec", type=Path, required=True)
    parser.add_argument("--tree-diagnostic-spec", type=Path, required=True)
    parser.add_argument("--features", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--overfit-output", type=Path)
    parser.add_argument("--node-output", type=Path)
    parser.add_argument("--rules-output", type=Path)
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
            features_path=args.features,
            labels_path=args.labels,
            manifest_path=args.manifest,
            report_output_path=args.output,
            overfit_output_path=args.overfit_output,
            node_output_path=args.node_output,
            rules_output_path=args.rules_output,
            predictions_output_path=args.predictions_output,
            serialized_spec_output_path=args.serialized_spec_output,
        )
    except (
        OSError,
        json.JSONDecodeError,
        ColumnTransformerAuditError,
        LinearBaselineError,
        TreeDiagnosticError,
        KeyError,
        ValueError,
    ) as error:
        report = {
            "valid": False,
            "summary": {
                "blocking_errors": ["tree_diagnostic_runtime_error"],
                "warnings": [],
                "readiness_status": "runtime_error",
            },
            "checks": [
                failed(
                    "tree_diagnostic_runtime_error",
                    str(error),
                    "readable inputs and fit-able diagnostic DecisionTreeClassifier Pipeline",
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
