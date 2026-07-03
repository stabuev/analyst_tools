from __future__ import annotations

# ruff: noqa: E402, I001

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

import sklearn

CALIBRATION_OUTPUT_ROOT = Path(__file__).resolve().parents[2] / "12-calibration" / "outputs"
IMBALANCE_OUTPUT_ROOT = Path(__file__).resolve().parents[2] / "11-imbalanced-data" / "outputs"
COLUMN_OUTPUT_ROOT = Path(__file__).resolve().parents[2] / "06-column-transformer" / "outputs"
for output_root in (CALIBRATION_OUTPUT_ROOT, IMBALANCE_OUTPUT_ROOT, COLUMN_OUTPUT_ROOT):
    if str(output_root) not in sys.path:
        sys.path.insert(0, str(output_root))

from column_transformer_auditor import (  # noqa: E402
    ColumnTransformerAuditError,
    failed,
    passed,
    read_csv,
    read_json,
    rounded,
    write_json,
)
from imbalance_policy_evaluator import (  # noqa: E402
    ImbalancePolicyError,
    json_ready,
)
from probability_calibration_auditor import (  # noqa: E402
    CalibrationPolicyError,
    run as run_calibration_audit,
)

GENERATED_AT = "2026-07-03T10:00:00+03:00"


class MLLeakageAuditError(ValueError):
    """Raised when leakage audit inputs cannot be parsed."""


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized == "true":
            return True
        if normalized == "false":
            return False
    raise MLLeakageAuditError(f"expected boolean-like value, got {value!r}")


