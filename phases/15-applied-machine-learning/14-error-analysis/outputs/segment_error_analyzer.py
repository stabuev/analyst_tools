from __future__ import annotations

# ruff: noqa: E402, I001

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import sklearn

LEAKAGE_OUTPUT_ROOT = Path(__file__).resolve().parents[2] / "13-leakage" / "outputs"
CALIBRATION_OUTPUT_ROOT = Path(__file__).resolve().parents[2] / "12-calibration" / "outputs"
IMBALANCE_OUTPUT_ROOT = Path(__file__).resolve().parents[2] / "11-imbalanced-data" / "outputs"
COLUMN_OUTPUT_ROOT = Path(__file__).resolve().parents[2] / "06-column-transformer" / "outputs"
for output_root in (
    LEAKAGE_OUTPUT_ROOT,
    CALIBRATION_OUTPUT_ROOT,
    IMBALANCE_OUTPUT_ROOT,
    COLUMN_OUTPUT_ROOT,
):
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
from ml_leakage_auditor import MLLeakageAuditError, run as run_leakage_audit  # noqa: E402
from probability_calibration_auditor import (  # noqa: E402
    CalibrationPolicyError,
    run as run_calibration_audit,
)

GENERATED_AT = "2026-07-03T10:00:00+03:00"


