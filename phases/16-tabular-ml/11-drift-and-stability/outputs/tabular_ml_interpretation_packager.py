from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
from pathlib import Path
from typing import Any


LESSON_ROOT = Path(__file__).resolve().parents[1]
PHASE_ROOT = LESSON_ROOT.parent
REPO_ROOT = LESSON_ROOT.parents[2]
DATA_ROOT = PHASE_ROOT / "data" / "tiny"
PHASE15_ROOT = REPO_ROOT / "phases" / "15-applied-machine-learning"
PHASE15_OUTPUT_ROOT = PHASE15_ROOT / "15-model-card" / "outputs"
PHASE15_DATA_ROOT = PHASE15_ROOT / "data" / "tiny"

DEFAULT_SPEC_PATH = DATA_ROOT / "tabular_ml_package_spec.json"
DEFAULT_INPUT_PATHS = {
    "baseline_package_manifest": PHASE15_OUTPUT_ROOT / "ml_baseline_package_manifest.json",
    "baseline_package": PHASE15_OUTPUT_ROOT / "ml_baseline_package.json",
    "baseline_decision_report": PHASE15_OUTPUT_ROOT / "decision_report.md",
    "problem_spec": PHASE15_DATA_ROOT / "problem_spec.json",
    "catboost_model_spec": DATA_ROOT / "catboost_model_spec.json",
    "categorical_feature_contract": DATA_ROOT / "categorical_feature_contract.json",
    "mlflow_tracking_policy": DATA_ROOT / "mlflow_tracking_policy_spec.json",
}
DEFAULT_REPORT_PATHS = {
    "baseline_package_report": PHASE15_OUTPUT_ROOT / "ml_baseline_package_report.json",
    "catboost_report": PHASE_ROOT / "01-catboost" / "outputs" / "catboost_report.json",
    "categorical_report": PHASE_ROOT / "02-categorical-features" / "outputs" / "categorical_feature_report.json",
    "early_stopping_report": PHASE_ROOT / "03-early-stopping" / "outputs" / "early_stopping_report.json",
    "built_in_importance_report": PHASE_ROOT / "04-feature-importance" / "outputs" / "built_in_importance_report.json",
    "permutation_importance_report": PHASE_ROOT / "05-permutation-importance" / "outputs" / "permutation_importance_report.json",
    "shap_report": PHASE_ROOT / "06-shap" / "outputs" / "shap_explanation_report.json",
    "segment_report": PHASE_ROOT / "07-segment-analysis" / "outputs" / "strong_model_segment_report.json",
    "cost_report": PHASE_ROOT / "08-cost-sensitive-decisions" / "outputs" / "cost_sensitive_decision_report.json",
    "optuna_report": PHASE_ROOT / "09-optuna" / "outputs" / "optuna_tuning_report.json",
    "mlflow_report": PHASE_ROOT / "10-mlflow" / "outputs" / "mlflow_experiment_report.json",
}
DEFAULT_TABLE_PATHS = {
    "catboost_comparison": PHASE_ROOT / "01-catboost" / "outputs" / "catboost_comparison.csv",
    "catboost_training_trace": PHASE_ROOT / "01-catboost" / "outputs" / "catboost_training_trace.csv",
    "categorical_inventory": PHASE_ROOT / "02-categorical-features" / "outputs" / "categorical_inventory.csv",
    "categorical_leakage_audit": PHASE_ROOT / "02-categorical-features" / "outputs" / "categorical_leakage_audit.csv",
    "categorical_unknowns": PHASE_ROOT / "02-categorical-features" / "outputs" / "categorical_unknowns.csv",
    "built_in_importance": PHASE_ROOT / "04-feature-importance" / "outputs" / "built_in_importance.csv",
    "permutation_importance": PHASE_ROOT / "05-permutation-importance" / "outputs" / "permutation_importance.csv",
    "shap_global_summary": PHASE_ROOT / "06-shap" / "outputs" / "shap_global_summary.csv",
    "explanation_disagreement": PHASE_ROOT / "06-shap" / "outputs" / "explanation_disagreement.csv",
    "strong_model_segment_deltas": PHASE_ROOT / "07-segment-analysis" / "outputs" / "strong_model_segment_deltas.csv",
    "strong_model_hidden_failure_slices": PHASE_ROOT / "07-segment-analysis" / "outputs" / "strong_model_hidden_failure_slices.csv",
    "decision_gate": PHASE_ROOT / "08-cost-sensitive-decisions" / "outputs" / "decision_gate.csv",
    "threshold_comparison": PHASE_ROOT / "08-cost-sensitive-decisions" / "outputs" / "threshold_comparison.csv",
    "optuna_trial_ledger": PHASE_ROOT / "09-optuna" / "outputs" / "optuna_trial_ledger.csv",
    "optuna_best_trial_trace": PHASE_ROOT / "09-optuna" / "outputs" / "optuna_best_trial_trace.csv",
    "optuna_tuned_predictions": PHASE_ROOT / "09-optuna" / "outputs" / "optuna_tuned_predictions.csv",
    "mlflow_run_table": PHASE_ROOT / "10-mlflow" / "outputs" / "mlflow_run_table.csv",
    "mlflow_artifact_inventory": PHASE_ROOT / "10-mlflow" / "outputs" / "mlflow_artifact_inventory.csv",
}
EXPECTED_OUTPUT_FIELDS = {
    "package_file",
    "report_file",
    "evidence_matrix_file",
    "score_drift_file",
    "feature_drift_file",
    "importance_stability_file",
    "segment_stability_file",
    "stability_report_file",
    "interpretation_report_file",
    "decision_report_file",
    "manifest_file",
}
REQUIRED_SPEC_FIELDS = {
    "package_id",
    "problem_id",
    "source_baseline_package_id",
    "source_mlflow_tracking_audit_id",
    "candidate_model_id",
    "source_catboost_model_id",
    "baseline_model_id",
    "required_upstream_reports",
    "required_evidence_files",
    "drift_policy",
    "stability_policy",
    "decision_policy",
    "output",
}
GENERATED_AT = "2026-07-06T14:00:00+03:00"