def validate_leakage_policy_spec(
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
    leakage_policy_spec: dict[str, Any],
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
        "calibration_policy_id": calibration_policy_spec.get("calibration_policy_id"),
    }
    for field, expected in expected_identity.items():
        if leakage_policy_spec.get(field) != expected:
            errors.append(
                {
                    "field": field,
                    "observed": leakage_policy_spec.get(field),
                    "expected": expected,
                }
            )

    expected_splits = {
        "fit_split": "train",
        "validation_split": "validation",
        "test_split": "test",
    }
    for field, expected in expected_splits.items():
        if leakage_policy_spec.get(field) != expected:
            errors.append(
                {"field": field, "observed": leakage_policy_spec.get(field), "expected": expected}
            )

    expected_model = calibration_policy_spec.get("source_model_id")
    if leakage_policy_spec.get("source_model_id") != expected_model:
        errors.append(
            {
                "field": "source_model_id",
                "observed": leakage_policy_spec.get("source_model_id"),
                "expected": expected_model,
            }
        )

    for field in (
        "feature_availability_file",
        "feature_selection_log_file",
        "model_selection_log_file",
    ):
        if not leakage_policy_spec.get(field):
            errors.append({"field": field, "reason": "required"})

    feature_policy = leakage_policy_spec.get("feature_availability_policy")
    if not isinstance(feature_policy, dict):
        errors.append({"field": "feature_availability_policy", "reason": "object required"})
    else:
        if feature_policy.get("prediction_time_column") != problem_spec["prediction_time"]["column"]:
            errors.append(
                {
                    "field": "feature_availability_policy.prediction_time_column",
                    "observed": feature_policy.get("prediction_time_column"),
                    "expected": problem_spec["prediction_time"]["column"],
                }
            )
        if set(feature_policy.get("allowed_timings") or []) != {
            "known_before_prediction_time",
            "lookback_before_prediction_time",
        }:
            errors.append(
                {
                    "field": "feature_availability_policy.allowed_timings",
                    "observed": feature_policy.get("allowed_timings"),
                    "expected": [
                        "known_before_prediction_time",
                        "lookback_before_prediction_time",
                    ],
                }
            )
        forbidden = set(feature_policy.get("forbidden_timings") or [])
        if not {
            "post_prediction_time",
            "intervention_after_prediction_time",
            "label_after_prediction_time",
            "full_sample_label_aggregation",
        }.issubset(forbidden):
            errors.append(
                {
                    "field": "feature_availability_policy.forbidden_timings",
                    "observed": sorted(forbidden),
                    "expected": "post-prediction, intervention, label and full-sample timings",
                }
            )
        for field in (
            "require_source_in_problem_allowed_sources",
            "forbid_label_or_post_prediction_features",
            "forbid_forbidden_source_usage_in_delivery_model",
        ):
            if feature_policy.get(field) is not True:
                errors.append(
                    {
                        "field": f"feature_availability_policy.{field}",
                        "observed": feature_policy.get(field),
                        "expected": True,
                    }
                )

    preprocessing_policy = leakage_policy_spec.get("preprocessing_scope_policy")
    if not isinstance(preprocessing_policy, dict):
        errors.append({"field": "preprocessing_scope_policy", "reason": "object required"})
    else:
        expected = {
            "fit_scope": "train_only",
            "require_pipeline_preprocessing": True,
            "forbid_full_sample_fit": True,
            "forbid_fit_on_validation_or_test": True,
        }
        for field, expected_value in expected.items():
            if preprocessing_policy.get(field) != expected_value:
                errors.append(
                    {
                        "field": f"preprocessing_scope_policy.{field}",
                        "observed": preprocessing_policy.get(field),
                        "expected": expected_value,
                    }
                )
        audited = set(preprocessing_policy.get("audited_specs") or [])
        if not {
            "preprocessing_contract",
            "pipeline_spec",
            "column_transformer_spec",
            "calibration_policy_spec",
        }.issubset(audited):
            errors.append(
                {
                    "field": "preprocessing_scope_policy.audited_specs",
                    "observed": sorted(audited),
                    "expected": "preprocessing, pipeline, column transformer and calibration specs",
                }
            )

    feature_selection_policy = leakage_policy_spec.get("feature_selection_policy")
    if not isinstance(feature_selection_policy, dict):
        errors.append({"field": "feature_selection_policy", "reason": "object required"})
    else:
        allowed = set(feature_selection_policy.get("allowed_scopes") or [])
        forbidden = set(feature_selection_policy.get("forbidden_scopes") or [])
        if not {"predeclared_business_contract", "inside_cv_pipeline"}.issubset(allowed):
            errors.append(
                {
                    "field": "feature_selection_policy.allowed_scopes",
                    "observed": sorted(allowed),
                    "expected": ["predeclared_business_contract", "inside_cv_pipeline"],
                }
            )
        if not {"all_rows_before_split", "validation_before_cv", "test_or_holdout"}.issubset(
            forbidden
        ):
            errors.append(
                {
                    "field": "feature_selection_policy.forbidden_scopes",
                    "observed": sorted(forbidden),
                    "expected": ["all_rows_before_split", "validation_before_cv", "test_or_holdout"],
                }
            )
        for field in (
            "forbid_select_k_best_before_split",
            "require_selector_inside_cv_if_label_aware",
            "forbid_delivery_selector_using_validation_or_test_labels",
        ):
            if feature_selection_policy.get(field) is not True:
                errors.append(
                    {
                        "field": f"feature_selection_policy.{field}",
                        "observed": feature_selection_policy.get(field),
                        "expected": True,
                    }
                )

    model_selection_policy = leakage_policy_spec.get("model_selection_policy")
    if not isinstance(model_selection_policy, dict):
        errors.append({"field": "model_selection_policy", "reason": "object required"})
    else:
        if model_selection_policy.get("selected_model_id") != leakage_policy_spec.get(
            "source_model_id"
        ):
            errors.append(
                {
                    "field": "model_selection_policy.selected_model_id",
                    "observed": model_selection_policy.get("selected_model_id"),
                    "expected": leakage_policy_spec.get("source_model_id"),
                }
            )
        expected = {
            "selection_split": "validation",
            "final_holdout_split": "test",
            "forbid_test_metric_in_selection": True,
            "forbid_validation_score_cherry_picking": True,
            "require_candidate_registry": True,
            "require_single_selected_delivery_model": True,
        }
        for field, expected_value in expected.items():
            if model_selection_policy.get(field) != expected_value:
                errors.append(
                    {
                        "field": f"model_selection_policy.{field}",
                        "observed": model_selection_policy.get(field),
                        "expected": expected_value,
                    }
                )

    audit_policy = leakage_policy_spec.get("audit_policy")
    if not isinstance(audit_policy, dict):
        errors.append({"field": "audit_policy", "reason": "object required"})
    else:
        for field in (
            "require_calibration_handoff",
            "require_feature_availability_report",
            "require_forbidden_feature_report",
            "require_preprocessing_scope_audit",
            "require_feature_selection_scope_audit",
            "require_model_selection_audit",
            "forbid_post_outcome_features",
            "forbid_full_sample_preprocessing",
            "forbid_feature_selection_outside_cv",
            "forbid_test_selection_or_cherry_picking",
        ):
            if audit_policy.get(field) is not True:
                errors.append(
                    {
                        "field": f"audit_policy.{field}",
                        "observed": audit_policy.get(field),
                        "expected": True,
                    }
                )

    output = leakage_policy_spec.get("output")
    if not isinstance(output, dict):
        errors.append({"field": "output", "reason": "object required"})
    else:
        for field in (
            "feature_availability_file",
            "forbidden_feature_file",
            "preprocessing_scope_file",
            "feature_selection_file",
            "model_selection_file",
            "audit_file",
            "report_file",
            "serialized_spec_file",
        ):
            if not output.get(field):
                errors.append({"field": f"output.{field}", "reason": "required"})

    if errors:
        return failed(
            "leakage_policy_spec_declares_audit_contract",
            len(errors),
            "leakage policy with feature availability, preprocessing, feature selection and model selection gates",
            errors,
        )
    return passed(
        "leakage_policy_spec_declares_audit_contract",
        {
            "leakage_policy_id": leakage_policy_spec["leakage_policy_id"],
            "source_model_id": leakage_policy_spec["source_model_id"],
            "selected_model_id": leakage_policy_spec["model_selection_policy"][
                "selected_model_id"
            ],
        },
        "leakage policy contract is explicit",
    )


