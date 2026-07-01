from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any


REQUIRED_SPEC_FIELDS = {
    "package_id",
    "forecast_id",
    "target_metric",
    "target_segments",
    "forecast_origin",
    "horizon_days",
    "primary_model_id",
    "primary_interval_method",
    "required_reports",
    "required_tables",
    "package_sections",
    "anomaly_policy",
    "decision_policy",
    "quality_gates",
}
REQUIRED_ANOMALY_LABELS = [
    "data_quality",
    "calendar_expected",
    "model_misspecification",
    "product_signal_candidate",
    "inconclusive",
]
REQUIRED_METRIC_COLUMNS = {
    "metric_id",
    "segment_id",
    "observed_date",
    "value",
    "is_complete_period",
    "revision_number",
    "source_status",
}
REQUIRED_CALENDAR_COLUMNS = {
    "date",
    "is_holiday",
    "holiday_name",
    "campaign_active",
    "release_active",
    "known_before_date",
}
REQUIRED_REVISION_COLUMNS = {
    "metric_id",
    "segment_id",
    "observed_date",
    "revision_number",
    "previous_value",
    "revised_value",
    "revised_at",
    "revision_reason",
}
REQUIRED_INTERVAL_FORECAST_COLUMNS = {
    "forecast_id",
    "metric_id",
    "segment_id",
    "model_id",
    "forecast_date",
    "horizon_step",
    "method_id",
    "decision_role",
    "point_forecast",
    "lower_bound",
    "upper_bound",
    "uncertainty_statement",
}
REQUIRED_INTERVAL_COVERAGE_COLUMNS = {
    "aggregation_level",
    "method_id",
    "model_id",
    "segment_id",
    "horizon_step",
    "empirical_coverage",
    "coverage_status",
}
REPORT_NAMES = [
    "time_index_report",
    "resampling_report",
    "window_feature_report",
    "seasonality_report",
    "temporal_leakage_report",
    "baseline_report",
    "model_report",
    "backtest_report",
    "metric_report",
    "interval_report",
]
OUTPUT_FILENAMES = [
    "anomaly_flags.csv",
    "quality_gate_summary.csv",
    "anomaly_policy.json",
    "forecast_package_report.json",
    "decision_report.md",
]