class SegmentErrorAnalysisError(ValueError):
    """Raised when segment error analysis inputs cannot be parsed."""


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def parse_boolish(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        if value in (0, 1):
            return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1"}:
            return True
        if normalized in {"false", "0"}:
            return False
    raise SegmentErrorAnalysisError(f"expected boolean-like value, got {value!r}")


def safe_rate(numerator: int | float, denominator: int | float) -> float | str:
    if denominator == 0:
        return ""
    return rounded(float(numerator) / float(denominator))


def validate_error_analysis_policy_spec(
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
    error_analysis_policy_spec: dict[str, Any],
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
        "leakage_policy_id": leakage_policy_spec.get("leakage_policy_id"),
    }
    for field, expected in expected_identity.items():
        if error_analysis_policy_spec.get(field) != expected:
            errors.append(
                {
                    "field": field,
                    "observed": error_analysis_policy_spec.get(field),
                    "expected": expected,
                }
            )

    expected_model = leakage_policy_spec.get("source_model_id")
    if error_analysis_policy_spec.get("source_model_id") != expected_model:
        errors.append(
            {
                "field": "source_model_id",
                "observed": error_analysis_policy_spec.get("source_model_id"),
                "expected": expected_model,
            }
        )

    expected_scalars = {
        "analysis_split": "test",
        "reference_split": "validation",
        "prediction_source": "calibrated",
        "score_column": "calibrated_score",
        "decision_column": "selected_at_budget_calibrated",
        "label_column": "actual_label",
        "positive_class": True,
        "negative_class": False,
    }
    for field, expected in expected_scalars.items():
        if error_analysis_policy_spec.get(field) != expected:
            errors.append(
                {
                    "field": field,
                    "observed": error_analysis_policy_spec.get(field),
                    "expected": expected,
                }
            )

    slice_policy = error_analysis_policy_spec.get("slice_policy")
    if not isinstance(slice_policy, dict):
        errors.append({"field": "slice_policy", "reason": "object required"})
    else:
        required = set(slice_policy.get("required_dimensions") or [])
        expected_required = set(problem_spec.get("segment_policy", {}).get("required_slices") or [])
        if not expected_required.issubset(required):
            errors.append(
                {
                    "field": "slice_policy.required_dimensions",
                    "observed": sorted(required),
                    "expected": sorted(expected_required),
                }
            )
        if set(slice_policy.get("business_dimensions") or []) != {
            "plan_id",
            "acquisition_channel",
        }:
            errors.append(
                {
                    "field": "slice_policy.business_dimensions",
                    "observed": slice_policy.get("business_dimensions"),
                    "expected": ["plan_id", "acquisition_channel"],
                }
            )
        if not {"business_cohort", "score_band"}.issubset(
            set(slice_policy.get("derived_dimensions") or [])
        ):
            errors.append(
                {
                    "field": "slice_policy.derived_dimensions",
                    "observed": slice_policy.get("derived_dimensions"),
                    "expected": ["business_cohort", "score_band"],
                }
            )
        for field in ("forbid_training_split_slice_claims", "forbid_dropping_small_slices"):
            if slice_policy.get(field) is not True:
                errors.append(
                    {
                        "field": f"slice_policy.{field}",
                        "observed": slice_policy.get(field),
                        "expected": True,
                    }
                )

    score_band_policy = error_analysis_policy_spec.get("score_band_policy")
    if not isinstance(score_band_policy, dict):
        errors.append({"field": "score_band_policy", "reason": "object required"})
    else:
        if score_band_policy.get("source") != "calibrated_score":
            errors.append(
                {
                    "field": "score_band_policy.source",
                    "observed": score_band_policy.get("source"),
                    "expected": "calibrated_score",
                }
            )
        bands = score_band_policy.get("bands")
        if not isinstance(bands, list) or len(bands) < 3:
            errors.append({"field": "score_band_policy.bands", "reason": "at least 3 bands"})
        else:
            previous_upper = 0.0
            for index, band in enumerate(bands):
                if not {"band_id", "lower", "upper"}.issubset(band):
                    errors.append({"field": f"score_band_policy.bands[{index}]", "reason": "bad band"})
                    continue
                if float(band["lower"]) != previous_upper:
                    errors.append(
                        {
                            "field": f"score_band_policy.bands[{index}].lower",
                            "observed": band["lower"],
                            "expected": previous_upper,
                        }
                    )
                if float(band["upper"]) <= float(band["lower"]):
                    errors.append(
                        {
                            "field": f"score_band_policy.bands[{index}].upper",
                            "reason": "must be greater than lower",
                        }
                    )
                previous_upper = float(band["upper"])

    metric_policy = error_analysis_policy_spec.get("metric_policy")
    if not isinstance(metric_policy, dict):
        errors.append({"field": "metric_policy", "reason": "object required"})
    else:
        if metric_policy.get("primary_decision_rule") != "rank_top_k_within_scoring_batch":
            errors.append(
                {
                    "field": "metric_policy.primary_decision_rule",
                    "observed": metric_policy.get("primary_decision_rule"),
                    "expected": "rank_top_k_within_scoring_batch",
                }
            )
        required_metrics = {
            "precision",
            "recall",
            "false_positive_rate",
            "false_negative_rate",
            "error_rate",
            "selection_rate",
            "brier_score",
        }
        if not required_metrics.issubset(set(metric_policy.get("metrics") or [])):
            errors.append(
                {
                    "field": "metric_policy.metrics",
                    "observed": metric_policy.get("metrics"),
                    "expected": sorted(required_metrics),
                }
            )
        if set(metric_policy.get("confusion_terms") or []) != {"tp", "fp", "tn", "fn"}:
            errors.append(
                {
                    "field": "metric_policy.confusion_terms",
                    "observed": metric_policy.get("confusion_terms"),
                    "expected": ["tp", "fp", "tn", "fn"],
                }
            )

    small_n_policy = error_analysis_policy_spec.get("small_n_policy")
    if not isinstance(small_n_policy, dict):
        errors.append({"field": "small_n_policy", "reason": "object required"})
    else:
        if int(small_n_policy.get("min_rows_per_slice", 0)) < 2:
            errors.append(
                {
                    "field": "small_n_policy.min_rows_per_slice",
                    "observed": small_n_policy.get("min_rows_per_slice"),
                    "expected": ">= 2",
                }
            )
        if small_n_policy.get("action") != "warn_not_hide":
            errors.append(
                {
                    "field": "small_n_policy.action",
                    "observed": small_n_policy.get("action"),
                    "expected": "warn_not_hide",
                }
            )
        if small_n_policy.get("forbid_dropping_small_slices") is not True:
            errors.append(
                {
                    "field": "small_n_policy.forbid_dropping_small_slices",
                    "observed": small_n_policy.get("forbid_dropping_small_slices"),
                    "expected": True,
                }
            )

    hidden_policy = error_analysis_policy_spec.get("hidden_failure_policy")
    if not isinstance(hidden_policy, dict):
        errors.append({"field": "hidden_failure_policy", "reason": "object required"})
    else:
        if int(hidden_policy.get("min_rows_for_candidate", 0)) < 2:
            errors.append(
                {
                    "field": "hidden_failure_policy.min_rows_for_candidate",
                    "observed": hidden_policy.get("min_rows_for_candidate"),
                    "expected": ">= 2",
                }
            )
        for field in ("require_hidden_failure_table", "aggregate_claim_requires_no_hidden_failure"):
            if hidden_policy.get(field) is not True:
                errors.append(
                    {
                        "field": f"hidden_failure_policy.{field}",
                        "observed": hidden_policy.get(field),
                        "expected": True,
                    }
                )

    audit_policy = error_analysis_policy_spec.get("audit_policy")
    if not isinstance(audit_policy, dict):
        errors.append({"field": "audit_policy", "reason": "object required"})
    else:
        for field in (
            "require_leakage_handoff",
            "require_calibrated_predictions",
            "require_confusion_rows",
            "require_slice_metrics",
            "require_small_n_warnings",
            "require_hidden_failure_table",
            "forbid_test_selection",
            "forbid_hiding_small_slices",
            "forbid_aggregate_only_readiness_claim",
        ):
            if audit_policy.get(field) is not True:
                errors.append(
                    {
                        "field": f"audit_policy.{field}",
                        "observed": audit_policy.get(field),
                        "expected": True,
                    }
                )

    output = error_analysis_policy_spec.get("output")
    if not isinstance(output, dict):
        errors.append({"field": "output", "reason": "object required"})
    else:
        for field in (
            "confusion_row_file",
            "slice_metric_file",
            "small_n_warning_file",
            "hidden_failure_file",
            "error_example_file",
            "audit_file",
            "report_file",
            "serialized_spec_file",
        ):
            if not output.get(field):
                errors.append({"field": f"output.{field}", "reason": "required"})

    if errors:
        return failed(
            "error_analysis_policy_spec_declares_slice_contract",
            len(errors),
            "error analysis policy with test-only split, required slices, small-n and hidden-failure gates",
            errors,
        )
    return passed(
        "error_analysis_policy_spec_declares_slice_contract",
        {
            "error_analysis_policy_id": error_analysis_policy_spec[
                "error_analysis_policy_id"
            ],
            "analysis_split": error_analysis_policy_spec["analysis_split"],
            "source_model_id": error_analysis_policy_spec["source_model_id"],
        },
        "error analysis contract is explicit",
    )


def score_band(score: float, bands: list[dict[str, Any]]) -> str:
    for index, band in enumerate(bands):
        lower = float(band["lower"])
        upper = float(band["upper"])
        is_last = index == len(bands) - 1
        if score >= lower and (score < upper or (is_last and score <= upper)):
            return str(band["band_id"])
    raise SegmentErrorAnalysisError(f"score {score} is outside configured score bands")


def build_confusion_rows(
    *,
    predictions: list[dict[str, Any]],
    snapshots: list[dict[str, str]],
    features: list[dict[str, str]],
    manifest: list[dict[str, str]],
    error_analysis_policy_spec: dict[str, Any],
) -> list[dict[str, Any]]:
    snapshot_by_id = {row["snapshot_id"]: row for row in snapshots}
    feature_by_id = {row["snapshot_id"]: row for row in features}
    manifest_by_id = {row["snapshot_id"]: row for row in manifest}
    analysis_split = error_analysis_policy_spec["analysis_split"]
    decision_column = error_analysis_policy_spec["decision_column"]
    score_column = error_analysis_policy_spec["score_column"]
    label_column = error_analysis_policy_spec["label_column"]
    bands = error_analysis_policy_spec["score_band_policy"]["bands"]

    rows: list[dict[str, Any]] = []
    for prediction in predictions:
        if prediction["split"] != analysis_split:
            continue
        snapshot_id = prediction["snapshot_id"]
        snapshot = snapshot_by_id.get(snapshot_id)
        feature_row = feature_by_id.get(snapshot_id)
        manifest_row = manifest_by_id.get(snapshot_id)
        if snapshot is None or feature_row is None or manifest_row is None:
            raise SegmentErrorAnalysisError(
                f"prediction {snapshot_id} has no snapshot, feature or manifest metadata"
            )
        score = float(prediction[score_column])
        actual = parse_boolish(prediction[label_column])
        selected = parse_boolish(prediction[decision_column])
        if selected and actual:
            confusion_label = "tp"
        elif selected and not actual:
            confusion_label = "fp"
        elif not selected and actual:
            confusion_label = "fn"
        else:
            confusion_label = "tn"
        rows.append(
            {
                "split": prediction["split"],
                "snapshot_id": snapshot_id,
                "user_id": manifest_row["user_id"],
                "prediction_time": manifest_row["prediction_time"],
                "segment_id": snapshot["segment_id"],
                "platform": snapshot["platform"],
                "country": snapshot["country"],
                "plan_id": snapshot["plan_id"],
                "acquisition_channel": feature_row.get("acquisition_channel") or "__missing__",
                "business_cohort": f'{snapshot["plan_id"]}:{snapshot["country"]}',
                "score_band": score_band(score, bands),
                "model_id": prediction["model_id"],
                "calibrated_score": rounded(score),
                "uncalibrated_score": rounded(float(prediction["uncalibrated_score"])),
                "actual_label": int(actual),
                "selected_for_action": selected,
                "confusion_label": confusion_label,
                "is_error": confusion_label in {"fp", "fn"},
                "false_positive": confusion_label == "fp",
                "false_negative": confusion_label == "fn",
            }
        )
    return rows


def build_slice_metric_rows(
    *,
    confusion_rows: list[dict[str, Any]],
    error_analysis_policy_spec: dict[str, Any],
) -> list[dict[str, Any]]:
    dimensions = [
        "overall",
        *error_analysis_policy_spec["slice_policy"]["required_dimensions"],
        *error_analysis_policy_spec["slice_policy"]["business_dimensions"],
        *error_analysis_policy_spec["slice_policy"]["derived_dimensions"],
    ]
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in confusion_rows:
        grouped[("overall", "all")].append(row)
        for dimension in dimensions:
            if dimension == "overall":
                continue
            grouped[(dimension, str(row[dimension]))].append(row)

    small_policy = error_analysis_policy_spec["small_n_policy"]
    hidden_policy = error_analysis_policy_spec["hidden_failure_policy"]
    min_rows = int(small_policy["min_rows_per_slice"])
    min_positive_count = int(small_policy["min_positive_count_for_recall_claim"])
    min_hidden_rows = int(hidden_policy["min_rows_for_candidate"])
    max_error_gap = float(hidden_policy["warn_if_error_rate_above_overall_by"])
    max_precision_gap = float(hidden_policy["warn_if_precision_below_overall_by"])

    rows: list[dict[str, Any]] = []
    for (dimension, value), members in sorted(
        grouped.items(), key=lambda item: (dimensions.index(item[0][0]), item[0][1])
    ):
        row_count = len(members)
        tp = sum(1 for row in members if row["confusion_label"] == "tp")
        fp = sum(1 for row in members if row["confusion_label"] == "fp")
        tn = sum(1 for row in members if row["confusion_label"] == "tn")
        fn = sum(1 for row in members if row["confusion_label"] == "fn")
        positive_count = tp + fn
        negative_count = tn + fp
        action_count = tp + fp
        precision = safe_rate(tp, action_count)
        recall = safe_rate(tp, positive_count)
        fpr = safe_rate(fp, negative_count)
        fnr = safe_rate(fn, positive_count)
        error_rate = safe_rate(fp + fn, row_count)
        selection_rate = safe_rate(action_count, row_count)
        brier_score = rounded(
            sum((float(row["calibrated_score"]) - float(row["actual_label"])) ** 2 for row in members)
            / row_count
        )
        rows.append(
            {
                "dimension": dimension,
                "slice_value": value,
                "row_count": row_count,
                "positive_count": positive_count,
                "negative_count": negative_count,
                "action_count": action_count,
                "tp": tp,
                "fp": fp,
                "tn": tn,
                "fn": fn,
                "precision": precision,
                "recall": recall,
                "false_positive_rate": fpr,
                "false_negative_rate": fnr,
                "error_rate": error_rate,
                "selection_rate": selection_rate,
                "brier_score": brier_score,
                "selected_ids": ",".join(row["snapshot_id"] for row in members if row["selected_for_action"]),
                "false_positive_ids": ",".join(row["snapshot_id"] for row in members if row["false_positive"]),
                "false_negative_ids": ",".join(row["snapshot_id"] for row in members if row["false_negative"]),
                "small_n_warning": dimension != "overall" and row_count < min_rows,
                "recall_claim_allowed": positive_count >= min_positive_count
                and row_count >= min_rows,
                "hidden_failure_candidate": False,
                "hidden_failure_reasons": "",
                "interpretation": "overall_reference"
                if dimension == "overall"
                else "diagnostic_only_small_n"
                if row_count < min_rows
                else "slice_diagnostic",
            }
        )

    overall = next(row for row in rows if row["dimension"] == "overall")
    overall_error_rate = float(overall["error_rate"])
    overall_precision = float(overall["precision"]) if overall["precision"] != "" else None
    for row in rows:
        if row["dimension"] == "overall" or row["row_count"] < min_hidden_rows:
            continue
        reasons: list[str] = []
        if row["error_rate"] != "" and float(row["error_rate"]) - overall_error_rate >= max_error_gap:
            reasons.append("error_rate_above_overall")
        if (
            row["precision"] != ""
            and overall_precision is not None
            and overall_precision - float(row["precision"]) >= max_precision_gap
        ):
            reasons.append("precision_below_overall")
        if reasons:
            row["hidden_failure_candidate"] = True
            row["hidden_failure_reasons"] = ",".join(reasons)
            if not row["small_n_warning"]:
                row["interpretation"] = "hidden_failure_candidate"
    return rows


def build_audit_rows(checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "check_id": check["id"],
            "severity": check["severity"],
            "valid": check["valid"],
            "observed": json.dumps(json_ready(check["observed"]), ensure_ascii=False),
            "expected": json.dumps(json_ready(check["expected"]), ensure_ascii=False),
        }
        for check in checks
    ]


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
    error_analysis_policy_spec_path: Path,
    feature_source_inventory_path: Path,
    feature_availability_path: Path,
    feature_selection_log_path: Path,
    model_selection_log_path: Path,
    features_path: Path,
    labels_path: Path,
    manifest_path: Path,
    cv_fold_manifest_path: Path,
    snapshots_path: Path,
    report_output_path: Path | None = None,
    confusion_row_output_path: Path | None = None,
    slice_metric_output_path: Path | None = None,
    small_n_warning_output_path: Path | None = None,
    hidden_failure_output_path: Path | None = None,
    error_example_output_path: Path | None = None,
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
    error_analysis_policy_spec = read_json(error_analysis_policy_spec_path)
    snapshots, _snapshot_columns = read_csv(snapshots_path)
    features, _feature_columns = read_csv(features_path)
    manifest, _manifest_columns = read_csv(manifest_path)

    checks: list[dict[str, Any]] = [
        validate_error_analysis_policy_spec(
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
            error_analysis_policy_spec=error_analysis_policy_spec,
        )
    ]

    leakage_report = run_leakage_audit(
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
        leakage_policy_spec_path=leakage_policy_spec_path,
        feature_source_inventory_path=feature_source_inventory_path,
        feature_availability_path=feature_availability_path,
        feature_selection_log_path=feature_selection_log_path,
        model_selection_log_path=model_selection_log_path,
        features_path=features_path,
        labels_path=labels_path,
        manifest_path=manifest_path,
        cv_fold_manifest_path=cv_fold_manifest_path,
    )
    if leakage_report.get("valid") and (
        leakage_report.get("summary", {}).get("readiness_status")
        == "ready_for_error_analysis_lesson"
    ):
        checks.append(
            passed(
                "upstream_leakage_handoff_is_valid",
                {
                    "leakage_policy_id": leakage_policy_spec.get("leakage_policy_id"),
                    "source_model_id": leakage_report["summary"].get("source_model_id"),
                    "readiness_status": leakage_report["summary"].get("readiness_status"),
                },
                "leakage handoff is valid and ready for segment error analysis",
            )
        )
    else:
        checks.append(
            failed(
                "upstream_leakage_handoff_is_valid",
                leakage_report.get("summary", {}).get("blocking_errors", []),
                "valid leakage report with ready_for_error_analysis_lesson",
                leakage_report.get("checks", []),
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
                "error_analysis_policy_id": error_analysis_policy_spec.get(
                    "error_analysis_policy_id"
                ),
                "blocking_errors": spec_blocking_errors,
                "warnings": [],
                "readiness_status": "blocked_before_error_analysis",
            },
            "checks": checks,
        }
        if report_output_path is not None:
            write_json(report_output_path, json_ready(report))
        return report

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
    confusion_rows = build_confusion_rows(
        predictions=calibration_report["predictions"],
        snapshots=snapshots,
        features=features,
        manifest=manifest,
        error_analysis_policy_spec=error_analysis_policy_spec,
    )
    analysis_split_ids = {
        row["snapshot_id"]
        for row in manifest
        if row["split"] == error_analysis_policy_spec["analysis_split"]
    }
    observed_ids = {row["snapshot_id"] for row in confusion_rows}
    if analysis_split_ids != observed_ids:
        checks.append(
            failed(
                "error_analysis_confusion_rows_cover_analysis_split",
                {
                    "missing_ids": sorted(analysis_split_ids - observed_ids),
                    "extra_ids": sorted(observed_ids - analysis_split_ids),
                },
                "one confusion row per analysis-split prediction",
            )
        )
    else:
        checks.append(
            passed(
                "error_analysis_confusion_rows_cover_analysis_split",
                {"analysis_split": error_analysis_policy_spec["analysis_split"], "row_count": len(confusion_rows)},
                "confusion rows cover the test split exactly once",
            )
        )
    if {row["split"] for row in confusion_rows} == {error_analysis_policy_spec["analysis_split"]}:
        checks.append(
            passed(
                "error_analysis_uses_test_split_only",
                sorted({row["split"] for row in confusion_rows}),
                "error analysis uses final holdout predictions only",
            )
        )
    else:
        checks.append(
            failed(
                "error_analysis_uses_test_split_only",
                sorted({row["split"] for row in confusion_rows}),
                [error_analysis_policy_spec["analysis_split"]],
            )
        )

    slice_metric_rows = build_slice_metric_rows(
        confusion_rows=confusion_rows,
        error_analysis_policy_spec=error_analysis_policy_spec,
    )
    expected_dimensions = {
        "overall",
        *error_analysis_policy_spec["slice_policy"]["required_dimensions"],
        *error_analysis_policy_spec["slice_policy"]["business_dimensions"],
        *error_analysis_policy_spec["slice_policy"]["derived_dimensions"],
    }
    observed_dimensions = {row["dimension"] for row in slice_metric_rows}
    if expected_dimensions.issubset(observed_dimensions):
        checks.append(
            passed(
                "error_analysis_slice_metrics_are_complete",
                {"dimensions": sorted(observed_dimensions), "row_count": len(slice_metric_rows)},
                "slice metrics cover required segment, business and score-band dimensions",
            )
        )
    else:
        checks.append(
            failed(
                "error_analysis_slice_metrics_are_complete",
                sorted(observed_dimensions),
                sorted(expected_dimensions),
            )
        )

    small_n_rows = [row for row in slice_metric_rows if row["small_n_warning"]]
    if small_n_rows:
        checks.append(
            failed(
                "error_analysis_small_n_slices_visible",
                {
                    "small_n_slice_count": len(small_n_rows),
                    "min_rows_per_slice": error_analysis_policy_spec["small_n_policy"][
                        "min_rows_per_slice"
                    ],
                },
                "small slices should remain visible and be labeled diagnostic-only",
                severity="warning",
            )
        )
    else:
        checks.append(
            passed(
                "error_analysis_small_n_slices_visible",
                {"small_n_slice_count": 0},
                "no small slices detected",
            )
        )

    hidden_failure_rows = [
        row for row in slice_metric_rows if row["hidden_failure_candidate"]
    ]
    if hidden_failure_rows:
        checks.append(
            failed(
                "error_analysis_hidden_failure_slices_visible",
                [
                    {
                        "dimension": row["dimension"],
                        "slice_value": row["slice_value"],
                        "reasons": row["hidden_failure_reasons"],
                    }
                    for row in hidden_failure_rows
                ],
                "hidden aggregate failures should be reported, not collapsed into overall metrics",
                severity="warning",
            )
        )
        checks.append(
            failed(
                "aggregate_metric_not_segment_readiness_claim",
                {
                    "overall_error_rate": next(
                        row["error_rate"] for row in slice_metric_rows if row["dimension"] == "overall"
                    ),
                    "hidden_failure_slice_count": len(hidden_failure_rows),
                },
                "overall metric cannot be treated as segment readiness when hidden failures exist",
                severity="warning",
            )
        )
    else:
        checks.append(
            passed(
                "error_analysis_hidden_failure_slices_visible",
                {"hidden_failure_slice_count": 0},
                "no hidden failure slices detected",
            )
        )

    error_examples = [row for row in confusion_rows if row["is_error"]]
    checks.append(
        passed(
            "error_analysis_reports_are_complete",
            {
                "confusion_rows": len(confusion_rows),
                "slice_metric_rows": len(slice_metric_rows),
                "small_n_warning_rows": len(small_n_rows),
                "hidden_failure_rows": len(hidden_failure_rows),
                "error_examples": len(error_examples),
            },
            "all segment error analysis evidence tables were built",
        )
    )

    blocking_errors = [
        check["id"] for check in checks if check["severity"] == "error" and not check["valid"]
    ]
    warnings = [
        check["id"] for check in checks if check["severity"] == "warning" and not check["valid"]
    ]
    valid = not blocking_errors
    overall = next(row for row in slice_metric_rows if row["dimension"] == "overall")
    serialized_spec = {
        "error_analysis_policy_id": error_analysis_policy_spec["error_analysis_policy_id"],
        "problem_id": problem_spec["problem_id"],
        "sklearn_version": sklearn.__version__,
        "source_model_id": error_analysis_policy_spec["source_model_id"],
        "analysis_split": error_analysis_policy_spec["analysis_split"],
        "prediction_source": error_analysis_policy_spec["prediction_source"],
        "slice_policy": error_analysis_policy_spec["slice_policy"],
        "score_band_policy": error_analysis_policy_spec["score_band_policy"],
        "small_n_policy": error_analysis_policy_spec["small_n_policy"],
        "hidden_failure_policy": error_analysis_policy_spec["hidden_failure_policy"],
        "upstream_leakage_summary": {
            "leakage_policy_id": leakage_report["summary"]["leakage_policy_id"],
            "readiness_status": leakage_report["summary"]["readiness_status"],
            "test_used_for_model_selection": leakage_report["summary"][
                "test_used_for_model_selection"
            ],
        },
        "generated_at": GENERATED_AT,
    }
    summary = {
        "error_analysis_policy_id": error_analysis_policy_spec["error_analysis_policy_id"],
        "problem_id": problem_spec["problem_id"],
        "sklearn_version": sklearn.__version__,
        "source_model_id": error_analysis_policy_spec["source_model_id"],
        "analysis_split": error_analysis_policy_spec["analysis_split"],
        "prediction_source": error_analysis_policy_spec["prediction_source"],
        "row_count": overall["row_count"],
        "positive_count": overall["positive_count"],
        "action_count": overall["action_count"],
        "overall_precision": overall["precision"],
        "overall_recall": overall["recall"],
        "overall_error_rate": overall["error_rate"],
        "false_positive_count": overall["fp"],
        "false_negative_count": overall["fn"],
        "slice_metric_row_count": len(slice_metric_rows),
        "small_n_slice_count": len(small_n_rows),
        "hidden_failure_slice_count": len(hidden_failure_rows),
        "error_example_count": len(error_examples),
        "blocking_errors": blocking_errors,
        "warnings": warnings,
        "readiness_status": "ready_for_model_card_lesson"
        if valid
        else "blocked_by_error_analysis",
    }
    report = {
        "valid": valid,
        "problem_id": problem_spec["problem_id"],
        "summary": summary,
        "confusion_rows": confusion_rows,
        "slice_metrics": slice_metric_rows,
        "small_n_warnings": small_n_rows,
        "hidden_failure_slices": hidden_failure_rows,
        "error_examples": error_examples,
        "audit": build_audit_rows(checks),
        "serialized_spec": serialized_spec,
        "checks": checks,
    }

    confusion_fields = [
        "split",
        "snapshot_id",
        "user_id",
        "prediction_time",
        "segment_id",
        "platform",
        "country",
        "plan_id",
        "acquisition_channel",
        "business_cohort",
        "score_band",
        "model_id",
        "calibrated_score",
        "uncalibrated_score",
        "actual_label",
        "selected_for_action",
        "confusion_label",
        "is_error",
        "false_positive",
        "false_negative",
    ]
    slice_fields = [
        "dimension",
        "slice_value",
        "row_count",
        "positive_count",
        "negative_count",
        "action_count",
        "tp",
        "fp",
        "tn",
        "fn",
        "precision",
        "recall",
        "false_positive_rate",
        "false_negative_rate",
        "error_rate",
        "selection_rate",
        "brier_score",
        "selected_ids",
        "false_positive_ids",
        "false_negative_ids",
        "small_n_warning",
        "recall_claim_allowed",
        "hidden_failure_candidate",
        "hidden_failure_reasons",
        "interpretation",
    ]
    if confusion_row_output_path is not None:
        write_csv(confusion_row_output_path, confusion_rows, confusion_fields)
    if slice_metric_output_path is not None:
        write_csv(slice_metric_output_path, slice_metric_rows, slice_fields)
    if small_n_warning_output_path is not None:
        write_csv(small_n_warning_output_path, small_n_rows, slice_fields)
    if hidden_failure_output_path is not None:
        write_csv(hidden_failure_output_path, hidden_failure_rows, slice_fields)
    if error_example_output_path is not None:
        write_csv(error_example_output_path, error_examples, confusion_fields)
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
    parser = argparse.ArgumentParser(description="Analyze ML errors by segment")
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
    parser.add_argument("--error-analysis-policy-spec", type=Path, required=True)
    parser.add_argument("--feature-source-inventory", type=Path, required=True)
    parser.add_argument("--feature-availability", type=Path, required=True)
    parser.add_argument("--feature-selection-log", type=Path, required=True)
    parser.add_argument("--model-selection-log", type=Path, required=True)
    parser.add_argument("--features", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--cv-fold-manifest", type=Path, required=True)
    parser.add_argument("--snapshots", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--confusion-row-output", type=Path)
    parser.add_argument("--slice-metric-output", type=Path)
    parser.add_argument("--small-n-warning-output", type=Path)
    parser.add_argument("--hidden-failure-output", type=Path)
    parser.add_argument("--error-example-output", type=Path)
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
            error_analysis_policy_spec_path=args.error_analysis_policy_spec,
            feature_source_inventory_path=args.feature_source_inventory,
            feature_availability_path=args.feature_availability,
            feature_selection_log_path=args.feature_selection_log,
            model_selection_log_path=args.model_selection_log,
            features_path=args.features,
            labels_path=args.labels,
            manifest_path=args.manifest,
            cv_fold_manifest_path=args.cv_fold_manifest,
            snapshots_path=args.snapshots,
            report_output_path=args.output,
            confusion_row_output_path=args.confusion_row_output,
            slice_metric_output_path=args.slice_metric_output,
            small_n_warning_output_path=args.small_n_warning_output,
            hidden_failure_output_path=args.hidden_failure_output,
            error_example_output_path=args.error_example_output,
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
        SegmentErrorAnalysisError,
        KeyError,
        ValueError,
    ) as error:
        report = {
            "valid": False,
            "summary": {
                "blocking_errors": ["segment_error_analysis_runtime_error"],
                "warnings": [],
                "readiness_status": "runtime_error",
            },
            "checks": [
                failed(
                    "segment_error_analysis_runtime_error",
                    str(error),
                    "readable inputs and valid segment error analysis policy",
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