class TabularMLPackageError(ValueError):
    """Raised when the tabular ML interpretation package cannot be built."""


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TabularMLPackageError(f"{path.name} must contain a JSON object")
    return payload


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open(encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        return list(reader), list(reader.fieldnames or [])


def stringify(value: Any) -> str:
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, float):
        return str(round_float(value))
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    if value is None:
        return ""
    return str(value)


def json_text(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def csv_text(rows: list[dict[str, Any]], fieldnames: list[str]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({field: stringify(row.get(field, "")) for field in fieldnames})
    return buffer.getvalue()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json_text(payload), encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(csv_text(rows, fieldnames), encoding="utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_path(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def path_label(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def round_float(value: float | None, digits: int = 6) -> float | None:
    if value is None:
        return None
    if math.isnan(value):
        return None
    return round(float(value), digits)


def as_float(value: Any, default: float = 0.0) -> float:
    if value in ("", None):
        return default
    return float(value)


def as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).lower() == "true"


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def stddev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    avg = mean(values)
    return math.sqrt(sum((value - avg) ** 2 for value in values) / (len(values) - 1))


def passed(check_id: str, observed: Any = None, expected: Any = None, sample: list[Any] | None = None) -> dict[str, Any]:
    return {
        "id": check_id,
        "severity": "error",
        "valid": True,
        "observed": observed,
        "expected": expected,
        "sample": sample or [],
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


def blocking_checks(checks: list[dict[str, Any]]) -> list[str]:
    return [check["id"] for check in checks if check["severity"] == "error" and not check["valid"]]


def warning_checks(checks: list[dict[str, Any]]) -> list[str]:
    return [check["id"] for check in checks if check["severity"] == "warning" and not check["valid"]]


def report_warnings(report: dict[str, Any]) -> list[str]:
    return list(report.get("summary", {}).get("warnings", []))


def report_blocking_errors(report: dict[str, Any]) -> list[str]:
    return list(report.get("summary", {}).get("blocking_errors", []))


def validate_spec(spec: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    missing = sorted(REQUIRED_SPEC_FIELDS - set(spec))
    if missing:
        checks.append(failed("package_spec_required_fields", missing, "all required fields"))
        return checks
    checks.append(passed("package_spec_required_fields", len(REQUIRED_SPEC_FIELDS), len(REQUIRED_SPEC_FIELDS)))

    output = spec.get("output", {})
    missing_outputs = sorted(EXPECTED_OUTPUT_FIELDS - set(output))
    if missing_outputs:
        checks.append(failed("package_output_contract_complete", missing_outputs, "all output filenames"))
    else:
        checks.append(passed("package_output_contract_complete", sorted(output.values()), "all output filenames"))

    decision_policy = spec.get("decision_policy", {})
    allowed_statuses = set(decision_policy.get("allowed_statuses", []))
    status = decision_policy.get("candidate_failed_gate_status")
    forbidden_flags = {
        "production_ready_allowed": decision_policy.get("production_ready_allowed"),
        "causal_claim_allowed": decision_policy.get("causal_claim_allowed"),
        "serving_release_allowed": decision_policy.get("serving_release_allowed"),
    }
    if status not in allowed_statuses or any(value is not False for value in forbidden_flags.values()):
        checks.append(
            failed(
                "decision_policy_blocks_production_causal_and_serving_claims",
                {"status": status, **forbidden_flags},
                "allowed non-production status with production/causal/serving disabled",
            )
        )
    else:
        checks.append(
            passed(
                "decision_policy_blocks_production_causal_and_serving_claims",
                {"status": status, **forbidden_flags},
                "allowed non-production status with production/causal/serving disabled",
            )
        )
    return checks


def validate_required_paths(
    input_paths: dict[str, Path],
    report_paths: dict[str, Path],
    table_paths: dict[str, Path],
    spec: dict[str, Any],
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    required_reports = set(spec.get("required_upstream_reports", []))
    required_files = set(spec.get("required_evidence_files", []))
    missing_reports = sorted(name for name in required_reports if name not in report_paths or not report_paths[name].is_file())
    missing_files = sorted(
        name
        for name in required_files
        if not ((name in input_paths and input_paths[name].is_file()) or (name in table_paths and table_paths[name].is_file()))
    )
    if missing_reports or missing_files:
        checks.append(
            failed(
                "required_upstream_evidence_files_exist",
                {"missing_reports": missing_reports, "missing_files": missing_files},
                "all declared reports and evidence files exist",
            )
        )
    else:
        checks.append(
            passed(
                "required_upstream_evidence_files_exist",
                {"report_count": len(required_reports), "evidence_file_count": len(required_files)},
                "all declared reports and evidence files exist",
            )
        )
    return checks


def validate_upstream_reports(reports: dict[str, dict[str, Any]], spec: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    invalid = {
        name: {"valid": report.get("valid"), "blocking_errors": report_blocking_errors(report)}
        for name, report in reports.items()
        if report.get("valid") is not True or report_blocking_errors(report)
    }
    if invalid:
        checks.append(failed("upstream_reports_are_valid", invalid, "all upstream reports valid with no blocking errors"))
    else:
        checks.append(passed("upstream_reports_are_valid", sorted(reports), "all upstream reports valid with no blocking errors"))

    problem_mismatches = []
    for name, report in reports.items():
        problem_id = report.get("summary", {}).get("problem_id")
        if problem_id and problem_id != spec["problem_id"]:
            problem_mismatches.append({"report": name, "observed": problem_id})
    if problem_mismatches:
        checks.append(failed("upstream_problem_ids_match_package_spec", problem_mismatches, spec["problem_id"]))
    else:
        checks.append(passed("upstream_problem_ids_match_package_spec", spec["problem_id"], spec["problem_id"]))

    mlflow_summary = reports.get("mlflow_report", {}).get("summary", {})
    if (
        mlflow_summary.get("mlflow_tracking_audit_id") == spec["source_mlflow_tracking_audit_id"]
        and mlflow_summary.get("readiness_status") == "ready_for_drift_and_stability_lesson"
    ):
        checks.append(passed("mlflow_handoff_ready_for_stability_package", mlflow_summary.get("readiness_status")))
    else:
        checks.append(
            failed(
                "mlflow_handoff_ready_for_stability_package",
                {
                    "audit_id": mlflow_summary.get("mlflow_tracking_audit_id"),
                    "readiness_status": mlflow_summary.get("readiness_status"),
                },
                {
                    "audit_id": spec["source_mlflow_tracking_audit_id"],
                    "readiness_status": "ready_for_drift_and_stability_lesson",
                },
            )
        )
    return checks


def ks_like_gap(reference: list[float], comparison: list[float]) -> float:
    if not reference or not comparison:
        return 0.0
    points = sorted(set(reference + comparison))
    max_gap = 0.0
    for point in points:
        ref_cdf = sum(value <= point for value in reference) / len(reference)
        cmp_cdf = sum(value <= point for value in comparison) / len(comparison)
        max_gap = max(max_gap, abs(ref_cdf - cmp_cdf))
    return max_gap


def build_score_drift_rows(prediction_rows: list[dict[str, str]], policy: dict[str, Any]) -> list[dict[str, Any]]:
    reference_split = policy["score_reference_split"]
    grouped: dict[str, list[dict[str, str]]] = {}
    for row in prediction_rows:
        grouped.setdefault(row["split"], []).append(row)
    reference_scores = [as_float(row["score"]) for row in grouped.get(reference_split, [])]
    reference_mean = mean(reference_scores)
    rows: list[dict[str, Any]] = []
    for split in ["train", "validation", "test"]:
        split_rows = grouped.get(split, [])
        scores = [as_float(row["score"]) for row in split_rows]
        labels = [as_float(row["actual_label"]) for row in split_rows]
        mean_delta = mean(scores) - reference_mean
        gap = ks_like_gap(reference_scores, scores)
        watch = abs(mean_delta) > policy["score_watch_abs_mean_delta"] or gap > policy["score_watch_ks_like_gap"]
        rows.append(
            {
                "split": split,
                "reference_split": reference_split,
                "row_count": len(split_rows),
                "mean_score": round_float(mean(scores)),
                "std_score": round_float(stddev(scores)),
                "min_score": round_float(min(scores) if scores else 0.0),
                "max_score": round_float(max(scores) if scores else 0.0),
                "positive_rate": round_float(mean(labels)),
                "mean_delta_vs_reference": round_float(mean_delta),
                "ks_like_gap_vs_reference": round_float(gap),
                "stability_status": "watch" if watch else "stable",
                "interpretation": "score_distribution_shift_watch" if watch else "tiny_score_distribution_stable",
            }
        )
    return rows


def build_feature_drift_rows(inventory_rows: list[dict[str, str]], policy: dict[str, Any]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, str]]] = {}
    for row in inventory_rows:
        grouped.setdefault(row["feature_name"], []).append(row)
    rows: list[dict[str, Any]] = []
    for feature_name, feature_rows in grouped.items():
        after_train_total = sum(int(row["validation_count"]) + int(row["test_count"]) for row in feature_rows)
        unseen_after_train_count = sum(
            int(row["validation_count"]) + int(row["test_count"])
            for row in feature_rows
            if as_bool(row["unseen_in_train"])
        )
        missing_after_train_count = sum(
            int(row["validation_count"]) + int(row["test_count"])
            for row in feature_rows
            if as_bool(row["missing_value"])
        )
        high_cardinality = any(as_bool(row["high_cardinality_feature"]) for row in feature_rows)
        unseen_rate = unseen_after_train_count / after_train_total if after_train_total else 0.0
        watch = unseen_rate > policy["feature_watch_unseen_after_train_rate"] or (
            high_cardinality and policy.get("feature_watch_high_cardinality") is True
        )
        rows.append(
            {
                "feature_name": feature_name,
                "category_row_count": len(feature_rows),
                "after_train_row_count": after_train_total,
                "unseen_after_train_count": unseen_after_train_count,
                "unseen_after_train_rate": round_float(unseen_rate),
                "missing_after_train_count": missing_after_train_count,
                "high_cardinality_feature": high_cardinality,
                "unknown_category_policy": feature_rows[0].get("unknown_category_policy", ""),
                "stability_status": "watch" if watch else "stable",
                "interpretation": "new_categories_require_monitoring" if watch else "known_category_mix_within_policy",
            }
        )
    return sorted(rows, key=lambda row: (row["stability_status"] != "watch", row["feature_name"]))


def build_importance_stability_rows(disagreement_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    top_features = {row["top_feature_name"] for row in disagreement_rows}
    directions = {row["direction"] for row in disagreement_rows}
    conflict = len(directions) > 1 or any(row["disagreement_status"] != "aligned" for row in disagreement_rows)
    status = "watch" if conflict else "stable"
    rows = []
    for row in disagreement_rows:
        rows.append(
            {
                "method": row["method"],
                "source_audit_id": row["source_audit_id"],
                "top_feature_name": row["top_feature_name"],
                "rank_basis": row["rank_basis"],
                "raw_value": row["raw_value"],
                "direction": row["direction"],
                "split": row["split"],
                "output_space": row["output_space"],
                "same_top_feature_across_methods": len(top_features) == 1,
                "direction_set": ",".join(sorted(directions)),
                "stability_status": status,
                "interpretation": "same_feature_but_conflicting_method_meaning" if conflict else "methods_aligned",
            }
        )
    return rows


def build_segment_stability_rows(delta_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in delta_rows:
        hidden = as_bool(row["hidden_failure_candidate"])
        small_n = as_bool(row["small_n_warning"])
        worse = as_bool(row["candidate_worse_than_baseline"])
        if hidden:
            status = "blocked_for_promotion"
        elif small_n:
            status = "diagnostic_small_n"
        elif worse:
            status = "watch"
        else:
            status = "stable"
        rows.append(
            {
                "dimension": row["dimension"],
                "slice_value": row["slice_value"],
                "baseline_row_count": int(row["baseline_row_count"]),
                "candidate_row_count": int(row["candidate_row_count"]),
                "precision_delta": row["precision_delta"],
                "recall_delta": row["recall_delta"],
                "error_rate_delta": row["error_rate_delta"],
                "candidate_worse_than_baseline": worse,
                "hidden_failure_candidate": hidden,
                "small_n_warning": small_n,
                "hidden_failure_reasons": row["hidden_failure_reasons"],
                "stability_status": status,
            }
        )
    return rows


def summarize_stability(
    score_rows: list[dict[str, Any]],
    feature_rows: list[dict[str, Any]],
    importance_rows: list[dict[str, Any]],
    segment_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    feature_watch = [row["feature_name"] for row in feature_rows if row["stability_status"] == "watch"]
    importance_watch = [row for row in importance_rows if row["stability_status"] == "watch"]
    hidden_segments = [row for row in segment_rows if row["hidden_failure_candidate"]]
    score_watch = [row for row in score_rows if row["stability_status"] == "watch"]
    return {
        "generated_at": GENERATED_AT,
        "overall_status": "watch_required" if feature_watch or importance_watch or hidden_segments or score_watch else "stable",
        "score_drift": {
            "status": "watch" if score_watch else "stable",
            "row_count": len(score_rows),
            "max_abs_mean_delta": round_float(max(abs(row["mean_delta_vs_reference"]) for row in score_rows)),
            "watch_splits": [row["split"] for row in score_watch],
        },
        "feature_drift": {
            "status": "watch" if feature_watch else "stable",
            "row_count": len(feature_rows),
            "watch_features": feature_watch,
            "max_unseen_after_train_rate": round_float(max(row["unseen_after_train_rate"] for row in feature_rows)),
        },
        "importance_stability": {
            "status": "watch" if importance_watch else "stable",
            "row_count": len(importance_rows),
            "top_feature": importance_rows[0]["top_feature_name"] if importance_rows else None,
            "direction_set": importance_rows[0]["direction_set"] if importance_rows else "",
        },
        "segment_stability": {
            "status": "blocked_for_promotion" if hidden_segments else "stable",
            "row_count": len(segment_rows),
            "hidden_failure_slice_count": len(hidden_segments),
            "small_n_slice_count": sum(1 for row in segment_rows if row["small_n_warning"]),
        },
    }


def required_promotion_failures(decision_gate_rows: list[dict[str, str]]) -> list[str]:
    return [
        row["gate_id"]
        for row in decision_gate_rows
        if as_bool(row["required_for_promotion"]) and not as_bool(row["passed"])
    ]


def validate_package_gates(
    spec: dict[str, Any],
    reports: dict[str, dict[str, Any]],
    decision_gate_rows: list[dict[str, str]],
    stability_report: dict[str, Any],
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    failures = required_promotion_failures(decision_gate_rows)
    decision_status = spec["decision_policy"]["candidate_failed_gate_status"] if failures else "promote_candidate_with_limits"
    if failures and decision_status == "promote_candidate_with_limits":
        checks.append(
            failed(
                "candidate_cannot_be_promoted_when_required_decision_gates_fail",
                {"decision_status": decision_status, "failed_gates": failures},
                "non-promotion decision status",
            )
        )
    else:
        checks.append(
            passed(
                "candidate_cannot_be_promoted_when_required_decision_gates_fail",
                {"decision_status": decision_status, "failed_gates": failures},
                "non-promotion decision status",
            )
        )

    if stability_report["feature_drift"]["status"] == "watch":
        checks.append(
            failed(
                "feature_drift_watch_required",
                stability_report["feature_drift"]["watch_features"],
                "no feature drift watch features",
                severity="warning",
            )
        )
    else:
        checks.append(passed("feature_drift_watch_required", [], "no feature drift watch features"))

    if stability_report["importance_stability"]["status"] == "watch":
        checks.append(
            failed(
                "unstable_explanations_require_review",
                stability_report["importance_stability"],
                "aligned explanation methods",
                severity="warning",
            )
        )
    else:
        checks.append(passed("unstable_explanations_require_review", "stable", "stable"))

    if stability_report["segment_stability"]["hidden_failure_slice_count"] > 0:
        checks.append(
            failed(
                "segment_hidden_failures_block_candidate_promotion",
                stability_report["segment_stability"]["hidden_failure_slice_count"],
                0,
                severity="warning",
            )
        )
    else:
        checks.append(passed("segment_hidden_failures_block_candidate_promotion", 0, 0))

    cost_summary = reports["cost_report"]["summary"]
    if cost_summary.get("decision_status") == "do_not_promote_catboost_candidate":
        checks.append(
            failed(
                "candidate_not_promoted_due_to_cost_and_segment_gate",
                cost_summary.get("failed_promotion_gates"),
                "all promotion gates passed",
                severity="warning",
            )
        )
    else:
        checks.append(passed("candidate_not_promoted_due_to_cost_and_segment_gate", [], "all promotion gates passed"))

    mlflow_summary = reports["mlflow_report"]["summary"]
    if mlflow_summary.get("tracking_backend") == "local_file_store":
        checks.append(
            failed(
                "local_tracking_store_not_serving_release",
                mlflow_summary.get("tracking_backend"),
                "production serving release",
                severity="warning",
            )
        )
    else:
        checks.append(passed("local_tracking_store_not_serving_release", mlflow_summary.get("tracking_backend")))
    return checks


def build_evidence_matrix(
    reports: dict[str, dict[str, Any]],
    report_paths: dict[str, Path],
    input_paths: dict[str, Path],
    score_rows: list[dict[str, Any]],
    feature_rows: list[dict[str, Any]],
    importance_rows: list[dict[str, Any]],
    segment_rows: list[dict[str, Any]],
    output: dict[str, str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = [
        {
            "evidence_id": "baseline_package_manifest",
            "package_section": "input",
            "source_path": str(input_paths["baseline_package_manifest"].relative_to(REPO_ROOT)),
            "valid": True,
            "warning_count": 0,
            "blocking_error_count": 0,
            "key_summary": {"sha256": sha256_path(input_paths["baseline_package_manifest"])},
        }
    ]
    for name in [
        "baseline_package_report",
        "catboost_report",
        "categorical_report",
        "early_stopping_report",
        "built_in_importance_report",
        "permutation_importance_report",
        "shap_report",
        "segment_report",
        "cost_report",
        "optuna_report",
        "mlflow_report",
    ]:
        report = reports[name]
        summary = report.get("summary", {})
        rows.append(
            {
                "evidence_id": name,
                "package_section": "upstream",
                "source_path": str(report_paths[name].relative_to(REPO_ROOT)),
                "valid": report.get("valid") is True,
                "warning_count": len(summary.get("warnings", [])),
                "blocking_error_count": len(summary.get("blocking_errors", [])),
                "key_summary": {
                    "readiness_status": summary.get("readiness_status"),
                    "decision_status": summary.get("decision_status"),
                    "model_id": summary.get("model_id") or summary.get("candidate_model_id"),
                },
            }
        )
    generated_sources = [
        ("score_drift", "stability", output["score_drift_file"], {"row_count": len(score_rows), "watch_count": sum(row["stability_status"] == "watch" for row in score_rows)}),
        ("feature_drift", "stability", output["feature_drift_file"], {"row_count": len(feature_rows), "watch_count": sum(row["stability_status"] == "watch" for row in feature_rows)}),
        (
            "importance_stability",
            "interpretation",
            output["importance_stability_file"],
            {"row_count": len(importance_rows), "watch_count": sum(row["stability_status"] == "watch" for row in importance_rows)},
        ),
        (
            "segment_stability",
            "stability",
            output["segment_stability_file"],
            {"row_count": len(segment_rows), "hidden_failure_count": sum(row["hidden_failure_candidate"] for row in segment_rows)},
        ),
    ]
    for evidence_id, section, filename, summary in generated_sources:
        rows.append(
            {
                "evidence_id": evidence_id,
                "package_section": section,
                "source_path": filename,
                "valid": True,
                "warning_count": summary.get("watch_count", summary.get("hidden_failure_count", 0)),
                "blocking_error_count": 0,
                "key_summary": summary,
            }
        )
    return rows


def markdown_interpretation_report(
    spec: dict[str, Any],
    stability_report: dict[str, Any],
    importance_rows: list[dict[str, Any]],
    reports: dict[str, dict[str, Any]],
) -> str:
    shap_summary = reports["shap_report"]["summary"]
    lines = [
        "# Tabular ML interpretation report",
        "",
        f"Package: `{spec['package_id']}`.",
        "",
        "## Explanation stack",
        "",
        "- CatBoost built-in importance, permutation importance and Tree SHAP are included as separate evidence views.",
        f"- All methods point to `{stability_report['importance_stability']['top_feature']}` as the main diagnostic feature.",
        f"- Direction set: `{stability_report['importance_stability']['direction_set']}`.",
        "- This is model behavior evidence, not a causal claim about retention offers.",
        "",
        "## Stability limits",
        "",
        f"- SHAP output space: `{shap_summary['output_space']}`.",
        f"- SHAP background rows: `{shap_summary['background_row_count']}`.",
        f"- Feature drift watch features: `{', '.join(stability_report['feature_drift']['watch_features'])}`.",
        f"- Segment hidden failure slices: `{stability_report['segment_stability']['hidden_failure_slice_count']}`.",
        "",
        "## Method disagreement",
        "",
    ]
    for row in importance_rows:
        lines.append(
            f"- `{row['method']}`: top feature `{row['top_feature_name']}`, direction `{row['direction']}`, status `{row['stability_status']}`."
        )
    lines.extend(
        [
            "",
            "Interpretation is therefore diagnostic-only until larger validation data, stable feature mix and segment review are available.",
        ]
    )
    return "\n".join(lines) + "\n"


def markdown_decision_report(
    spec: dict[str, Any],
    decision_status: str,
    monitoring_status: str,
    failures: list[str],
    stability_report: dict[str, Any],
) -> str:
    return "\n".join(
        [
            "# Tabular ML decision report",
            "",
            f"Decision status: `{decision_status}`.",
            f"Monitoring status: `{monitoring_status}`.",
            "",
            "## Decision",
            "",
            f"Keep `{spec['baseline_model_id']}` as the selected baseline for the course handoff.",
            f"Do not promote `{spec['candidate_model_id']}` because required promotion gates failed.",
            "",
            "## Failed gates",
            "",
            *[f"- `{failure}`" for failure in failures],
            "",
            "## Boundaries",
            "",
            "- This package does not make a causal claim about the retention offer.",
            "- This package is not a production serving release or model registry approval.",
            "- Drift and stability diagnostics are local offline checks, not online monitoring.",
            "",
            "## Stability notes",
            "",
            f"- Feature drift status: `{stability_report['feature_drift']['status']}`.",
            f"- Importance stability status: `{stability_report['importance_stability']['status']}`.",
            f"- Segment stability status: `{stability_report['segment_stability']['status']}`.",
            "",
        ]
    )


def build_manifest(
    inputs: dict[str, Path],
    outputs_payload: dict[str, str],
) -> dict[str, Any]:
    return {
        "hash_algorithm": "sha256",
        "generated_at": GENERATED_AT,
        "inputs": {
            name: {
                "path": path_label(path),
                "bytes": path.stat().st_size,
                "sha256": sha256_path(path),
            }
            for name, path in sorted(inputs.items())
        },
        "outputs": {
            filename: {
                "bytes": len(payload.encode("utf-8")),
                "sha256": sha256_bytes(payload.encode("utf-8")),
            }
            for filename, payload in sorted(outputs_payload.items())
        },
    }


def build_tabular_ml_package(
    *,
    spec_path: Path = DEFAULT_SPEC_PATH,
    input_paths: dict[str, Path] | None = None,
    report_paths: dict[str, Path] | None = None,
    table_paths: dict[str, Path] | None = None,
) -> dict[str, Any]:
    input_paths = input_paths or DEFAULT_INPUT_PATHS
    report_paths = report_paths or DEFAULT_REPORT_PATHS
    table_paths = table_paths or DEFAULT_TABLE_PATHS
    spec = read_json(spec_path)
    checks = validate_spec(spec)
    checks.extend(validate_required_paths(input_paths, report_paths, table_paths, spec))

    reports: dict[str, dict[str, Any]] = {}
    if not blocking_checks(checks):
        reports = {name: read_json(path) for name, path in report_paths.items() if name in spec["required_upstream_reports"]}
        checks.extend(validate_upstream_reports(reports, spec))

    if blocking_checks(checks):
        report = {
            "valid": False,
            "decision_status": "blocked_before_package_build",
            "summary": {
                "package_id": spec.get("package_id"),
                "blocking_errors": blocking_checks(checks),
                "warnings": warning_checks(checks),
                "readiness_status": "blocked_before_tabular_ml_package",
            },
            "checks": checks,
        }
        return {"report": report}

    prediction_rows, _ = read_csv(table_paths["optuna_tuned_predictions"])
    inventory_rows, _ = read_csv(table_paths["categorical_inventory"])
    disagreement_rows, _ = read_csv(table_paths["explanation_disagreement"])
    segment_delta_rows, _ = read_csv(table_paths["strong_model_segment_deltas"])
    decision_gate_rows, _ = read_csv(table_paths["decision_gate"])

    score_rows = build_score_drift_rows(prediction_rows, spec["drift_policy"])
    feature_rows = build_feature_drift_rows(inventory_rows, spec["drift_policy"])
    importance_rows = build_importance_stability_rows(disagreement_rows)
    segment_rows = build_segment_stability_rows(segment_delta_rows)
    stability_report = summarize_stability(score_rows, feature_rows, importance_rows, segment_rows)
    checks.extend(validate_package_gates(spec, reports, decision_gate_rows, stability_report))

    failures = required_promotion_failures(decision_gate_rows)
    decision_status = spec["decision_policy"]["candidate_failed_gate_status"] if failures else "promote_candidate_with_limits"
    monitoring_status = (
        spec["decision_policy"]["monitoring_status_with_warnings"]
        if stability_report["overall_status"] == "watch_required"
        else "stable_offline_package"
    )
    evidence_matrix = build_evidence_matrix(
        reports,
        report_paths,
        input_paths,
        score_rows,
        feature_rows,
        importance_rows,
        segment_rows,
        spec["output"],
    )
    interpretation_report = markdown_interpretation_report(spec, stability_report, importance_rows, reports)
    decision_report = markdown_decision_report(spec, decision_status, monitoring_status, failures, stability_report)

    package = {
        "package_id": spec["package_id"],
        "problem_id": spec["problem_id"],
        "source_baseline_package_id": spec["source_baseline_package_id"],
        "source_mlflow_tracking_audit_id": spec["source_mlflow_tracking_audit_id"],
        "candidate_model_id": spec["candidate_model_id"],
        "baseline_model_id": spec["baseline_model_id"],
        "decision": {
            "decision_status": decision_status,
            "monitoring_status": monitoring_status,
            "production_ready": False,
            "causal_claim_made": False,
            "serving_release": False,
            "failed_promotion_gates": failures,
            "blocked_actions": [
                "promote_catboost_candidate",
                "claim_causal_offer_effect",
                "register_or_serve_model",
            ],
        },
        "stability": stability_report,
        "evidence": {
            "evidence_row_count": len(evidence_matrix),
            "upstream_report_count": len(spec["required_upstream_reports"]),
            "required_evidence_file_count": len(spec["required_evidence_files"]),
        },
        "generated_at": GENERATED_AT,
    }

    output = spec["output"]
    output_payloads_without_report = {
        output["package_file"]: json_text(package),
        output["evidence_matrix_file"]: csv_text(
            evidence_matrix,
            ["evidence_id", "package_section", "source_path", "valid", "warning_count", "blocking_error_count", "key_summary"],
        ),
        output["score_drift_file"]: csv_text(
            score_rows,
            [
                "split",
                "reference_split",
                "row_count",
                "mean_score",
                "std_score",
                "min_score",
                "max_score",
                "positive_rate",
                "mean_delta_vs_reference",
                "ks_like_gap_vs_reference",
                "stability_status",
                "interpretation",
            ],
        ),
        output["feature_drift_file"]: csv_text(
            feature_rows,
            [
                "feature_name",
                "category_row_count",
                "after_train_row_count",
                "unseen_after_train_count",
                "unseen_after_train_rate",
                "missing_after_train_count",
                "high_cardinality_feature",
                "unknown_category_policy",
                "stability_status",
                "interpretation",
            ],
        ),
        output["importance_stability_file"]: csv_text(
            importance_rows,
            [
                "method",
                "source_audit_id",
                "top_feature_name",
                "rank_basis",
                "raw_value",
                "direction",
                "split",
                "output_space",
                "same_top_feature_across_methods",
                "direction_set",
                "stability_status",
                "interpretation",
            ],
        ),
        output["segment_stability_file"]: csv_text(
            segment_rows,
            [
                "dimension",
                "slice_value",
                "baseline_row_count",
                "candidate_row_count",
                "precision_delta",
                "recall_delta",
                "error_rate_delta",
                "candidate_worse_than_baseline",
                "hidden_failure_candidate",
                "small_n_warning",
                "hidden_failure_reasons",
                "stability_status",
            ],
        ),
        output["stability_report_file"]: json_text(stability_report),
        output["interpretation_report_file"]: interpretation_report,
        output["decision_report_file"]: decision_report,
    }
    all_inputs = {"package_spec": spec_path, **input_paths, **report_paths, **table_paths}
    planned_manifest_input_count = len(all_inputs)
    planned_manifest_output_count = len(output_payloads_without_report) + 1
    checks.append(
        passed(
            "manifest_hashes_inputs_and_generated_outputs",
            {"input_count": planned_manifest_input_count, "output_count": planned_manifest_output_count},
            "sha256 manifest for inputs and generated outputs",
        )
    )
    report = {
        "valid": not blocking_checks(checks),
        "decision_status": decision_status,
        "summary": {
            "package_id": spec["package_id"],
            "problem_id": spec["problem_id"],
            "source_baseline_package_id": spec["source_baseline_package_id"],
            "candidate_model_id": spec["candidate_model_id"],
            "baseline_model_id": spec["baseline_model_id"],
            "evidence_row_count": len(evidence_matrix),
            "upstream_report_count": len(spec["required_upstream_reports"]),
            "upstream_warning_count": sum(len(report_warnings(report)) for report in reports.values()),
            "score_drift_row_count": len(score_rows),
            "score_drift_watch_count": sum(row["stability_status"] == "watch" for row in score_rows),
            "feature_drift_row_count": len(feature_rows),
            "feature_drift_watch_count": sum(row["stability_status"] == "watch" for row in feature_rows),
            "importance_stability_row_count": len(importance_rows),
            "importance_stability_watch_count": sum(row["stability_status"] == "watch" for row in importance_rows),
            "segment_stability_row_count": len(segment_rows),
            "hidden_failure_slice_count": stability_report["segment_stability"]["hidden_failure_slice_count"],
            "failed_promotion_gate_count": len(failures),
            "manifest_input_count": planned_manifest_input_count,
            "manifest_output_count": planned_manifest_output_count,
            "production_ready": False,
            "monitoring_status": monitoring_status,
            "blocking_errors": blocking_checks(checks),
            "warnings": warning_checks(checks),
            "readiness_status": "phase_16_complete_tabular_ml_interpretation_package",
        },
        "checks": checks,
        "outputs": {
            "package_file": output["package_file"],
            "decision_report_file": output["decision_report_file"],
            "interpretation_report_file": output["interpretation_report_file"],
            "manifest_file": output["manifest_file"],
        },
    }
    report_payload = json_text(report)
    payloads_for_manifest = {
        **output_payloads_without_report,
        output["report_file"]: report_payload,
    }
    manifest = build_manifest(all_inputs, payloads_for_manifest)
    output_payloads = {
        **payloads_for_manifest,
        output["manifest_file"]: json_text(manifest),
    }
    return {
        "package": package,
        "report": report,
        "evidence_matrix": evidence_matrix,
        "score_drift": score_rows,
        "feature_drift": feature_rows,
        "importance_stability": importance_rows,
        "segment_stability": segment_rows,
        "stability_report": stability_report,
        "interpretation_report": interpretation_report,
        "decision_report": decision_report,
        "manifest": manifest,
        "output_payloads": output_payloads,
        "output": output,
    }


def write_outputs(result: dict[str, Any], output_dir: Path, output: dict[str, str] | None = None) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    if "output_payloads" not in result:
        output = output or read_json(DEFAULT_SPEC_PATH)["output"]
        write_json(output_dir / output["report_file"], result["report"])
        return
    for filename, payload in result["output_payloads"].items():
        (output_dir / filename).write_text(payload, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the final tabular ML interpretation package.")
    parser.add_argument("--spec-path", type=Path, default=DEFAULT_SPEC_PATH)
    parser.add_argument("--output-dir", type=Path, default=LESSON_ROOT / "outputs")
    parser.add_argument("--fail-on-warning", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = build_tabular_ml_package(spec_path=args.spec_path)
    output = read_json(args.spec_path).get("output", {})
    write_outputs(result, args.output_dir, output)
    report = result["report"]
    if not report["valid"]:
        return 1
    if args.fail_on_warning and report["summary"]["warnings"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