class ForecastPackageError(ValueError):
    """Raised when the forecast package inputs cannot be interpreted."""


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ForecastPackageError(f"{path.name} must contain a JSON object")
    return value


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open(encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        return list(reader), list(reader.fieldnames or [])


def csv_text(rows: list[dict[str, Any]], fieldnames: list[str]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(csv_text(rows, fieldnames), encoding="utf-8")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_bool(value: str | bool, field: str) -> bool:
    if isinstance(value, bool):
        return value
    normalized = value.strip().lower()
    if normalized not in {"true", "false"}:
        raise ForecastPackageError(f"{field} must be true or false: {value}")
    return normalized == "true"


def parse_date(value: str, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ForecastPackageError(f"{field} must be ISO date: {value}") from error


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


def has_blocking_errors(checks: list[dict[str, Any]]) -> bool:
    return any(not check["valid"] and check["severity"] == "error" for check in checks)


def warning_ids(report: dict[str, Any]) -> list[str]:
    return list(report.get("summary", {}).get("warnings", []))


def blocking_ids(report: dict[str, Any]) -> list[str]:
    return list(report.get("summary", {}).get("blocking_errors", []))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_path(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def normalize_spec_and_reports(
    spec: dict[str, Any],
    scenario: dict[str, Any],
    reports: dict[str, dict[str, Any]],
    metric_leaderboard_rows: list[dict[str, str]],
    interval_forecast_rows: list[dict[str, str]],
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    checks: list[dict[str, Any]] = []
    missing_spec = sorted(REQUIRED_SPEC_FIELDS - set(spec))
    if missing_spec:
        checks.append(failed("forecast_package_spec_required_fields", missing_spec, "all package spec fields"))
        return checks, None
    checks.append(passed("forecast_package_spec_required_fields", len(REQUIRED_SPEC_FIELDS)))

    labels = spec.get("anomaly_policy", {}).get("labels")
    if labels != REQUIRED_ANOMALY_LABELS:
        checks.append(failed("anomaly_policy_contains_all_labels", labels, REQUIRED_ANOMALY_LABELS))
    else:
        checks.append(passed("anomaly_policy_contains_all_labels", labels))

    expected_report_names = [
        "time_index_audit",
        "resampling_report",
        "window_feature_report",
        "seasonality_report",
        "temporal_leakage_report",
        "baseline_report",
        "model_report",
        "backtest_report",
        "metric_report",
        "interval_report",
    ]
    if spec["required_reports"] != expected_report_names:
        checks.append(failed("required_upstream_files_exist", spec["required_reports"], expected_report_names))
    else:
        checks.append(passed("required_upstream_files_exist", len(reports)))

    invalid_reports = [name for name, report in reports.items() if report.get("valid") is not True]
    if invalid_reports:
        checks.append(failed("upstream_reports_are_valid", invalid_reports, "all upstream reports valid"))
    else:
        checks.append(passed("upstream_reports_are_valid", len(reports)))

    upstream_warnings = {name: warning_ids(report) for name, report in reports.items() if warning_ids(report)}
    if upstream_warnings:
        checks.append(
            failed(
                "upstream_warnings_propagated_to_decision",
                upstream_warnings,
                "no upstream warnings for production release",
                severity="warning",
            )
        )
    else:
        checks.append(passed("upstream_warnings_propagated_to_decision", []))

    forecast_ids = {
        "spec": spec.get("forecast_id"),
        "scenario": scenario.get("forecast_id"),
        **{name: report.get("forecast_id") for name, report in reports.items() if report.get("forecast_id") is not None},
    }
    if len(set(forecast_ids.values())) != 1:
        checks.append(failed("forecast_ids_align", forecast_ids, spec["forecast_id"]))
    else:
        checks.append(passed("forecast_ids_align", spec["forecast_id"]))

    top_model = reports["metric_report"].get("outputs", {}).get("top_model_id")
    leaderboard_top = metric_leaderboard_rows[0].get("model_id") if metric_leaderboard_rows else None
    if spec["primary_model_id"] != top_model or top_model != leaderboard_top:
        checks.append(
            failed(
                "primary_model_matches_metric_leaderboard",
                {"spec": spec["primary_model_id"], "metric_report": top_model, "leaderboard": leaderboard_top},
                "same primary model",
            )
        )
    else:
        checks.append(passed("primary_model_matches_metric_leaderboard", top_model))

    interval_method = reports["interval_report"].get("outputs", {}).get("primary_interval_method")
    if spec["primary_interval_method"] != interval_method:
        checks.append(failed("primary_interval_method_matches_interval_report", spec["primary_interval_method"], interval_method))
    else:
        checks.append(passed("primary_interval_method_matches_interval_report", interval_method))

    primary_rows = [
        row
        for row in interval_forecast_rows
        if row.get("model_id") == spec["primary_model_id"]
        and row.get("method_id") == spec["primary_interval_method"]
        and row.get("metric_id") == spec["target_metric"]
    ]
    expected_primary = len(spec["target_segments"]) * int(spec["horizon_days"])
    if len(primary_rows) != expected_primary or any(not row.get("uncertainty_statement") for row in primary_rows):
        checks.append(failed("primary_interval_forecasts_exist", len(primary_rows), expected_primary))
    else:
        checks.append(passed("primary_interval_forecasts_exist", len(primary_rows)))

    if spec["decision_policy"].get("point_forecast_requires_prediction_interval") is not True:
        checks.append(failed("point_forecast_requires_prediction_interval", spec["decision_policy"].get("point_forecast_requires_prediction_interval"), True))
    else:
        checks.append(passed("point_forecast_requires_prediction_interval", True))

    if has_blocking_errors(checks):
        return checks, None
    return checks, {
        "upstream_warnings": upstream_warnings,
        "primary_rows": primary_rows,
        "complete_through": parse_date(scenario["complete_through"], "scenario.complete_through"),
    }


def validate_table_columns(fields: list[str], required: set[str], check_id: str) -> dict[str, Any]:
    missing = sorted(required - set(fields))
    if missing:
        return failed(check_id, missing, "required columns")
    return passed(check_id, len(fields))


def calendar_context(calendar_row: dict[str, str]) -> tuple[bool, str]:
    parts: list[str] = []
    if parse_bool(calendar_row["is_holiday"], "is_holiday"):
        parts.append(f"holiday:{calendar_row.get('holiday_name') or 'unnamed'}")
    if parse_bool(calendar_row["campaign_active"], "campaign_active"):
        parts.append("campaign_active")
    if parse_bool(calendar_row["release_active"], "release_active"):
        parts.append("release_active")
    return bool(parts), ",".join(parts)


def anomaly_row(
    *,
    case_id: str,
    label: str,
    gate: str,
    metric_id: str,
    segment_id: str,
    event_date: str,
    severity: str,
    evidence: str,
    recommended_action: str,
) -> dict[str, str]:
    return {
        "case_id": case_id,
        "label": label,
        "gate": gate,
        "metric_id": metric_id,
        "segment_id": segment_id,
        "event_date": event_date,
        "severity": severity,
        "evidence": evidence,
        "recommended_action": recommended_action,
    }


def build_anomaly_flags(
    spec: dict[str, Any],
    context: dict[str, Any],
    metric_rows: list[dict[str, str]],
    calendar_rows: list[dict[str, str]],
    revision_rows: list[dict[str, str]],
    interval_forecast_rows: list[dict[str, str]],
    interval_coverage_rows: list[dict[str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    checks: list[dict[str, Any]] = []
    flags: list[dict[str, str]] = []
    calendar_by_date = {row["date"]: row for row in calendar_rows}
    data_quality_statuses = set(spec["anomaly_policy"]["data_quality_statuses"])

    for row in metric_rows:
        if row["metric_id"] != spec["target_metric"] or row["segment_id"] not in spec["target_segments"]:
            continue
        incomplete = not parse_bool(row["is_complete_period"], "is_complete_period")
        status_problem = row["source_status"] in data_quality_statuses
        if incomplete or status_problem:
            flags.append(
                anomaly_row(
                    case_id=f"dq-source-{row['segment_id']}-{row['observed_date']}",
                    label="data_quality",
                    gate="data_quality",
                    metric_id=row["metric_id"],
                    segment_id=row["segment_id"],
                    event_date=row["observed_date"],
                    severity="warning",
                    evidence=f"source_status={row['source_status']}; is_complete_period={row['is_complete_period']}",
                    recommended_action="exclude_from_alerting_until_period_closes",
                )
            )

    for row in revision_rows:
        if row["metric_id"] != spec["target_metric"] or row["segment_id"] not in spec["target_segments"]:
            continue
        flags.append(
            anomaly_row(
                case_id=f"dq-revision-{row['segment_id']}-{row['observed_date']}",
                label="data_quality",
                gate="data_quality",
                metric_id=row["metric_id"],
                segment_id=row["segment_id"],
                event_date=row["observed_date"],
                severity="warning",
                evidence=f"revision_number={row['revision_number']}; reason={row['revision_reason']}",
                recommended_action="rebuild_history_before_interpreting_residual",
            )
        )

    for row in metric_rows:
        if row["metric_id"] != spec["target_metric"] or row["segment_id"] not in spec["target_segments"]:
            continue
        calendar_row = calendar_by_date.get(row["observed_date"])
        if not calendar_row:
            continue
        has_context, evidence = calendar_context(calendar_row)
        if has_context:
            flags.append(
                anomaly_row(
                    case_id=f"calendar-{row['segment_id']}-{row['observed_date']}",
                    label="calendar_expected",
                    gate="calendar_context",
                    metric_id=row["metric_id"],
                    segment_id=row["segment_id"],
                    event_date=row["observed_date"],
                    severity="info",
                    evidence=evidence,
                    recommended_action="annotate_forecast_residual_before_business_alert",
                )
            )

    for row in interval_coverage_rows:
        if row.get("method_id") != "model_based_normal" or row.get("coverage_status") != "diagnostic_undercoverage":
            continue
        flags.append(
            anomaly_row(
                case_id=f"model-misspec-{row['model_id']}-{row['aggregation_level']}-{row['segment_id'] or 'all'}-{row['horizon_step'] or 'all'}",
                label="model_misspecification",
                gate="model_diagnostics",
                metric_id=spec["target_metric"],
                segment_id=row["segment_id"] or "*",
                event_date="backtest",
                severity="warning",
                evidence=f"method=model_based_normal; empirical_coverage={row['empirical_coverage']}",
                recommended_action="do_not_use_model_based_normal_as_anomaly_threshold",
            )
        )

    for row in interval_forecast_rows:
        if row["model_id"] != spec["primary_model_id"] or row["method_id"] != spec["primary_interval_method"]:
            continue
        forecast_date = parse_date(row["forecast_date"], "forecast_date")
        calendar_row = calendar_by_date.get(row["forecast_date"])
        if forecast_date <= context["complete_through"] or not calendar_row:
            continue
        has_context, evidence = calendar_context(calendar_row)
        if has_context:
            flags.append(
                anomaly_row(
                    case_id=f"future-context-{row['segment_id']}-{row['forecast_date']}",
                    label="inconclusive",
                    gate="business_review",
                    metric_id=row["metric_id"],
                    segment_id=row["segment_id"],
                    event_date=row["forecast_date"],
                    severity="info",
                    evidence=f"future_interval_with_known_context={evidence}",
                    recommended_action="wait_for_actual_and_quality_gates_before_alerting",
                )
            )

    duplicate_ids = [case_id for case_id, count in Counter(row["case_id"] for row in flags).items() if count > 1]
    if duplicate_ids:
        checks.append(failed("anomaly_case_ids_unique", duplicate_ids[:10], "unique case ids"))
    else:
        checks.append(passed("anomaly_case_ids_unique", len(flags)))

    data_quality_product = [row["case_id"] for row in flags if row["gate"] == "data_quality" and row["label"] == "product_signal_candidate"]
    if data_quality_product:
        checks.append(failed("data_quality_cases_not_product_signals", data_quality_product[:10], "no data-quality product signals"))
    else:
        checks.append(passed("data_quality_cases_not_product_signals", "data-quality cases are separated"))

    calendar_product = [row["case_id"] for row in flags if row["gate"] == "calendar_context" and row["label"] == "product_signal_candidate"]
    if calendar_product:
        checks.append(failed("calendar_context_cases_not_product_signals", calendar_product[:10], "no calendar product signals"))
    else:
        checks.append(passed("calendar_context_cases_not_product_signals", "calendar cases are separated"))

    misspec_count = sum(1 for row in flags if row["label"] == "model_misspecification")
    if misspec_count == 0:
        checks.append(failed("model_based_undercoverage_flagged_as_model_misspecification", 0, "at least one model misspecification flag"))
    else:
        checks.append(passed("model_based_undercoverage_flagged_as_model_misspecification", misspec_count))

    labels_in_flags = Counter(row["label"] for row in flags)
    if labels_in_flags.get("product_signal_candidate", 0) != 0:
        checks.append(failed("no_unreviewed_product_signal_candidate", labels_in_flags["product_signal_candidate"], 0))
    else:
        checks.append(passed("no_unreviewed_product_signal_candidate", 0))

    return checks, sorted(flags, key=lambda row: (row["label"], row["event_date"], row["segment_id"], row["case_id"]))


def build_decision_report(spec: dict[str, Any], report: dict[str, Any], anomaly_rows: list[dict[str, str]]) -> str:
    counts = Counter(row["label"] for row in anomaly_rows)
    warnings = ", ".join(report["summary"]["warnings"]) or "none"
    blocking = ", ".join(report["summary"]["blocking_errors"]) or "none"
    return "\n".join(
        [
            f"# Forecast package decision: {spec['package_id']}",
            "",
            f"- Status: {report['decision_status']}",
            f"- Forecast: {spec['forecast_id']} / {spec['target_metric']}",
            f"- Primary model: {spec['primary_model_id']}",
            f"- Primary interval method: {spec['primary_interval_method']}",
            f"- Package valid: {str(report['valid']).lower()}",
            f"- Blocking errors: {blocking}",
            f"- Warnings: {warnings}",
            "",
            "## Anomaly triage",
            "",
            f"- data_quality: {counts.get('data_quality', 0)}",
            f"- calendar_expected: {counts.get('calendar_expected', 0)}",
            f"- model_misspecification: {counts.get('model_misspecification', 0)}",
            f"- product_signal_candidate: {counts.get('product_signal_candidate', 0)}",
            f"- inconclusive: {counts.get('inconclusive', 0)}",
            "",
            "## Interpretation boundary",
            "",
            "This package can describe unusual observations relative to declared forecasts, intervals, data quality gates, and known calendar context.",
            "It does not make a causal claim and it is not a production SLA release on the tiny profile.",
            "",
        ]
    )


def quality_gate_rows(checks: list[dict[str, Any]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for check in checks:
        status = "pass" if check["valid"] else ("warning" if check["severity"] == "warning" else "fail")
        rows.append(
            {
                "check_id": check["id"],
                "severity": check["severity"],
                "status": status,
                "observed": json.dumps(check["observed"], ensure_ascii=False, sort_keys=True),
                "expected": json.dumps(check["expected"], ensure_ascii=False, sort_keys=True),
            }
        )
    return rows


def build_manifest(input_paths: dict[str, Path], output_payloads: dict[str, bytes]) -> dict[str, Any]:
    return {
        "manifest_id": "active-subscriptions-forecast-package-manifest",
        "hash_algorithm": "sha256",
        "inputs": {
            name: {"path": str(path), "sha256": sha256_path(path), "bytes": path.stat().st_size}
            for name, path in sorted(input_paths.items())
        },
        "outputs": {
            name: {"sha256": sha256_bytes(payload), "bytes": len(payload)}
            for name, payload in sorted(output_payloads.items())
        },
    }


def build_forecast_package(
    *,
    spec_path: Path,
    scenario_path: Path,
    metric_observations_path: Path,
    calendar_path: Path,
    data_revisions_path: Path,
    metric_leaderboard_path: Path,
    interval_forecasts_path: Path,
    interval_coverage_path: Path,
    report_paths: dict[str, Path],
) -> dict[str, Any]:
    spec = read_json(spec_path)
    scenario = read_json(scenario_path)
    reports = {name: read_json(path) for name, path in report_paths.items()}
    metric_rows, metric_fields = read_csv(metric_observations_path)
    calendar_rows, calendar_fields = read_csv(calendar_path)
    revision_rows, revision_fields = read_csv(data_revisions_path)
    metric_leaderboard_rows, metric_leaderboard_fields = read_csv(metric_leaderboard_path)
    interval_forecast_rows, interval_forecast_fields = read_csv(interval_forecasts_path)
    interval_coverage_rows, interval_coverage_fields = read_csv(interval_coverage_path)

    checks: list[dict[str, Any]] = []
    checks.append(validate_table_columns(metric_fields, REQUIRED_METRIC_COLUMNS, "metric_observations_required_columns"))
    checks.append(validate_table_columns(calendar_fields, REQUIRED_CALENDAR_COLUMNS, "calendar_required_columns"))
    checks.append(validate_table_columns(revision_fields, REQUIRED_REVISION_COLUMNS, "data_revisions_required_columns"))
    checks.append(validate_table_columns(interval_forecast_fields, REQUIRED_INTERVAL_FORECAST_COLUMNS, "interval_forecasts_required_columns"))
    checks.append(validate_table_columns(interval_coverage_fields, REQUIRED_INTERVAL_COVERAGE_COLUMNS, "interval_coverage_required_columns"))
    checks.append(validate_table_columns(metric_leaderboard_fields, {"model_id", "rank"}, "metric_leaderboard_required_columns"))

    spec_checks, context = normalize_spec_and_reports(spec, scenario, reports, metric_leaderboard_rows, interval_forecast_rows)
    checks.extend(spec_checks)
    anomaly_rows: list[dict[str, str]] = []
    if context is not None and not has_blocking_errors(checks):
        anomaly_checks, anomaly_rows = build_anomaly_flags(
            spec,
            context,
            metric_rows,
            calendar_rows,
            revision_rows,
            interval_forecast_rows,
            interval_coverage_rows,
        )
        checks.extend(anomaly_checks)

    warning_list = [check["id"] for check in checks if not check["valid"] and check["severity"] == "warning"]
    blocking_list = [check["id"] for check in checks if not check["valid"] and check["severity"] == "error"]
    label_counts = Counter(row["label"] for row in anomaly_rows)
    report = {
        "audit_id": "time-series-forecast-package-report",
        "package_id": spec.get("package_id"),
        "forecast_id": spec.get("forecast_id"),
        "valid": not blocking_list,
        "warning_count": len(warning_list),
        "error_count": len(blocking_list),
        "decision_status": spec.get("decision_policy", {}).get("tiny_profile_status"),
        "checks": checks,
        "outputs": {
            "anomaly_rows": len(anomaly_rows),
            "quality_gate_rows": len(checks),
            "labels": {label: label_counts.get(label, 0) for label in REQUIRED_ANOMALY_LABELS},
            "primary_model_id": spec.get("primary_model_id"),
            "primary_interval_method": spec.get("primary_interval_method"),
        },
        "summary": {
            "checks_total": len(checks),
            "checks_failed": len(warning_list) + len(blocking_list),
            "blocking_errors": blocking_list,
            "warnings": warning_list,
        },
    }
    decision_report = build_decision_report(spec, report, anomaly_rows)
    if "caused by" in decision_report.lower():
        checks.append(failed("decision_report_has_no_causal_claim", "caused by", "no causal wording"))
    else:
        checks.append(passed("decision_report_has_no_causal_claim", "no causal claim"))
    report["checks"] = checks
    warning_list = [check["id"] for check in checks if not check["valid"] and check["severity"] == "warning"]
    blocking_list = [check["id"] for check in checks if not check["valid"] and check["severity"] == "error"]
    report["warning_count"] = len(warning_list)
    report["error_count"] = len(blocking_list)
    report["valid"] = not blocking_list
    report["outputs"]["quality_gate_rows"] = len(checks)
    report["summary"] = {
        "checks_total": len(checks),
        "checks_failed": len(warning_list) + len(blocking_list),
        "blocking_errors": blocking_list,
        "warnings": warning_list,
    }
    gate_rows = quality_gate_rows(checks)
    anomaly_policy = {
        "package_id": spec.get("package_id"),
        "forecast_id": spec.get("forecast_id"),
        "labels": spec.get("anomaly_policy", {}).get("labels"),
        "gate_order": spec.get("anomaly_policy", {}).get("gate_order"),
        "product_signal_requires": spec.get("anomaly_policy", {}).get("product_signal_requires"),
        "no_causal_claim_without_experiment": spec.get("anomaly_policy", {}).get("no_causal_claim_without_experiment"),
    }
    output_payloads = {
        "anomaly_flags.csv": csv_text(anomaly_rows, ANOMALY_FIELDNAMES).encode("utf-8"),
        "quality_gate_summary.csv": csv_text(gate_rows, QUALITY_GATE_FIELDNAMES).encode("utf-8"),
        "anomaly_policy.json": (json.dumps(anomaly_policy, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        "forecast_package_report.json": (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        "decision_report.md": decision_report.encode("utf-8"),
    }
    input_paths = {
        "spec": spec_path,
        "scenario": scenario_path,
        "metric_observations": metric_observations_path,
        "calendar": calendar_path,
        "data_revisions": data_revisions_path,
        "metric_leaderboard": metric_leaderboard_path,
        "interval_forecasts": interval_forecasts_path,
        "interval_coverage": interval_coverage_path,
        **report_paths,
    }
    manifest = build_manifest(input_paths, output_payloads)
    if set(manifest["outputs"]) != set(OUTPUT_FILENAMES):
        checks.append(failed("checksum_manifest_covers_inputs_and_outputs", sorted(manifest["outputs"]), OUTPUT_FILENAMES))
    else:
        checks.append(passed("checksum_manifest_covers_inputs_and_outputs", len(manifest["inputs"]) + len(manifest["outputs"])))
    report["checks"] = checks
    warning_list = [check["id"] for check in checks if not check["valid"] and check["severity"] == "warning"]
    blocking_list = [check["id"] for check in checks if not check["valid"] and check["severity"] == "error"]
    report["warning_count"] = len(warning_list)
    report["error_count"] = len(blocking_list)
    report["valid"] = not blocking_list
    report["outputs"]["quality_gate_rows"] = len(checks)
    report["summary"] = {
        "checks_total": len(checks),
        "checks_failed": len(warning_list) + len(blocking_list),
        "blocking_errors": blocking_list,
        "warnings": warning_list,
    }
    gate_rows = quality_gate_rows(checks)
    output_payloads = {
        "anomaly_flags.csv": csv_text(anomaly_rows, ANOMALY_FIELDNAMES).encode("utf-8"),
        "quality_gate_summary.csv": csv_text(gate_rows, QUALITY_GATE_FIELDNAMES).encode("utf-8"),
        "anomaly_policy.json": (json.dumps(anomaly_policy, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        "forecast_package_report.json": (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        "decision_report.md": build_decision_report(spec, report, anomaly_rows).encode("utf-8"),
    }
    manifest = build_manifest(input_paths, output_payloads)
    return {
        "report": report,
        "anomaly_rows": anomaly_rows,
        "quality_gate_rows": quality_gate_rows(checks),
        "anomaly_policy": anomaly_policy,
        "decision_report": build_decision_report(spec, report, anomaly_rows),
        "manifest": manifest,
    }


ANOMALY_FIELDNAMES = [
    "case_id",
    "label",
    "gate",
    "metric_id",
    "segment_id",
    "event_date",
    "severity",
    "evidence",
    "recommended_action",
]
QUALITY_GATE_FIELDNAMES = ["check_id", "severity", "status", "observed", "expected"]


def write_package(package: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / "anomaly_flags.csv", package["anomaly_rows"], ANOMALY_FIELDNAMES)
    write_csv(output_dir / "quality_gate_summary.csv", package["quality_gate_rows"], QUALITY_GATE_FIELDNAMES)
    write_json(output_dir / "anomaly_policy.json", package["anomaly_policy"])
    write_json(output_dir / "forecast_package_report.json", package["report"])
    (output_dir / "decision_report.md").write_text(package["decision_report"], encoding="utf-8")
    write_json(output_dir / "forecast_package_manifest.json", package["manifest"])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an integrated time-series forecast package")
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--scenario", type=Path, required=True)
    parser.add_argument("--metric-observations", type=Path, required=True)
    parser.add_argument("--calendar", type=Path, required=True)
    parser.add_argument("--data-revisions", type=Path, required=True)
    parser.add_argument("--metric-leaderboard", type=Path, required=True)
    parser.add_argument("--interval-forecasts", type=Path, required=True)
    parser.add_argument("--interval-coverage", type=Path, required=True)
    for report_name in REPORT_NAMES:
        parser.add_argument(f"--{report_name.replace('_', '-')}", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--fail-on-warning", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report_paths = {name: getattr(args, name) for name in REPORT_NAMES}
    package = build_forecast_package(
        spec_path=args.spec,
        scenario_path=args.scenario,
        metric_observations_path=args.metric_observations,
        calendar_path=args.calendar,
        data_revisions_path=args.data_revisions,
        metric_leaderboard_path=args.metric_leaderboard,
        interval_forecasts_path=args.interval_forecasts,
        interval_coverage_path=args.interval_coverage,
        report_paths=report_paths,
    )
    write_package(package, args.output_dir)
    print(json.dumps({"valid": package["report"]["valid"], **package["report"]["summary"]}, ensure_ascii=False))
    if not package["report"]["valid"] or (args.fail_on_warning and package["report"]["warning_count"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