def build_feature_availability_rows(
    *,
    feature_rows: list[dict[str, str]],
    source_rows: list[dict[str, str]],
    problem_spec: dict[str, Any],
    leakage_policy_spec: dict[str, Any],
) -> list[dict[str, Any]]:
    source_by_id = {row["source_id"]: row for row in source_rows}
    allowed_sources = set(problem_spec.get("allowed_feature_sources") or [])
    forbidden_sources = set(problem_spec.get("forbidden_feature_sources") or [])
    policy = leakage_policy_spec["feature_availability_policy"]
    allowed_timings = set(policy["allowed_timings"])
    forbidden_timings = set(policy["forbidden_timings"])
    rows: list[dict[str, Any]] = []
    for row in feature_rows:
        source = source_by_id.get(row["source_id"], {})
        used_in_delivery = parse_bool(row["used_in_delivery_model"])
        source_allowed = row["source_id"] in allowed_sources
        source_forbidden = row["source_id"] in forbidden_sources
        timing_allowed = row["timing"] in allowed_timings
        timing_forbidden = row["timing"] in forbidden_timings
        source_inventory_allowed = source.get("allowed") == "true"
        candidate_allowed = source_allowed and timing_allowed and not timing_forbidden
        blocking_if_used = used_in_delivery and (
            not candidate_allowed or source_forbidden or not source_inventory_allowed
        )
        rows.append(
            {
                "feature_name": row["feature_name"],
                "source_id": row["source_id"],
                "source_table": row["source_table"],
                "feature_role": row["feature_role"],
                "timing": row["timing"],
                "risk_type": row["risk_type"],
                "used_in_delivery_model": used_in_delivery,
                "source_allowed_by_problem": source_allowed,
                "source_forbidden_by_problem": source_forbidden,
                "source_inventory_allowed": source_inventory_allowed,
                "timing_allowed_by_policy": timing_allowed,
                "timing_forbidden_by_policy": timing_forbidden,
                "candidate_allowed": candidate_allowed,
                "blocking_if_used": blocking_if_used,
                "decision": "allowed_delivery_feature"
                if used_in_delivery and not blocking_if_used
                else "rejected_known_bad_candidate"
                if not used_in_delivery and not candidate_allowed
                else "blocked_delivery_feature"
                if blocking_if_used
                else "unused_allowed_candidate",
                "notes": row["notes"],
            }
        )
    return rows


def build_forbidden_feature_rows(feature_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row
        for row in feature_rows
        if row["source_forbidden_by_problem"]
        or row["timing_forbidden_by_policy"]
        or row["risk_type"] != "none"
    ]


def build_preprocessing_scope_rows(
    *,
    preprocessing_contract: dict[str, Any],
    pipeline_spec: dict[str, Any],
    column_transformer_spec: dict[str, Any],
    calibration_policy_spec: dict[str, Any],
) -> list[dict[str, Any]]:
    rows = [
        {
            "component_id": preprocessing_contract["contract_id"],
            "component_type": "preprocessing_contract",
            "declared_fit_split": preprocessing_contract.get("fit_split"),
            "transform_or_predict_splits": ",".join(
                preprocessing_contract.get("transform_splits") or []
            ),
            "preprocessing_location": "contract",
            "full_sample_fit_detected": preprocessing_contract.get("fit_split") != "train",
            "validation_used_for_fit": preprocessing_contract.get("fit_split") == "validation",
            "test_used_for_fit": preprocessing_contract.get("fit_split") == "test",
            "valid": preprocessing_contract.get("fit_split") == "train",
            "notes": "fit imputation and scaling on train only",
        },
        {
            "component_id": pipeline_spec["pipeline_id"],
            "component_type": "pipeline_spec",
            "declared_fit_split": pipeline_spec.get("fit_split"),
            "transform_or_predict_splits": ",".join(pipeline_spec.get("predict_splits") or []),
            "preprocessing_location": pipeline_spec.get("preprocessing_location"),
            "full_sample_fit_detected": pipeline_spec.get("fit_split") != "train",
            "validation_used_for_fit": pipeline_spec.get("fit_split") == "validation",
            "test_used_for_fit": pipeline_spec.get("fit_split") == "test",
            "valid": pipeline_spec.get("fit_split") == "train"
            and pipeline_spec.get("preprocessing_location") == "inside_pipeline",
            "notes": "preprocessing and estimator are fit as one pipeline",
        },
        {
            "component_id": column_transformer_spec["column_transformer_id"],
            "component_type": "column_transformer_spec",
            "declared_fit_split": column_transformer_spec.get("fit_split"),
            "transform_or_predict_splits": ",".join(
                column_transformer_spec.get("predict_splits") or []
            ),
            "preprocessing_location": column_transformer_spec.get("preprocessing_location"),
            "full_sample_fit_detected": column_transformer_spec.get("fit_split") != "train",
            "validation_used_for_fit": column_transformer_spec.get("fit_split") == "validation",
            "test_used_for_fit": column_transformer_spec.get("fit_split") == "test",
            "valid": column_transformer_spec.get("fit_split") == "train"
            and column_transformer_spec.get("preprocessing_location") == "inside_pipeline",
            "notes": "ColumnTransformer categories and imputers are learned on train",
        },
        {
            "component_id": calibration_policy_spec["calibration_policy_id"],
            "component_type": "calibration_policy_spec",
            "declared_fit_split": calibration_policy_spec.get("fit_split"),
            "transform_or_predict_splits": ",".join(
                [
                    calibration_policy_spec.get("calibration_split", ""),
                    calibration_policy_spec.get("evaluation_split", ""),
                ]
            ),
            "preprocessing_location": "upstream_pipeline",
            "full_sample_fit_detected": calibration_policy_spec.get("fit_split") != "train",
            "validation_used_for_fit": False,
            "test_used_for_fit": False,
            "valid": calibration_policy_spec.get("fit_split") == "train"
            and calibration_policy_spec.get("evaluation_split") == "test",
            "notes": "base model fit remains train-only; calibrator is audited separately",
        },
    ]
    return rows


