from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from collections import Counter
from pathlib import Path
from typing import Any


LESSON_ROOT = Path(__file__).resolve().parents[1]
PHASE_ROOT = LESSON_ROOT.parent
REPO_ROOT = LESSON_ROOT.parents[2]
DATA_ROOT = PHASE_ROOT / "data" / "tiny"
GENERATED_AT = "2026-07-03T11:00:00+03:00"


def portable_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return path.name


REQUIRED_SPEC_FIELDS = {
    "package_id",
    "model_card_id",
    "problem_id",
    "source_model_id",
    "error_analysis_policy_id",
    "package_version",
    "required_upstream_reports",
    "required_evidence_tables",
    "model_card_sections",
    "model_card_policy",
    "decision_policy",
    "risk_policy",
    "output",
}
REQUIRED_MODEL_CARD_SECTIONS = [
    "model_details",
    "intended_use",
    "out_of_scope_uses",
    "training_data",
    "evaluation_data",
    "metrics",
    "calibration",
    "error_analysis",
    "limitations",
    "ethical_considerations",
    "decision",
    "maintenance",
]
EXPECTED_OUTPUT_FILES = {
    "package_file",
    "report_file",
    "model_card_file",
    "decision_report_file",
    "evidence_matrix_file",
    "risk_register_file",
    "audit_file",
    "manifest_file",
}
DEFAULT_REPORT_PATHS = {
    "problem_report": PHASE_ROOT / "01-problem-framing" / "outputs" / "ml_problem_readiness_report.json",
    "split_report": PHASE_ROOT / "02-data-splitting" / "outputs" / "ml_split_report.json",
    "metric_report": PHASE_ROOT / "03-metrics" / "outputs" / "classification_metric_report.json",
    "preprocessing_report": PHASE_ROOT / "04-preprocessing" / "outputs" / "preprocessing_report.json",
    "pipeline_report": PHASE_ROOT / "05-pipeline" / "outputs" / "pipeline_report.json",
    "column_transformer_report": PHASE_ROOT
    / "06-column-transformer"
    / "outputs"
    / "column_transformer_report.json",
    "baseline_report": PHASE_ROOT / "07-linear-models" / "outputs" / "baseline_report.json",
    "tree_report": PHASE_ROOT / "08-trees" / "outputs" / "tree_report.json",
    "ensemble_report": PHASE_ROOT / "09-ensembles" / "outputs" / "ensemble_report.json",
    "cv_report": PHASE_ROOT / "10-cross-validation" / "outputs" / "cv_report.json",
    "imbalance_report": PHASE_ROOT / "11-imbalanced-data" / "outputs" / "imbalance_report.json",
    "calibration_report": PHASE_ROOT / "12-calibration" / "outputs" / "calibration_report.json",
    "leakage_report": PHASE_ROOT / "13-leakage" / "outputs" / "leakage_report.json",
    "error_analysis_report": PHASE_ROOT
    / "14-error-analysis"
    / "outputs"
    / "error_analysis_report.json",
}
DEFAULT_TABLE_PATHS = {
    "column_transformer_feature_schema": PHASE_ROOT
    / "06-column-transformer"
    / "outputs"
    / "column_transformer_feature_schema.csv",
    "ensemble_feature_importance": PHASE_ROOT
    / "09-ensembles"
    / "outputs"
    / "ensemble_feature_importance.csv",
    "class_distribution": PHASE_ROOT
    / "11-imbalanced-data"
    / "outputs"
    / "class_distribution.csv",
    "imbalance_threshold_report": PHASE_ROOT
    / "11-imbalanced-data"
    / "outputs"
    / "imbalance_threshold_report.csv",
    "calibration_metrics": PHASE_ROOT
    / "12-calibration"
    / "outputs"
    / "calibration_metrics.csv",
    "calibration_threshold_impact": PHASE_ROOT
    / "12-calibration"
    / "outputs"
    / "calibration_threshold_impact.csv",
    "forbidden_feature_report": PHASE_ROOT
    / "13-leakage"
    / "outputs"
    / "forbidden_feature_report.csv",
    "model_selection_audit": PHASE_ROOT
    / "13-leakage"
    / "outputs"
    / "model_selection_audit.csv",
    "confusion_rows": PHASE_ROOT / "14-error-analysis" / "outputs" / "confusion_rows.csv",
    "slice_metrics": PHASE_ROOT / "14-error-analysis" / "outputs" / "slice_metrics.csv",
    "small_n_warnings": PHASE_ROOT
    / "14-error-analysis"
    / "outputs"
    / "small_n_warnings.csv",
    "hidden_failure_slices": PHASE_ROOT
    / "14-error-analysis"
    / "outputs"
    / "hidden_failure_slices.csv",
    "error_examples": PHASE_ROOT / "14-error-analysis" / "outputs" / "error_examples.csv",
}
TABLE_REQUIRED_COLUMNS = {
    "confusion_rows": {"snapshot_id", "split", "confusion_label", "selected_for_action"},
    "slice_metrics": {
        "dimension",
        "slice_value",
        "row_count",
        "precision",
        "recall",
        "hidden_failure_candidate",
    },
    "small_n_warnings": {"dimension", "slice_value", "row_count", "interpretation"},
    "hidden_failure_slices": {"dimension", "slice_value", "row_count", "hidden_failure_reasons"},
    "error_examples": {"snapshot_id", "confusion_label", "false_positive", "false_negative"},
    "calibration_metrics": {"split", "probability_source", "brier_score", "log_loss"},
    "forbidden_feature_report": {"feature_name", "risk_type", "decision"},
    "model_selection_audit": {"candidate_id", "selection_split", "decision"},
}