def build_feature_selection_rows(
    *,
    log_rows: list[dict[str, str]],
    leakage_policy_spec: dict[str, Any],
) -> list[dict[str, Any]]:
    policy = leakage_policy_spec["feature_selection_policy"]
    allowed_scopes = set(policy["allowed_scopes"])
    forbidden_scopes = set(policy["forbidden_scopes"])
    rows: list[dict[str, Any]] = []
    for row in log_rows:
        uses_labels = parse_bool(row["uses_labels"])
        uses_validation = parse_bool(row["uses_validation_labels"])
        uses_test = parse_bool(row["uses_test_labels"])
        inside_cv = parse_bool(row["inside_cv"])
        selected = parse_bool(row["selected_for_delivery"])
        scope_allowed = row["scope"] in allowed_scopes
        scope_forbidden = row["scope"] in forbidden_scopes
        label_aware_scope_valid = not uses_labels or inside_cv or row["scope"] == "predeclared_business_contract"
        validation_or_test_labels_used = uses_validation or uses_test
        delivery_valid = (
            scope_allowed
            and not scope_forbidden
            and label_aware_scope_valid
            and not (selected and validation_or_test_labels_used)
        )
        blocking_if_selected = selected and not delivery_valid
        rows.append(
            {
                "selector_id": row["selector_id"],
                "selector_kind": row["selector_kind"],
                "scope": row["scope"],
                "fit_split": row["fit_split"],
                "uses_labels": uses_labels,
                "uses_validation_labels": uses_validation,
                "uses_test_labels": uses_test,
                "inside_pipeline": parse_bool(row["inside_pipeline"]),
                "inside_cv": inside_cv,
                "selected_for_delivery": selected,
                "scope_allowed": scope_allowed,
                "scope_forbidden": scope_forbidden,
                "label_aware_scope_valid": label_aware_scope_valid,
                "blocking_if_selected": blocking_if_selected,
                "decision": "allowed_delivery_selector"
                if selected and not blocking_if_selected
                else "rejected_known_bad_selector"
                if scope_forbidden
                else "allowed_future_pattern",
                "status": row["status"],
                "notes": row["notes"],
            }
        )
    return rows


def build_model_selection_rows(
    *,
    log_rows: list[dict[str, str]],
    leakage_policy_spec: dict[str, Any],
) -> list[dict[str, Any]]:
    policy = leakage_policy_spec["model_selection_policy"]
    rows: list[dict[str, Any]] = []
    for row in log_rows:
        selected = parse_bool(row["selected_for_delivery"])
        test_visible = parse_bool(row["test_metric_visible_to_selector"])
        split_valid = row["selection_split"] == policy["selection_split"]
        selected_model_valid = not selected or row["candidate_id"] == policy["selected_model_id"]
        test_selection = row["selection_split"] == policy["final_holdout_split"] or test_visible
        blocking_if_selected = selected and (not split_valid or test_selection or not selected_model_valid)
        rows.append(
            {
                "candidate_id": row["candidate_id"],
                "candidate_family": row["candidate_family"],
                "selection_stage": row["selection_stage"],
                "selection_split": row["selection_split"],
                "validation_precision_at_budget": rounded(
                    float(row["validation_precision_at_budget"])
                )
                if row["validation_precision_at_budget"]
                else "",
                "test_precision_at_budget": rounded(float(row["test_precision_at_budget"]))
                if row["test_precision_at_budget"]
                else "",
                "test_metric_visible_to_selector": test_visible,
                "selected_for_delivery": selected,
                "selection_rank": row["selection_rank"],
                "selection_split_valid": split_valid,
                "selected_model_valid": selected_model_valid,
                "test_selection_or_cherry_pick": test_selection,
                "blocking_if_selected": blocking_if_selected,
                "decision": "selected_on_validation"
                if selected and not blocking_if_selected
                else "rejected_test_cherry_pick"
                if test_selection
                else "evaluated_not_selected",
                "status": row["status"],
                "notes": row["notes"],
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
    leakage_policy_spec_path: Path,
    feature_source_inventory_path: Path,
    feature_availability_path: Path,
    feature_selection_log_path: Path,
    model_selection_log_path: Path,
    features_path: Path,
    labels_path: Path,
    manifest_path: Path,
    cv_fold_manifest_path: Path,
    report_output_path: Path | None = None,
    feature_availability_output_path: Path | None = None,
    forbidden_feature_output_path: Path | None = None,
    preprocessing_scope_output_path: Path | None = None,
    feature_selection_output_path: Path | None = None,
    model_selection_output_path: Path | None = None,
    audit_output_path: Path | None = None,
    serialized_spec_output_path: Path | None = None,
) -> dict[str, Any]:
    problem_spec = read_json(spec_path)
    preprocessing_contract = read_json(preprocessing_contract_path)
    pipeline_spec = read_json(pipeline_spec_path)
    column_transformer_spec = read_json(column_transformer_spec_path)
    linear_baseline_spec = read_json(linear_baseline_spec_path)
    tree_diagnostic_spec = read_json(tree_diagnostic_spec_path)
    tree_ensemble_spec = read_json(tree_ensemble_spec_path)
    cv_plan_spec = read_json(cv_plan_spec_path)
    imbalance_policy_spec = read_json(imbalance_policy_spec_path)
    calibration_policy_spec = read_json(calibration_policy_spec_path)
    leakage_policy_spec = read_json(leakage_policy_spec_path)
    feature_source_rows, _source_columns = read_csv(feature_source_inventory_path)
    feature_rows, _feature_columns = read_csv(feature_availability_path)
    feature_selection_log, _selector_columns = read_csv(feature_selection_log_path)
    model_selection_log, _model_selection_columns = read_csv(model_selection_log_path)

    checks: list[dict[str, Any]] = [
        validate_leakage_policy_spec(
            problem_spec=problem_spec,
            pipeline_spec=pipeline_spec,
            column_transformer_spec=column_transformer_spec,
            linear_baseline_spec=linear_baseline_spec,
            tree_diagnostic_spec=tree_diagnostic_spec,
            tree_ensemble_spec=tree_ensemble_spec,
            cv_plan_spec=cv_plan_spec,
            imbalance_policy_spec=imbalance_policy_spec,
            calibration_policy_spec=calibration_policy_spec,
            leakage_policy_spec=leakage_policy_spec,
        )
    ]

    calibration_report = run_calibration_audit(
        spec_path=spec_path,
        preprocessing_contract_path=preprocessing_contract_path,
        pipeline_spec_path=pipeline_spec_path,
        column_transformer_spec_path=column_transformer_spec_path,
        linear_baseline_spec_path=linear_baseline_spec_path,
        tree_diagnostic_spec_path=tree_diagnostic_spec_path,
        tree_ensemble_spec_path=tree_ensemble_spec_path,
        cv_plan_spec_path=cv_plan_spec_path,
        imbalance_policy_spec_path=imbalance_policy_spec_path,
        calibration_policy_spec_path=calibration_policy_spec_path,
        features_path=features_path,
        labels_path=labels_path,
        manifest_path=manifest_path,
        cv_fold_manifest_path=cv_fold_manifest_path,
    )
    if calibration_report.get("valid") and (
        calibration_report.get("summary", {}).get("readiness_status")
        == "ready_for_leakage_lesson"
    ):
        checks.append(
            passed(
                "upstream_calibration_handoff_is_valid",
                {
                    "calibration_policy_id": calibration_policy_spec.get("calibration_policy_id"),
                    "source_model_id": calibration_report["summary"].get("source_model_id"),
                    "readiness_status": calibration_report["summary"].get("readiness_status"),
                },
                "calibration handoff is valid and ready for leakage audit",
            )
        )
    else:
        checks.append(
            failed(
                "upstream_calibration_handoff_is_valid",
                calibration_report.get("summary", {}).get("blocking_errors", []),
                "valid calibration report with ready_for_leakage_lesson",
                calibration_report.get("checks", []),
            )
        )

    spec_blocking_errors = [
        check["id"] for check in checks if check["severity"] == "error" and not check["valid"]
    ]
    if spec_blocking_errors:
        report = {
            "valid": False,
            "problem_id": problem_spec.get("problem_id"),
            "summary": {
                "leakage_policy_id": leakage_policy_spec.get("leakage_policy_id"),
                "blocking_errors": spec_blocking_errors,
                "warnings": [],
                "readiness_status": "blocked_before_leakage_audit",
            },
            "checks": checks,
        }
        if report_output_path is not None:
            write_json(report_output_path, json_ready(report))
        return report

    feature_availability_rows = build_feature_availability_rows(
        feature_rows=feature_rows,
        source_rows=feature_source_rows,
        problem_spec=problem_spec,
        leakage_policy_spec=leakage_policy_spec,
    )
    forbidden_feature_rows = build_forbidden_feature_rows(feature_availability_rows)
    blocked_delivery_features = [
        row for row in feature_availability_rows if row["blocking_if_used"]
    ]
    if blocked_delivery_features:
        checks.append(
            failed(
                "leakage_no_forbidden_features_in_delivery_model",
                [
                    {"feature_name": row["feature_name"], "risk_type": row["risk_type"]}
                    for row in blocked_delivery_features
                ],
                "no forbidden or unavailable feature may be used by delivery model",
            )
        )
    else:
        checks.append(
            passed(
                "leakage_no_forbidden_features_in_delivery_model",
                {
                    "delivery_feature_count": sum(
                        1 for row in feature_availability_rows if row["used_in_delivery_model"]
                    ),
                    "blocked_delivery_feature_count": 0,
                },
                "delivery model uses only prediction-time-safe features",
            )
        )
    if forbidden_feature_rows:
        checks.append(
            failed(
                "leakage_forbidden_feature_candidates_reported",
                {
                    "forbidden_candidate_count": len(forbidden_feature_rows),
                    "used_in_delivery_model": sum(
                        1 for row in forbidden_feature_rows if row["used_in_delivery_model"]
                    ),
                },
                "forbidden candidates should be visible and rejected",
                severity="warning",
            )
        )

    preprocessing_scope_rows = build_preprocessing_scope_rows(
        preprocessing_contract=preprocessing_contract,
        pipeline_spec=pipeline_spec,
        column_transformer_spec=column_transformer_spec,
        calibration_policy_spec=calibration_policy_spec,
    )
    invalid_preprocessing_rows = [row for row in preprocessing_scope_rows if not row["valid"]]
    if invalid_preprocessing_rows:
        checks.append(
            failed(
                "leakage_preprocessing_fit_scope_is_train_only",
                [
                    {
                        "component_id": row["component_id"],
                        "declared_fit_split": row["declared_fit_split"],
                    }
                    for row in invalid_preprocessing_rows
                ],
                "all preprocessing fit scopes must be train-only and inside pipeline",
            )
        )
    else:
        checks.append(
            passed(
                "leakage_preprocessing_fit_scope_is_train_only",
                {"audited_components": len(preprocessing_scope_rows)},
                "no full-sample preprocessing fit is detected",
            )
        )

    feature_selection_rows = build_feature_selection_rows(
        log_rows=feature_selection_log,
        leakage_policy_spec=leakage_policy_spec,
    )
    selected_bad_selectors = [
        row for row in feature_selection_rows if row["blocking_if_selected"]
    ]
    if selected_bad_selectors:
        checks.append(
            failed(
                "leakage_feature_selection_not_outside_cv",
                [
                    {"selector_id": row["selector_id"], "scope": row["scope"]}
                    for row in selected_bad_selectors
                ],
                "delivery feature selector must be predeclared or fit inside CV",
            )
        )
    else:
        checks.append(
            passed(
                "leakage_feature_selection_not_outside_cv",
                {
                    "selected_delivery_selectors": [
                        row["selector_id"]
                        for row in feature_selection_rows
                        if row["selected_for_delivery"]
                    ],
                },
                "no selected delivery selector uses validation/test labels or all-row fit",
            )
        )
    rejected_selectors = [
        row for row in feature_selection_rows if row["decision"] == "rejected_known_bad_selector"
    ]
    if rejected_selectors:
        checks.append(
            failed(
                "leakage_rejected_feature_selection_patterns_reported",
                [
                    {"selector_id": row["selector_id"], "scope": row["scope"]}
                    for row in rejected_selectors
                ],
                "known bad feature-selection patterns are visible in the audit",
                severity="warning",
            )
        )

    model_selection_rows = build_model_selection_rows(
        log_rows=model_selection_log,
        leakage_policy_spec=leakage_policy_spec,
    )
    selected_rows = [row for row in model_selection_rows if row["selected_for_delivery"]]
    selected_bad_models = [row for row in model_selection_rows if row["blocking_if_selected"]]
    if len(selected_rows) != 1 or selected_bad_models:
        checks.append(
            failed(
                "leakage_model_selection_uses_validation_not_test",
                {
                    "selected_delivery_count": len(selected_rows),
                    "blocked_selected_candidates": [
                        {
                            "candidate_id": row["candidate_id"],
                            "selection_split": row["selection_split"],
                            "test_metric_visible_to_selector": row[
                                "test_metric_visible_to_selector"
                            ],
                        }
                        for row in selected_bad_models
                    ],
                },
                "exactly one delivery model selected on validation without test metric visibility",
            )
        )
    else:
        checks.append(
            passed(
                "leakage_model_selection_uses_validation_not_test",
                {
                    "selected_model_id": selected_rows[0]["candidate_id"],
                    "selection_split": selected_rows[0]["selection_split"],
                    "test_metric_visible_to_selector": selected_rows[0][
                        "test_metric_visible_to_selector"
                    ],
                },
                "selected delivery model was selected on validation only",
            )
        )
    rejected_test_candidates = [
        row for row in model_selection_rows if row["decision"] == "rejected_test_cherry_pick"
    ]
    if rejected_test_candidates:
        checks.append(
            failed(
                "leakage_test_cherry_pick_candidates_reported",
                [
                    {
                        "candidate_id": row["candidate_id"],
                        "selection_stage": row["selection_stage"],
                    }
                    for row in rejected_test_candidates
                ],
                "test-based cherry-pick candidates are visible and rejected",
                severity="warning",
            )
        )

    checks.append(
        passed(
            "leakage_reports_are_complete",
            {
                "feature_availability_rows": len(feature_availability_rows),
                "forbidden_feature_rows": len(forbidden_feature_rows),
                "preprocessing_scope_rows": len(preprocessing_scope_rows),
                "feature_selection_rows": len(feature_selection_rows),
                "model_selection_rows": len(model_selection_rows),
            },
            "all leakage evidence tables were built",
        )
    )

    blocking_errors = [
        check["id"] for check in checks if check["severity"] == "error" and not check["valid"]
    ]
    warnings = [
        check["id"] for check in checks if check["severity"] == "warning" and not check["valid"]
    ]
    valid = not blocking_errors
    delivery_feature_count = sum(
        1 for row in feature_availability_rows if row["used_in_delivery_model"]
    )
    serialized_spec = {
        "leakage_policy_id": leakage_policy_spec["leakage_policy_id"],
        "problem_id": problem_spec["problem_id"],
        "sklearn_version": sklearn.__version__,
        "source_model_id": leakage_policy_spec["source_model_id"],
        "feature_availability_policy": leakage_policy_spec["feature_availability_policy"],
        "preprocessing_scope_policy": leakage_policy_spec["preprocessing_scope_policy"],
        "feature_selection_policy": leakage_policy_spec["feature_selection_policy"],
        "model_selection_policy": leakage_policy_spec["model_selection_policy"],
        "upstream_calibration_summary": {
            "calibration_policy_id": calibration_report["summary"]["calibration_policy_id"],
            "readiness_status": calibration_report["summary"]["readiness_status"],
            "test_used_for_calibration": calibration_report["summary"][
                "test_used_for_calibration"
            ],
        },
        "test_used_for_model_selection": False,
        "generated_at": GENERATED_AT,
    }
    summary = {
        "leakage_policy_id": leakage_policy_spec["leakage_policy_id"],
        "problem_id": problem_spec["problem_id"],
        "sklearn_version": sklearn.__version__,
        "source_model_id": leakage_policy_spec["source_model_id"],
        "selected_model_id": selected_rows[0]["candidate_id"] if len(selected_rows) == 1 else None,
        "delivery_feature_count": delivery_feature_count,
        "forbidden_candidate_count": len(forbidden_feature_rows),
        "blocked_delivery_feature_count": len(blocked_delivery_features),
        "preprocessing_full_sample_fit_detected": any(
            row["full_sample_fit_detected"] for row in preprocessing_scope_rows
        ),
        "selected_feature_selector_id": next(
            row["selector_id"] for row in feature_selection_rows if row["selected_for_delivery"]
        ),
        "feature_selection_outside_cv_selected_count": len(selected_bad_selectors),
        "test_selected_model_count": sum(
            1
            for row in selected_rows
            if row["selection_split"] == "test" or row["test_metric_visible_to_selector"]
        ),
        "test_used_for_model_selection": False,
        "blocking_errors": blocking_errors,
        "warnings": warnings,
        "readiness_status": "ready_for_error_analysis_lesson"
        if valid
        else "blocked_by_leakage_audit",
    }
    report = {
        "valid": valid,
        "problem_id": problem_spec["problem_id"],
        "summary": summary,
        "feature_availability": feature_availability_rows,
        "forbidden_features": forbidden_feature_rows,
        "preprocessing_scope": preprocessing_scope_rows,
        "feature_selection": feature_selection_rows,
        "model_selection": model_selection_rows,
        "audit": build_audit_rows(checks),
        "serialized_spec": serialized_spec,
        "checks": checks,
    }

    if feature_availability_output_path is not None:
        write_csv(
            feature_availability_output_path,
            feature_availability_rows,
            [
                "feature_name",
                "source_id",
                "source_table",
                "feature_role",
                "timing",
                "risk_type",
                "used_in_delivery_model",
                "source_allowed_by_problem",
                "source_forbidden_by_problem",
                "source_inventory_allowed",
                "timing_allowed_by_policy",
                "timing_forbidden_by_policy",
                "candidate_allowed",
                "blocking_if_used",
                "decision",
                "notes",
            ],
        )
    if forbidden_feature_output_path is not None:
        write_csv(
            forbidden_feature_output_path,
            forbidden_feature_rows,
            [
                "feature_name",
                "source_id",
                "source_table",
                "feature_role",
                "timing",
                "risk_type",
                "used_in_delivery_model",
                "source_allowed_by_problem",
                "source_forbidden_by_problem",
                "source_inventory_allowed",
                "timing_allowed_by_policy",
                "timing_forbidden_by_policy",
                "candidate_allowed",
                "blocking_if_used",
                "decision",
                "notes",
            ],
        )
    if preprocessing_scope_output_path is not None:
        write_csv(
            preprocessing_scope_output_path,
            preprocessing_scope_rows,
            [
                "component_id",
                "component_type",
                "declared_fit_split",
                "transform_or_predict_splits",
                "preprocessing_location",
                "full_sample_fit_detected",
                "validation_used_for_fit",
                "test_used_for_fit",
                "valid",
                "notes",
            ],
        )
    if feature_selection_output_path is not None:
        write_csv(
            feature_selection_output_path,
            feature_selection_rows,
            [
                "selector_id",
                "selector_kind",
                "scope",
                "fit_split",
                "uses_labels",
                "uses_validation_labels",
                "uses_test_labels",
                "inside_pipeline",
                "inside_cv",
                "selected_for_delivery",
                "scope_allowed",
                "scope_forbidden",
                "label_aware_scope_valid",
                "blocking_if_selected",
                "decision",
                "status",
                "notes",
            ],
        )
    if model_selection_output_path is not None:
        write_csv(
            model_selection_output_path,
            model_selection_rows,
            [
                "candidate_id",
                "candidate_family",
                "selection_stage",
                "selection_split",
                "validation_precision_at_budget",
                "test_precision_at_budget",
                "test_metric_visible_to_selector",
                "selected_for_delivery",
                "selection_rank",
                "selection_split_valid",
                "selected_model_valid",
                "test_selection_or_cherry_pick",
                "blocking_if_selected",
                "decision",
                "status",
                "notes",
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
    parser = argparse.ArgumentParser(description="Audit ML data leakage risks")
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
    parser.add_argument("--leakage-policy-spec", type=Path, required=True)
    parser.add_argument("--feature-source-inventory", type=Path, required=True)
    parser.add_argument("--feature-availability", type=Path, required=True)
    parser.add_argument("--feature-selection-log", type=Path, required=True)
    parser.add_argument("--model-selection-log", type=Path, required=True)
    parser.add_argument("--features", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--cv-fold-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--feature-availability-output", type=Path)
    parser.add_argument("--forbidden-feature-output", type=Path)
    parser.add_argument("--preprocessing-scope-output", type=Path)
    parser.add_argument("--feature-selection-output", type=Path)
    parser.add_argument("--model-selection-output", type=Path)
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
            leakage_policy_spec_path=args.leakage_policy_spec,
            feature_source_inventory_path=args.feature_source_inventory,
            feature_availability_path=args.feature_availability,
            feature_selection_log_path=args.feature_selection_log,
            model_selection_log_path=args.model_selection_log,
            features_path=args.features,
            labels_path=args.labels,
            manifest_path=args.manifest,
            cv_fold_manifest_path=args.cv_fold_manifest,
            report_output_path=args.output,
            feature_availability_output_path=args.feature_availability_output,
            forbidden_feature_output_path=args.forbidden_feature_output,
            preprocessing_scope_output_path=args.preprocessing_scope_output,
            feature_selection_output_path=args.feature_selection_output,
            model_selection_output_path=args.model_selection_output,
            audit_output_path=args.audit_output,
            serialized_spec_output_path=args.serialized_spec_output,
        )
    except (
        OSError,
        json.JSONDecodeError,
        ColumnTransformerAuditError,
        ImbalancePolicyError,
        CalibrationPolicyError,
        MLLeakageAuditError,
        KeyError,
        ValueError,
    ) as error:
        report = {
            "valid": False,
            "summary": {
                "blocking_errors": ["ml_leakage_runtime_error"],
                "warnings": [],
                "readiness_status": "runtime_error",
            },
            "checks": [
                failed(
                    "ml_leakage_runtime_error",
                    str(error),
                    "readable inputs and valid leakage audit policy",
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