class MLBaselinePackageError(ValueError):
    """Raised when the ML baseline package cannot be built."""


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise MLBaselinePackageError(f"{path.name} must contain a JSON object")
    return payload


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open(encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        return list(reader), list(reader.fieldnames or [])


def json_text(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json_text(payload), encoding="utf-8")


def stringify(value: Any) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    if value is None:
        return ""
    return str(value)


def csv_text(rows: list[dict[str, Any]], fieldnames: list[str]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({field: stringify(row.get(field, "")) for field in fieldnames})
    return buffer.getvalue()


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(csv_text(rows, fieldnames), encoding="utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_path(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


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


def blocking_checks(checks: list[dict[str, Any]]) -> list[str]:
    return [
        check["id"]
        for check in checks
        if check["severity"] == "error" and not check["valid"]
    ]


def warning_checks(checks: list[dict[str, Any]]) -> list[str]:
    return [
        check["id"]
        for check in checks
        if check["severity"] == "warning" and not check["valid"]
    ]


def report_warnings(report: dict[str, Any]) -> list[str]:
    return list(report.get("summary", {}).get("warnings", []))


def report_blocking_errors(report: dict[str, Any]) -> list[str]:
    return list(report.get("summary", {}).get("blocking_errors", []))


def validate_package_spec(spec: dict[str, Any], problem_spec: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    missing = sorted(REQUIRED_SPEC_FIELDS - set(spec))
    if missing:
        checks.append(failed("package_spec_required_fields", missing, "all required fields"))
        return checks
    checks.append(passed("package_spec_required_fields", len(REQUIRED_SPEC_FIELDS)))

    sections = spec.get("model_card_sections")
    missing_sections = [section for section in REQUIRED_MODEL_CARD_SECTIONS if section not in sections]
    if missing_sections:
        checks.append(
            failed(
                "model_card_sections_complete",
                missing_sections,
                REQUIRED_MODEL_CARD_SECTIONS,
            )
        )
    else:
        checks.append(passed("model_card_sections_complete", sections))

    output = spec.get("output", {})
    missing_output = sorted(EXPECTED_OUTPUT_FILES - set(output))
    if missing_output:
        checks.append(failed("package_output_contract_complete", missing_output, "all output files"))
    else:
        checks.append(passed("package_output_contract_complete", sorted(output.values())))

    problem_policy = problem_spec.get("model_card_policy", {})
    package_policy = spec.get("model_card_policy", {})
    if package_policy.get("intended_use") != problem_policy.get("intended_use"):
        checks.append(
            failed(
                "model_card_intended_use_matches_problem_spec",
                package_policy.get("intended_use"),
                problem_policy.get("intended_use"),
            )
        )
    else:
        checks.append(passed("model_card_intended_use_matches_problem_spec", package_policy.get("intended_use")))

    out_of_scope = set(package_policy.get("out_of_scope_uses", []))
    required_out_of_scope = {
        "causal_effect_of_offer",
        "automatic_account_action",
        "production_deployment_without_monitoring",
    }
    if not required_out_of_scope.issubset(out_of_scope):
        checks.append(
            failed(
                "model_card_blocks_out_of_scope_uses",
                sorted(out_of_scope),
                sorted(required_out_of_scope),
            )
        )
    else:
        checks.append(passed("model_card_blocks_out_of_scope_uses", sorted(out_of_scope)))

    decision_policy = spec.get("decision_policy", {})
    forbidden_claims = set(decision_policy.get("forbidden_claims", []))
    if (
        decision_policy.get("valid_with_warnings_status")
        != "review_required_before_production"
        or "production_ready" not in forbidden_claims
        or "causal_offer_effect" not in forbidden_claims
    ):
        checks.append(
            failed(
                "decision_policy_blocks_production_and_causal_claims",
                decision_policy,
                "review before production and no causal offer-effect claim",
            )
        )
    else:
        checks.append(
            passed(
                "decision_policy_blocks_production_and_causal_claims",
                decision_policy["valid_with_warnings_status"],
            )
        )

    risk_policy = spec.get("risk_policy", {})
    required_flags = [
        "propagate_upstream_warnings",
        "hidden_failure_blocks_production_claim",
        "small_n_blocks_segment_claim",
        "require_no_test_selection",
        "require_no_causal_offer_claim",
        "pickle_security_notice_required",
    ]
    missing_flags = [field for field in required_flags if risk_policy.get(field) is not True]
    if missing_flags or risk_policy.get("hash_algorithm") != "sha256":
        checks.append(
            failed(
                "risk_policy_requires_warning_propagation_and_sha256_manifest",
                {"missing_flags": missing_flags, "hash_algorithm": risk_policy.get("hash_algorithm")},
                "all risk flags true and sha256",
            )
        )
    else:
        checks.append(passed("risk_policy_requires_warning_propagation_and_sha256_manifest", "sha256"))
    return checks


def load_reports(report_paths: dict[str, Path], checks: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    reports: dict[str, dict[str, Any]] = {}
    missing = [
        {"id": key, "path": portable_path(path)}
        for key, path in report_paths.items()
        if not path.exists()
    ]
    if missing:
        checks.append(failed("all_required_upstream_reports_present", len(missing), 0, missing))
    else:
        checks.append(passed("all_required_upstream_reports_present", len(report_paths)))
    invalid: list[dict[str, str]] = []
    for key, path in report_paths.items():
        if not path.exists():
            continue
        try:
            reports[key] = read_json(path)
        except json.JSONDecodeError as error:
            invalid.append(
                {"id": key, "path": portable_path(path), "error": str(error)}
            )
    if invalid:
        checks.append(failed("all_required_upstream_reports_parse", invalid, "valid JSON"))
    else:
        checks.append(passed("all_required_upstream_reports_parse", len(reports)))
    return reports


def load_tables(table_paths: dict[str, Path], checks: list[dict[str, Any]]) -> dict[str, list[dict[str, str]]]:
    tables: dict[str, list[dict[str, str]]] = {}
    missing = [
        {"id": key, "path": portable_path(path)}
        for key, path in table_paths.items()
        if not path.exists()
    ]
    if missing:
        checks.append(failed("all_required_evidence_tables_present", len(missing), 0, missing))
    else:
        checks.append(passed("all_required_evidence_tables_present", len(table_paths)))
    column_errors: list[dict[str, Any]] = []
    for key, path in table_paths.items():
        if not path.exists():
            continue
        rows, fields = read_csv(path)
        tables[key] = rows
        required = TABLE_REQUIRED_COLUMNS.get(key)
        if required and not required.issubset(set(fields)):
            column_errors.append(
                {"id": key, "missing": sorted(required - set(fields)), "observed": fields}
            )
    if column_errors:
        checks.append(failed("evidence_tables_required_columns", column_errors, "required columns"))
    else:
        checks.append(passed("evidence_tables_required_columns", len(tables)))
    return tables


def validate_upstream_reports(
    spec: dict[str, Any],
    reports: dict[str, dict[str, Any]],
    checks: list[dict[str, Any]],
) -> None:
    required_ids = [item["id"] for item in spec.get("required_upstream_reports", [])]
    missing_report_ids = [report_id for report_id in required_ids if report_id not in reports]
    if missing_report_ids:
        checks.append(failed("package_spec_reports_match_inputs", missing_report_ids, required_ids))
        return
    checks.append(passed("package_spec_reports_match_inputs", required_ids))

    invalid_reports = [
        {"id": report_id, "blocking_errors": report_blocking_errors(report)}
        for report_id, report in reports.items()
        if report.get("valid") is not True
    ]
    if invalid_reports:
        checks.append(failed("upstream_reports_are_structurally_valid", invalid_reports, "all valid"))
    else:
        checks.append(passed("upstream_reports_are_structurally_valid", len(reports)))

    readiness_mismatches: list[dict[str, Any]] = []
    for item in spec["required_upstream_reports"]:
        report = reports[item["id"]]
        observed = report.get("summary", {}).get("readiness_status")
        if observed != item["expected_readiness"]:
            readiness_mismatches.append(
                {
                    "id": item["id"],
                    "observed": observed,
                    "expected": item["expected_readiness"],
                }
            )
    if readiness_mismatches:
        checks.append(failed("upstream_readiness_chain_is_complete", readiness_mismatches, "expected readiness statuses"))
    else:
        checks.append(passed("upstream_readiness_chain_is_complete", len(spec["required_upstream_reports"])))

    problem_ids = {
        report_id: report.get("summary", {}).get("problem_id")
        for report_id, report in reports.items()
        if report.get("summary", {}).get("problem_id")
    }
    mismatched_problem_ids = {
        report_id: problem_id
        for report_id, problem_id in problem_ids.items()
        if problem_id != spec["problem_id"]
    }
    if mismatched_problem_ids:
        checks.append(failed("problem_ids_align_across_package", mismatched_problem_ids, spec["problem_id"]))
    else:
        checks.append(passed("problem_ids_align_across_package", spec["problem_id"]))

    model_ids = {
        "imbalance_report.selected_model_id": reports["imbalance_report"]["summary"].get("selected_model_id"),
        "calibration_report.source_model_id": reports["calibration_report"]["summary"].get("source_model_id"),
        "leakage_report.source_model_id": reports["leakage_report"]["summary"].get("source_model_id"),
        "error_analysis_report.source_model_id": reports["error_analysis_report"]["summary"].get("source_model_id"),
    }
    mismatched_model_ids = {
        key: model_id for key, model_id in model_ids.items() if model_id != spec["source_model_id"]
    }
    if mismatched_model_ids:
        checks.append(failed("source_model_ids_align_across_package", mismatched_model_ids, spec["source_model_id"]))
    else:
        checks.append(passed("source_model_ids_align_across_package", spec["source_model_id"]))

    no_peeking = {
        "threshold_selected_on": reports["metric_report"]["summary"].get("threshold_selected_on"),
        "cv_test_used": reports["cv_report"]["summary"].get("test_used_in_cv"),
        "imbalance_test_used": reports["imbalance_report"]["summary"].get("test_used_for_selection"),
        "calibration_test_used": reports["calibration_report"]["summary"].get("test_used_for_calibration"),
        "leakage_test_used": reports["leakage_report"]["summary"].get("test_used_for_model_selection"),
        "error_analysis_split": reports["error_analysis_report"]["summary"].get("analysis_split"),
    }
    if no_peeking != {
        "threshold_selected_on": "validation",
        "cv_test_used": False,
        "imbalance_test_used": False,
        "calibration_test_used": False,
        "leakage_test_used": False,
        "error_analysis_split": "test",
    }:
        checks.append(failed("final_holdout_not_used_for_selection", no_peeking, "validation selection and test-only error analysis"))
    else:
        checks.append(passed("final_holdout_not_used_for_selection", no_peeking))

    upstream_warning_counts = {
        report_id: len(report_warnings(report))
        for report_id, report in reports.items()
        if report_warnings(report)
    }
    if upstream_warning_counts:
        checks.append(
            failed(
                "upstream_warnings_propagated_to_model_card",
                upstream_warning_counts,
                "no upstream warnings",
                severity="warning",
            )
        )
    else:
        checks.append(passed("upstream_warnings_propagated_to_model_card", {}))


def validate_evidence_tables(
    reports: dict[str, dict[str, Any]],
    tables: dict[str, list[dict[str, str]]],
    checks: list[dict[str, Any]],
) -> None:
    error_summary = reports.get("error_analysis_report", {}).get("summary", {})
    expected_counts = {
        "confusion_rows": error_summary.get("row_count"),
        "slice_metrics": error_summary.get("slice_metric_row_count"),
        "small_n_warnings": error_summary.get("small_n_slice_count"),
        "hidden_failure_slices": error_summary.get("hidden_failure_slice_count"),
        "error_examples": error_summary.get("error_example_count"),
    }
    mismatches = {
        table_id: {"observed": len(tables.get(table_id, [])), "expected": expected}
        for table_id, expected in expected_counts.items()
        if expected is not None and len(tables.get(table_id, [])) != int(expected)
    }
    if mismatches:
        checks.append(failed("error_analysis_evidence_counts_match_report", mismatches, "summary counts"))
    else:
        checks.append(passed("error_analysis_evidence_counts_match_report", expected_counts))

    hidden_count = len(tables.get("hidden_failure_slices", []))
    if hidden_count:
        checks.append(
            failed(
                "segment_hidden_failures_block_production_claim",
                hidden_count,
                0,
                tables["hidden_failure_slices"][:5],
                severity="warning",
            )
        )
    else:
        checks.append(passed("segment_hidden_failures_block_production_claim", 0))

    small_n_count = len(tables.get("small_n_warnings", []))
    if small_n_count:
        checks.append(
            failed(
                "small_n_segment_claims_are_diagnostic_only",
                small_n_count,
                0,
                tables["small_n_warnings"][:5],
                severity="warning",
            )
        )
    else:
        checks.append(passed("small_n_segment_claims_are_diagnostic_only", 0))

    calibration_rows = [
        row
        for row in tables.get("calibration_metrics", [])
        if row.get("split") == "test" and row.get("probability_source") == "calibrated"
    ]
    if not calibration_rows:
        checks.append(failed("calibration_evidence_includes_test_calibrated_metrics", 0, 1))
    else:
        checks.append(passed("calibration_evidence_includes_test_calibrated_metrics", calibration_rows[0]))


def build_evidence_matrix(
    spec: dict[str, Any],
    report_paths: dict[str, Path],
    reports: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in spec["required_upstream_reports"]:
        report_id = item["id"]
        report = reports[report_id]
        summary = report.get("summary", {})
        blocking = report_blocking_errors(report)
        warnings = report_warnings(report)
        rows.append(
            {
                "evidence_id": report_id,
                "lesson": item["lesson"],
                "path": portable_path(report_paths[report_id]),
                "valid": report.get("valid") is True,
                "readiness_status": summary.get("readiness_status", ""),
                "blocking_error_count": len(blocking),
                "warning_count": len(warnings),
                "status": "fail" if blocking else ("warning" if warnings else "pass"),
                "key_summary": {
                    key: summary[key]
                    for key in (
                        "row_count",
                        "test_positive_rate",
                        "overall_precision",
                        "overall_recall",
                        "overall_error_rate",
                        "hidden_failure_slice_count",
                        "small_n_slice_count",
                        "calibrated_test_brier",
                        "calibrated_test_log_loss",
                        "test_used_for_model_selection",
                    )
                    if key in summary
                },
                "warnings": warnings,
            }
        )
    return rows


def build_risk_register(
    spec: dict[str, Any],
    reports: dict[str, dict[str, Any]],
    tables: dict[str, list[dict[str, str]]],
) -> list[dict[str, Any]]:
    error_summary = reports["error_analysis_report"]["summary"]
    calibration_summary = reports["calibration_report"]["summary"]
    return [
        {
            "risk_id": "tiny_profile_not_production_sample",
            "severity": "warning",
            "status": "disclosed_requires_larger_sample",
            "evidence": "problem_report,split_report,cv_report,calibration_report",
            "owner": "ml_analytics",
            "next_action": "collect_larger_representative_train_validation_test_sample",
        },
        {
            "risk_id": "hidden_segment_failure",
            "severity": "warning",
            "status": "blocks_production_claim",
            "evidence": f"{error_summary['hidden_failure_slice_count']} hidden failure slices",
            "owner": "product_analytics",
            "next_action": "review android organic trial_basic_ru and low score band before rollout",
        },
        {
            "risk_id": "small_n_segment_metrics",
            "severity": "warning",
            "status": "diagnostic_only",
            "evidence": f"{error_summary['small_n_slice_count']} small-n slices",
            "owner": "ml_analytics",
            "next_action": "increase holdout size before segment readiness claims",
        },
        {
            "risk_id": "calibration_tiny_bins",
            "severity": "warning",
            "status": "review_required",
            "evidence": (
                f"calibration_rows={calibration_summary['calibration_row_count']}; "
                f"test_brier={calibration_summary['calibrated_test_brier']}"
            ),
            "owner": "ml_analytics",
            "next_action": "recalibrate on larger validation data and monitor calibration drift",
        },
        {
            "risk_id": "unknown_categories_bucketed",
            "severity": "warning",
            "status": "disclosed",
            "evidence": "unknown acquisition_channel values are bucketed",
            "owner": "data_engineering",
            "next_action": "monitor unseen category rates in scoring batches",
        },
        {
            "risk_id": "no_causal_offer_effect",
            "severity": "limitation",
            "status": "out_of_scope",
            "evidence": spec["model_card_policy"]["claim_boundary"],
            "owner": "product_analytics",
            "next_action": "run experiment or causal design before claiming offer impact",
        },
        {
            "risk_id": "forbidden_features_rejected",
            "severity": "control",
            "status": "control_passed",
            "evidence": f"{len(tables.get('forbidden_feature_report', []))} forbidden candidates rejected",
            "owner": "ml_analytics",
            "next_action": "keep feature availability audit in future retrains",
        },
        {
            "risk_id": "model_artifact_security",
            "severity": "limitation",
            "status": "requires_secure_serving_review",
            "evidence": "no pickle/joblib artifact is shipped by this lesson",
            "owner": "ml_platform",
            "next_action": "review trusted serialization and serving boundary before deployment",
        },
    ]


def build_model_card_data(
    spec: dict[str, Any],
    problem_spec: dict[str, Any],
    reports: dict[str, dict[str, Any]],
    tables: dict[str, list[dict[str, str]]],
    risk_register: list[dict[str, Any]],
    decision_status: str,
) -> dict[str, Any]:
    split = reports["split_report"]["summary"]
    error = reports["error_analysis_report"]["summary"]
    calibration = reports["calibration_report"]["summary"]
    leakage = reports["leakage_report"]["summary"]
    return {
        "model_card_id": spec["model_card_id"],
        "model_details": {
            "package_id": spec["package_id"],
            "problem_id": spec["problem_id"],
            "model_id": spec["source_model_id"],
            "model_type": "sklearn Pipeline(ColumnTransformer, RandomForestClassifier)",
            "package_version": spec["package_version"],
            "generated_at": GENERATED_AT,
        },
        "intended_use": {
            "summary": spec["model_card_policy"]["intended_use"],
            "primary_users": spec["model_card_policy"]["primary_users"],
            "decision_action": problem_spec["decision_action"],
            "decision_budget": problem_spec["decision_budget"],
        },
        "out_of_scope_uses": spec["model_card_policy"]["out_of_scope_uses"],
        "training_data": {
            "split_type": problem_spec["split_policy"]["split_type"],
            "train_rows": split["rows_by_split"]["train"],
            "validation_rows": split["rows_by_split"]["validation"],
            "test_rows": split["rows_by_split"]["test"],
            "target": problem_spec["target_name"],
            "positive_class": problem_spec["positive_class"]["meaning"],
        },
        "evaluation_data": {
            "final_holdout_split": "test",
            "test_rows": error["row_count"],
            "test_positive_count": error["positive_count"],
            "test_action_count": error["action_count"],
            "test_was_used_for_selection": leakage["test_used_for_model_selection"],
        },
        "metrics": {
            "primary_rule": "rank_top_k_within_scoring_batch",
            "precision_at_budget": error["overall_precision"],
            "recall_at_budget": error["overall_recall"],
            "overall_error_rate": error["overall_error_rate"],
            "false_positive_count": error["false_positive_count"],
            "false_negative_count": error["false_negative_count"],
        },
        "calibration": {
            "method": calibration["calibration_method"],
            "calibration_split": calibration["calibration_split"],
            "test_brier_score": calibration["calibrated_test_brier"],
            "test_log_loss": calibration["calibrated_test_log_loss"],
            "test_used_for_calibration": calibration["test_used_for_calibration"],
        },
        "error_analysis": {
            "slice_metric_rows": error["slice_metric_row_count"],
            "small_n_slice_count": error["small_n_slice_count"],
            "hidden_failure_slice_count": error["hidden_failure_slice_count"],
            "hidden_failure_slices": [
                f"{row['dimension']}={row['slice_value']}"
                for row in tables.get("hidden_failure_slices", [])
            ],
        },
        "limitations": [
            row
            for row in risk_register
            if row["severity"] in {"warning", "limitation"}
        ],
        "ethical_considerations": {
            "claim_boundary": spec["model_card_policy"]["claim_boundary"],
            "automated_action_allowed": False,
            "sensitive_use_note": (
                "The score can prioritize human review, but it must not be used as an "
                "automatic account action or as a causal offer-effect statement."
            ),
        },
        "decision": {
            "status": decision_status,
            "allowed_package_claim": spec["decision_policy"]["allowed_package_claim"],
            "forbidden_claims": spec["decision_policy"]["forbidden_claims"],
            "production_requires": spec["decision_policy"]["production_requires"],
        },
        "maintenance": {
            "monitoring_needed": [
                "input schema and unknown-category rates",
                "precision/recall at offer budget",
                "calibration drift",
                "segment hidden failures",
            ],
            "next_phase": "16-tabular-ml",
        },
    }


def format_bullet_list(values: list[Any]) -> list[str]:
    return [f"- {value}" for value in values]


def model_card_markdown(card: dict[str, Any]) -> str:
    hidden = card["error_analysis"]["hidden_failure_slices"]
    limitations = [row["risk_id"] for row in card["limitations"]]
    lines = [
        f"# Model Card: {card['model_card_id']}",
        "",
        "## Model Details",
        "",
        f"- Package: {card['model_details']['package_id']}",
        f"- Model: {card['model_details']['model_id']}",
        f"- Type: {card['model_details']['model_type']}",
        f"- Generated at: {card['model_details']['generated_at']}",
        "",
        "## Intended Use",
        "",
        f"- {card['intended_use']['summary']}",
        f"- Decision action: {card['intended_use']['decision_action']}",
        f"- Offer budget: {card['intended_use']['decision_budget']['max_actions']} per scoring batch",
        "",
        "## Out-of-Scope Uses",
        "",
        *format_bullet_list(card["out_of_scope_uses"]),
        "",
        "## Training And Evaluation Data",
        "",
        f"- Train rows: {card['training_data']['train_rows']}",
        f"- Validation rows: {card['training_data']['validation_rows']}",
        f"- Test rows: {card['training_data']['test_rows']}",
        f"- Final holdout used for selection: {card['evaluation_data']['test_was_used_for_selection']}",
        "",
        "## Metrics",
        "",
        f"- Precision at budget: {card['metrics']['precision_at_budget']}",
        f"- Recall at budget: {card['metrics']['recall_at_budget']}",
        f"- Overall error rate: {card['metrics']['overall_error_rate']}",
        f"- False positives / false negatives: {card['metrics']['false_positive_count']} / {card['metrics']['false_negative_count']}",
        "",
        "## Calibration",
        "",
        f"- Method: {card['calibration']['method']}",
        f"- Test Brier score: {card['calibration']['test_brier_score']}",
        f"- Test log loss: {card['calibration']['test_log_loss']}",
        f"- Test used for calibration: {card['calibration']['test_used_for_calibration']}",
        "",
        "## Error Analysis",
        "",
        f"- Slice metric rows: {card['error_analysis']['slice_metric_rows']}",
        f"- Small-n slices: {card['error_analysis']['small_n_slice_count']}",
        f"- Hidden failure slices: {card['error_analysis']['hidden_failure_slice_count']}",
        *format_bullet_list(hidden),
        "",
        "## Limitations",
        "",
        *format_bullet_list(limitations),
        "",
        "## Ethical Considerations",
        "",
        card["ethical_considerations"]["claim_boundary"],
        card["ethical_considerations"]["sensitive_use_note"],
        "",
        "## Decision",
        "",
        f"- Status: {card['decision']['status']}",
        f"- Allowed claim: {card['decision']['allowed_package_claim']}",
        "- Production requires:",
        *format_bullet_list(card["decision"]["production_requires"]),
        "",
        "## Maintenance",
        "",
        *format_bullet_list(card["maintenance"]["monitoring_needed"]),
        "",
    ]
    return "\n".join(lines)


def decision_report_markdown(
    *,
    spec: dict[str, Any],
    report: dict[str, Any],
    risk_register: list[dict[str, Any]],
) -> str:
    warning_ids = ", ".join(report["summary"]["warnings"]) or "none"
    blocking_ids = ", ".join(report["summary"]["blocking_errors"]) or "none"
    high_risks = [
        row["risk_id"]
        for row in risk_register
        if row["status"] in {"blocks_production_claim", "review_required"}
    ]
    return "\n".join(
        [
            f"# ML Baseline Decision: {spec['package_id']}",
            "",
            f"- Status: {report['decision_status']}",
            f"- Package valid: {str(report['valid']).lower()}",
            f"- Blocking errors: {blocking_ids}",
            f"- Warnings: {warning_ids}",
            f"- Allowed package claim: {spec['decision_policy']['allowed_package_claim']}",
            "",
            "## Production Blockers",
            "",
            *format_bullet_list(high_risks),
            "",
            "## Allowed Next Actions",
            "",
            *format_bullet_list(spec["decision_policy"]["allowed_actions"]),
            "",
            "## Blocked Actions",
            "",
            *format_bullet_list(spec["decision_policy"]["blocked_actions"]),
            "",
            "## Interpretation Boundary",
            "",
            spec["model_card_policy"]["claim_boundary"],
            "This package is an offline baseline handoff, not a production deployment approval.",
            "",
        ]
    )


def build_audit_rows(checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "check_id": check["id"],
            "severity": check["severity"],
            "status": "pass" if check["valid"] else ("warning" if check["severity"] == "warning" else "fail"),
            "observed": check["observed"],
            "expected": check["expected"],
        }
        for check in checks
    ]


def risk_summary(risk_register: list[dict[str, Any]]) -> dict[str, int]:
    return dict(Counter(row["severity"] for row in risk_register))


def build_output_payloads(result: dict[str, Any], output: dict[str, str]) -> dict[str, bytes]:
    evidence_fields = [
        "evidence_id",
        "lesson",
        "path",
        "valid",
        "readiness_status",
        "blocking_error_count",
        "warning_count",
        "status",
        "key_summary",
        "warnings",
    ]
    risk_fields = ["risk_id", "severity", "status", "evidence", "owner", "next_action"]
    audit_fields = ["check_id", "severity", "status", "observed", "expected"]
    return {
        output["package_file"]: json_text(result["package"]).encode("utf-8"),
        output["report_file"]: json_text(result["report"]).encode("utf-8"),
        output["model_card_file"]: result["model_card_markdown"].encode("utf-8"),
        output["decision_report_file"]: result["decision_report"].encode("utf-8"),
        output["evidence_matrix_file"]: csv_text(result["evidence_matrix"], evidence_fields).encode("utf-8"),
        output["risk_register_file"]: csv_text(result["risk_register"], risk_fields).encode("utf-8"),
        output["audit_file"]: csv_text(result["audit_rows"], audit_fields).encode("utf-8"),
    }


def build_manifest(input_paths: dict[str, Path], output_payloads: dict[str, bytes]) -> dict[str, Any]:
    return {
        "manifest_id": "trial-churn-ml-baseline-package-manifest-v0",
        "hash_algorithm": "sha256",
        "inputs": {
            name: {
                "path": portable_path(path),
                "sha256": sha256_path(path),
                "bytes": path.stat().st_size,
            }
            for name, path in sorted(input_paths.items())
            if path.exists()
        },
        "outputs": {
            name: {"sha256": sha256_bytes(payload), "bytes": len(payload)}
            for name, payload in sorted(output_payloads.items())
        },
    }


def build_ml_baseline_package(
    *,
    package_spec_path: Path,
    problem_spec_path: Path,
    report_paths: dict[str, Path],
    table_paths: dict[str, Path],
) -> dict[str, Any]:
    spec = read_json(package_spec_path)
    problem_spec = read_json(problem_spec_path)
    checks = validate_package_spec(spec, problem_spec)
    reports = load_reports(report_paths, checks)
    tables = load_tables(table_paths, checks)

    if not blocking_checks(checks):
        validate_upstream_reports(spec, reports, checks)
        validate_evidence_tables(reports, tables, checks)

    blocking = blocking_checks(checks)
    warnings = warning_checks(checks)
    valid = not blocking
    upstream_warning_count = sum(len(report_warnings(report)) for report in reports.values())
    risk_register = build_risk_register(spec, reports, tables) if not blocking else []
    if valid:
        checks.append(
            failed(
                "model_card_requires_human_review_before_production",
                spec["decision_policy"]["valid_with_warnings_status"],
                "production_ready",
                severity="warning",
            )
        )
        warnings = warning_checks(checks)

    decision_status = "blocked"
    if valid:
        decision_status = (
            spec["decision_policy"]["valid_with_warnings_status"]
            if warnings
            else spec["decision_policy"]["allowed_package_claim"]
        )
    evidence_matrix = build_evidence_matrix(spec, report_paths, reports) if not blocking else []
    model_card = (
        build_model_card_data(spec, problem_spec, reports, tables, risk_register, decision_status)
        if valid
        else {}
    )

    summary = {
        "package_id": spec.get("package_id"),
        "model_card_id": spec.get("model_card_id"),
        "problem_id": spec.get("problem_id"),
        "source_model_id": spec.get("source_model_id"),
        "evidence_row_count": len(evidence_matrix),
        "risk_row_count": len(risk_register),
        "upstream_warning_count": upstream_warning_count,
        "small_n_slice_count": reports.get("error_analysis_report", {})
        .get("summary", {})
        .get("small_n_slice_count", 0),
        "hidden_failure_slice_count": reports.get("error_analysis_report", {})
        .get("summary", {})
        .get("hidden_failure_slice_count", 0),
        "decision_status": decision_status,
        "production_ready": False,
        "blocking_errors": blocking,
        "warnings": warnings,
        "readiness_status": "phase_15_complete_baseline_package" if valid else "blocked_before_model_card",
        "generated_at": GENERATED_AT,
    }
    report = {
        "valid": valid,
        "package_id": spec.get("package_id"),
        "model_card_id": spec.get("model_card_id"),
        "decision_status": decision_status,
        "summary": summary,
        "outputs": spec.get("output", {}),
        "risk_summary": risk_summary(risk_register),
        "checks": checks,
    }
    package = {
        "valid": valid,
        "package_id": spec.get("package_id"),
        "model_card_id": spec.get("model_card_id"),
        "problem_id": spec.get("problem_id"),
        "source_model_id": spec.get("source_model_id"),
        "decision": {
            "status": decision_status,
            "production_ready": False,
            "allowed_package_claim": spec.get("decision_policy", {}).get("allowed_package_claim"),
            "blocked_actions": spec.get("decision_policy", {}).get("blocked_actions", []),
            "production_requires": spec.get("decision_policy", {}).get("production_requires", []),
        },
        "model_card": model_card,
        "evidence_matrix": evidence_matrix,
        "risk_register": risk_register,
        "checks": checks,
        "summary": summary,
    }
    model_card_text = model_card_markdown(model_card) if valid else ""
    decision_text = (
        decision_report_markdown(spec=spec, report=report, risk_register=risk_register)
        if valid
        else ""
    )
    input_paths = {
        "package_spec": package_spec_path,
        "problem_spec": problem_spec_path,
        **{f"report:{key}": path for key, path in report_paths.items()},
        **{f"table:{key}": path for key, path in table_paths.items()},
    }
    result = {
        "package": package,
        "report": report,
        "model_card_markdown": model_card_text,
        "decision_report": decision_text,
        "evidence_matrix": evidence_matrix,
        "risk_register": risk_register,
        "audit_rows": build_audit_rows(checks),
        "input_paths": input_paths,
    }
    output_payloads = build_output_payloads(result, spec.get("output", {})) if valid else {}
    result["manifest"] = build_manifest(input_paths, output_payloads) if valid else {
        "manifest_id": "trial-churn-ml-baseline-package-manifest-v0",
        "hash_algorithm": "sha256",
        "inputs": {},
        "outputs": {},
    }
    return result


def write_outputs(result: dict[str, Any], output_dir: Path, output: dict[str, str]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    payloads = build_output_payloads(result, output)
    for filename, payload in payloads.items():
        (output_dir / filename).write_bytes(payload)
    write_json(output_dir / output["manifest_file"], result["manifest"])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an ML baseline package and model card.")
    parser.add_argument(
        "--package-spec",
        type=Path,
        default=DATA_ROOT / "ml_baseline_package_spec.json",
    )
    parser.add_argument("--problem-spec", type=Path, default=DATA_ROOT / "problem_spec.json")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--fail-on-warning", action="store_true")
    for report_id, default_path in DEFAULT_REPORT_PATHS.items():
        parser.add_argument(
            f"--{report_id.replace('_', '-')}",
            type=Path,
            default=default_path,
        )
    for table_id, default_path in DEFAULT_TABLE_PATHS.items():
        parser.add_argument(
            f"--{table_id.replace('_', '-')}",
            type=Path,
            default=default_path,
        )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report_paths = {
        report_id: getattr(args, report_id)
        for report_id in DEFAULT_REPORT_PATHS
    }
    table_paths = {
        table_id: getattr(args, table_id)
        for table_id in DEFAULT_TABLE_PATHS
    }
    try:
        result = build_ml_baseline_package(
            package_spec_path=args.package_spec,
            problem_spec_path=args.problem_spec,
            report_paths=report_paths,
            table_paths=table_paths,
        )
        spec = read_json(args.package_spec)
        if args.output_dir is not None and result["report"]["valid"]:
            write_outputs(result, args.output_dir, spec["output"])
        elif args.output_dir is not None:
            write_json(args.output_dir / spec["output"]["report_file"], result["report"])
        print(json.dumps(result["report"]["summary"], ensure_ascii=False, indent=2))
        if result["report"]["summary"]["blocking_errors"]:
            return 1
        if args.fail_on_warning and result["report"]["summary"]["warnings"]:
            return 1
        return 0
    except (MLBaselinePackageError, OSError, json.JSONDecodeError) as error:
        summary = {
            "package_id": None,
            "blocking_errors": ["ml_baseline_package_runtime_error"],
            "warnings": [],
            "readiness_status": "blocked_by_runtime_error",
            "error": str(error),
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
