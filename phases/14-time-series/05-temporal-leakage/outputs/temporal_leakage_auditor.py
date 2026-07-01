from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


REQUIRED_SERIES_COLUMNS = {
    "metric_id",
    "segment_id",
    "observed_date",
    "frequency",
    "value",
    "include_in_training",
}
REQUIRED_FEATURE_COLUMNS = {"metric_id", "segment_id", "observed_date", "include_in_training"}
REQUIRED_FEATURE_AUDIT_COLUMNS = {
    "segment_id",
    "feature_date",
    "feature_name",
    "latest_source_date_used",
    "valid",
}
REQUIRED_CALENDAR_COLUMNS = {"date", "known_before_date"}
REQUIRED_REVISION_COLUMNS = {
    "metric_id",
    "segment_id",
    "observed_date",
    "revision_number",
    "revised_at",
}
REQUIRED_SCENARIO_FIELDS = {
    "forecast_id",
    "target_metric",
    "target_segments",
    "timezone",
    "frequency",
    "expected_start",
    "complete_through",
    "forecast_origin",
    "horizon_days",
}
REQUIRED_SPEC_FIELDS = {
    "leakage_audit_id",
    "target_metric",
    "target_segments",
    "timezone",
    "frequency",
    "expected_start",
    "complete_through",
    "forecast_origin",
    "horizon_days",
    "split_plan",
    "revision_policy",
    "known_future_feature_policy",
    "forbidden_availability_types",
    "candidate_features",
}
REQUIRED_SPLIT_FIELDS = {
    "split_id",
    "split_type",
    "training_start",
    "training_end",
    "first_forecast_date",
    "embargo_dates",
    "horizon_end",
}
REQUIRED_FEATURE_FIELDS = {
    "name",
    "source",
    "availability_type",
    "selected",
    "required_evidence",
}


class TemporalLeakageError(ValueError):
    """Raised when temporal leakage audit inputs cannot be interpreted."""


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open(encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        return list(reader), list(reader.fieldnames or [])


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TemporalLeakageError(f"{path.name} must contain a JSON object")
    return value


def parse_date(value: str, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise TemporalLeakageError(f"{field} must be ISO date: {value}") from error


def parse_timestamp(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise TemporalLeakageError(f"{field} must be ISO timestamp: {value}") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise TemporalLeakageError(f"{field} must be timezone-aware: {value}")
    return parsed


def parse_bool(value: str | bool, field: str) -> bool:
    if isinstance(value, bool):
        return value
    normalized = value.strip().lower()
    if normalized not in {"true", "false"}:
        raise TemporalLeakageError(f"{field} must be true or false: {value}")
    return normalized == "true"


def daterange(start: date, end: date) -> list[date]:
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


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


def normalize_spec(spec: dict[str, Any], scenario: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    checks: list[dict[str, Any]] = []
    missing_spec = sorted(REQUIRED_SPEC_FIELDS - set(spec))
    if missing_spec:
        checks.append(failed("leakage_spec_required_fields", missing_spec, "all required temporal leakage fields"))
        return checks, None
    checks.append(passed("leakage_spec_required_fields", len(REQUIRED_SPEC_FIELDS)))

    missing_scenario = sorted(REQUIRED_SCENARIO_FIELDS - set(scenario))
    if missing_scenario:
        checks.append(failed("scenario_required_fields", missing_scenario, "all required scenario fields"))
        return checks, None
    checks.append(passed("scenario_required_fields", len(REQUIRED_SCENARIO_FIELDS)))

    segments = spec.get("target_segments")
    if not isinstance(segments, list) or not segments or not all(isinstance(item, str) and item for item in segments):
        checks.append(failed("target_segments_declared", segments, "non-empty list of segment ids"))
        return checks, None
    checks.append(passed("target_segments_declared", segments))

    try:
        timezone = ZoneInfo(str(spec["timezone"]))
    except ZoneInfoNotFoundError:
        checks.append(failed("timezone_valid", spec["timezone"], "IANA timezone"))
        return checks, None
    checks.append(passed("timezone_valid", spec["timezone"]))

    split_plan = spec.get("split_plan")
    if not isinstance(split_plan, dict):
        checks.append(failed("split_plan_declared", split_plan, "object with cutoff contract"))
        return checks, None
    missing_split = sorted(REQUIRED_SPLIT_FIELDS - set(split_plan))
    if missing_split:
        checks.append(failed("split_plan_required_fields", missing_split, "all required split fields"))
        return checks, None
    checks.append(passed("split_plan_required_fields", len(REQUIRED_SPLIT_FIELDS)))

    candidates = spec.get("candidate_features")
    if not isinstance(candidates, list) or not candidates:
        checks.append(failed("candidate_features_declared", candidates, "non-empty feature catalog"))
        return checks, None
    feature_errors = []
    feature_names = []
    for index, feature in enumerate(candidates):
        if not isinstance(feature, dict):
            feature_errors.append({"feature_index": index, "error": "feature must be an object"})
            continue
        missing_feature = sorted(REQUIRED_FEATURE_FIELDS - set(feature))
        if missing_feature:
            feature_errors.append({"feature_index": index, "missing": missing_feature})
        feature_names.append(str(feature.get("name", "")))
    duplicate_feature_names = [name for name, count in Counter(feature_names).items() if name and count > 1]
    for name in duplicate_feature_names:
        feature_errors.append({"feature": name, "error": "duplicate feature name"})
    if feature_errors:
        checks.append(failed("candidate_features_valid", len(feature_errors), "valid feature catalog entries", feature_errors))
    else:
        checks.append(passed("candidate_features_valid", len(candidates)))

    forbidden_types = spec.get("forbidden_availability_types")
    if not isinstance(forbidden_types, list) or not forbidden_types:
        checks.append(failed("forbidden_availability_types_declared", forbidden_types, "non-empty forbidden availability list"))
        return checks, None
    checks.append(passed("forbidden_availability_types_declared", forbidden_types))

    alignment_errors = []
    for field in ("target_metric", "target_segments", "timezone", "frequency", "expected_start", "complete_through", "forecast_origin", "horizon_days"):
        if spec[field] != scenario[field]:
            alignment_errors.append({"field": field, "spec": spec[field], "scenario": scenario[field]})
    if alignment_errors:
        checks.append(failed("scenario_and_leakage_spec_align", len(alignment_errors), "matching forecast setup fields", alignment_errors))
    else:
        checks.append(passed("scenario_and_leakage_spec_align", 8))

    if spec["revision_policy"] != "exclude_revisions_after_forecast_origin":
        checks.append(
            failed(
                "revision_policy_excludes_after_origin",
                spec["revision_policy"],
                "exclude_revisions_after_forecast_origin",
            )
        )
    else:
        checks.append(passed("revision_policy_excludes_after_origin", spec["revision_policy"]))

    if spec["known_future_feature_policy"] != "require_known_before_forecast_origin":
        checks.append(
            failed(
                "known_future_feature_policy_supported",
                spec["known_future_feature_policy"],
                "require_known_before_forecast_origin",
            )
        )
    else:
        checks.append(passed("known_future_feature_policy_supported", spec["known_future_feature_policy"]))

    forecast_origin = parse_timestamp(str(spec["forecast_origin"]), "forecast_origin")
    normalized = {
        "leakage_audit_id": str(spec["leakage_audit_id"]),
        "forecast_id": str(scenario["forecast_id"]),
        "target_metric": str(spec["target_metric"]),
        "target_segments": [str(segment) for segment in segments],
        "timezone": timezone,
        "timezone_name": str(spec["timezone"]),
        "frequency": str(spec["frequency"]),
        "expected_start": parse_date(str(spec["expected_start"]), "expected_start"),
        "complete_through": parse_date(str(spec["complete_through"]), "complete_through"),
        "forecast_origin": forecast_origin,
        "forecast_origin_date": forecast_origin.astimezone(timezone).date(),
        "horizon_days": int(spec["horizon_days"]),
        "split_plan": {
            "split_id": str(split_plan["split_id"]),
            "split_type": str(split_plan["split_type"]),
            "training_start": parse_date(str(split_plan["training_start"]), "training_start"),
            "training_end": parse_date(str(split_plan["training_end"]), "training_end"),
            "first_forecast_date": parse_date(str(split_plan["first_forecast_date"]), "first_forecast_date"),
            "embargo_dates": [parse_date(str(day), "embargo_dates") for day in split_plan["embargo_dates"]],
            "horizon_end": parse_date(str(split_plan["horizon_end"]), "horizon_end"),
        },
        "revision_policy": str(spec["revision_policy"]),
        "forbidden_availability_types": {str(item) for item in forbidden_types},
        "candidate_features": candidates,
    }
    return checks, normalized


def build_temporal_leakage_package(
    *,
    series_path: Path,
    features_path: Path,
    feature_audit_path: Path,
    calendar_path: Path,
    revisions_path: Path,
    scenario_path: Path,
    spec_path: Path,
) -> dict[str, Any]:
    series_rows, series_columns = read_csv(series_path)
    feature_rows, feature_columns = read_csv(features_path)
    feature_audit_rows, feature_audit_columns = read_csv(feature_audit_path)
    calendar_rows, calendar_columns = read_csv(calendar_path)
    revision_rows, revision_columns = read_csv(revisions_path)
    scenario = read_json(scenario_path)
    spec = read_json(spec_path)

    spec_checks, normalized = normalize_spec(spec, scenario)
    checks = list(spec_checks)
    missing_series_columns = sorted(REQUIRED_SERIES_COLUMNS - set(series_columns))
    missing_feature_columns = sorted(REQUIRED_FEATURE_COLUMNS - set(feature_columns))
    missing_feature_audit_columns = sorted(REQUIRED_FEATURE_AUDIT_COLUMNS - set(feature_audit_columns))
    missing_calendar_columns = sorted(REQUIRED_CALENDAR_COLUMNS - set(calendar_columns))
    missing_revision_columns = sorted(REQUIRED_REVISION_COLUMNS - set(revision_columns))

    checks.append(
        failed("series_columns_present", missing_series_columns, "all required source columns")
        if missing_series_columns
        else passed("series_columns_present", len(series_columns))
    )
    checks.append(
        failed("feature_columns_present", missing_feature_columns, "all required feature columns")
        if missing_feature_columns
        else passed("feature_columns_present", len(feature_columns))
    )
    checks.append(
        failed("feature_audit_columns_present", missing_feature_audit_columns, "all required feature audit columns")
        if missing_feature_audit_columns
        else passed("feature_audit_columns_present", len(feature_audit_columns))
    )
    checks.append(
        failed("calendar_columns_present", missing_calendar_columns, "all required calendar columns")
        if missing_calendar_columns
        else passed("calendar_columns_present", len(calendar_columns))
    )
    checks.append(
        failed("revision_columns_present", missing_revision_columns, "all required revision columns")
        if missing_revision_columns
        else passed("revision_columns_present", len(revision_columns))
    )

    if normalized is None or any(
        [missing_series_columns, missing_feature_columns, missing_feature_audit_columns, missing_calendar_columns, missing_revision_columns]
    ):
        report = build_report(spec, scenario, checks, {}, [])
        return {"report": report, "cutoff_contract": {}, "forbidden_feature_rows": []}

    parsed_series, series_parse_checks = parse_series_rows(series_rows, normalized)
    parsed_features, feature_parse_checks = parse_feature_rows(feature_rows, normalized)
    parsed_feature_audit, feature_audit_parse_checks = parse_feature_audit_rows(feature_audit_rows)
    parsed_calendar, calendar_parse_checks = parse_calendar_rows(calendar_rows)
    parsed_revisions, revision_parse_checks = parse_revision_rows(revision_rows)
    checks.extend(series_parse_checks)
    checks.extend(feature_parse_checks)
    checks.extend(feature_audit_parse_checks)
    checks.extend(calendar_parse_checks)
    checks.extend(revision_parse_checks)

    cutoff_contract, cutoff_checks = audit_cutoff_contract(parsed_series, parsed_features, normalized)
    checks.extend(cutoff_checks)

    forbidden_feature_rows, feature_checks = audit_feature_catalog(
        feature_columns=feature_columns,
        parsed_feature_audit=parsed_feature_audit,
        parsed_calendar=parsed_calendar,
        spec=normalized,
    )
    checks.extend(feature_checks)

    revision_checks = audit_revisions(parsed_revisions, normalized)
    checks.extend(revision_checks)

    cutoff_contract["selected_features"] = [
        row["feature_name"]
        for row in forbidden_feature_rows
        if row["selected"] == "true" and row["decision"] == "allow"
    ]
    cutoff_contract["rejected_feature_candidates"] = sum(1 for row in forbidden_feature_rows if row["decision"] == "reject")
    report = build_report(spec, scenario, checks, cutoff_contract, forbidden_feature_rows)
    return {
        "report": report,
        "cutoff_contract": cutoff_contract,
        "forbidden_feature_rows": forbidden_feature_rows,
    }


def parse_series_rows(rows: list[dict[str, str]], spec: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    parsed: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    target_segments = set(spec["target_segments"])
    for index, row in enumerate(rows, start=2):
        if row.get("metric_id") != spec["target_metric"] or row.get("segment_id") not in target_segments:
            continue
        try:
            parsed.append(
                {
                    **row,
                    "_row": index,
                    "_date": parse_date(row.get("observed_date", ""), "observed_date"),
                    "_include_in_training": parse_bool(row.get("include_in_training", ""), "include_in_training"),
                }
            )
        except TemporalLeakageError as error:
            errors.append({"row": index, "error": str(error)})
    if errors:
        return parsed, [failed("series_rows_parse", len(errors), "valid dates and training flags", errors[:10])]
    return parsed, [passed("series_rows_parse", len(parsed))]


def parse_feature_rows(rows: list[dict[str, str]], spec: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    parsed: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    target_segments = set(spec["target_segments"])
    for index, row in enumerate(rows, start=2):
        if row.get("metric_id") != spec["target_metric"] or row.get("segment_id") not in target_segments:
            continue
        try:
            parsed.append(
                {
                    **row,
                    "_row": index,
                    "_date": parse_date(row.get("observed_date", ""), "observed_date"),
                    "_include_in_training": parse_bool(row.get("include_in_training", ""), "include_in_training"),
                }
            )
        except TemporalLeakageError as error:
            errors.append({"row": index, "error": str(error)})
    if errors:
        return parsed, [failed("feature_rows_parse", len(errors), "valid dates and training flags", errors[:10])]
    return parsed, [passed("feature_rows_parse", len(parsed))]


def parse_feature_audit_rows(rows: list[dict[str, str]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    parsed: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=2):
        try:
            feature_date = parse_date(row.get("feature_date", ""), "feature_date")
            latest_value = row.get("latest_source_date_used", "")
            latest_date = parse_date(latest_value, "latest_source_date_used") if latest_value else None
            parsed.append(
                {
                    **row,
                    "_row": index,
                    "_feature_date": feature_date,
                    "_latest_source_date": latest_date,
                    "_valid": parse_bool(row.get("valid", ""), "valid"),
                }
            )
        except TemporalLeakageError as error:
            errors.append({"row": index, "feature_name": row.get("feature_name"), "error": str(error)})
    if errors:
        return parsed, [failed("feature_audit_rows_parse", len(errors), "valid feature audit rows", errors[:10])]
    return parsed, [passed("feature_audit_rows_parse", len(parsed))]


def parse_calendar_rows(rows: list[dict[str, str]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    parsed: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=2):
        try:
            parsed.append(
                {
                    **row,
                    "_row": index,
                    "_date": parse_date(row.get("date", ""), "date"),
                    "_known_before_date": parse_date(row.get("known_before_date", ""), "known_before_date"),
                }
            )
        except TemporalLeakageError as error:
            errors.append({"row": index, "error": str(error)})
    if errors:
        return parsed, [failed("calendar_rows_parse", len(errors), "valid calendar rows", errors[:10])]
    return parsed, [passed("calendar_rows_parse", len(parsed))]


def parse_revision_rows(rows: list[dict[str, str]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    parsed: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=2):
        try:
            parsed.append(
                {
                    **row,
                    "_row": index,
                    "_observed_date": parse_date(row.get("observed_date", ""), "observed_date"),
                    "_revised_at": parse_timestamp(row.get("revised_at", ""), "revised_at"),
                }
            )
        except TemporalLeakageError as error:
            errors.append({"row": index, "error": str(error)})
    if errors:
        return parsed, [failed("revision_rows_parse", len(errors), "valid revision rows", errors[:10])]
    return parsed, [passed("revision_rows_parse", len(parsed))]


def audit_cutoff_contract(
    series_rows: list[dict[str, Any]],
    feature_rows: list[dict[str, Any]],
    spec: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    checks: list[dict[str, Any]] = []
    split = spec["split_plan"]
    expected_horizon_end = split["first_forecast_date"] + timedelta(days=spec["horizon_days"] - 1)
    if split["split_type"] != "time_ordered_cutoff":
        checks.append(failed("split_plan_is_time_ordered", split["split_type"], "time_ordered_cutoff"))
    else:
        checks.append(passed("split_plan_is_time_ordered", split["split_type"]))

    if split["training_end"] != spec["complete_through"]:
        checks.append(failed("training_end_matches_complete_through", split["training_end"].isoformat(), spec["complete_through"].isoformat()))
    else:
        checks.append(passed("training_end_matches_complete_through", split["training_end"].isoformat()))

    if split["first_forecast_date"] <= split["training_end"]:
        checks.append(
            failed(
                "forecast_horizon_starts_after_training",
                split["first_forecast_date"].isoformat(),
                f"> {split['training_end'].isoformat()}",
            )
        )
    else:
        checks.append(passed("forecast_horizon_starts_after_training", split["first_forecast_date"].isoformat()))

    if split["horizon_end"] != expected_horizon_end:
        checks.append(
            failed(
                "forecast_horizon_length_matches_scenario",
                split["horizon_end"].isoformat(),
                expected_horizon_end.isoformat(),
            )
        )
    else:
        checks.append(passed("forecast_horizon_length_matches_scenario", spec["horizon_days"]))

    training_after_cutoff = [
        {"segment_id": row["segment_id"], "observed_date": row["_date"].isoformat()}
        for row in series_rows
        if row["_include_in_training"] and row["_date"] > split["training_end"]
    ]
    if training_after_cutoff:
        checks.append(
            failed(
                "training_rows_end_at_complete_through",
                len(training_after_cutoff),
                "0 training rows after training_end",
                training_after_cutoff[:10],
            )
        )
    else:
        checks.append(passed("training_rows_end_at_complete_through", split["training_end"].isoformat()))

    feature_training_after_cutoff = [
        {"segment_id": row["segment_id"], "observed_date": row["_date"].isoformat()}
        for row in feature_rows
        if row["_include_in_training"] and row["_date"] > split["training_end"]
    ]
    if feature_training_after_cutoff:
        checks.append(
            failed(
                "feature_training_rows_end_at_complete_through",
                len(feature_training_after_cutoff),
                "0 feature training rows after training_end",
                feature_training_after_cutoff[:10],
            )
        )
    else:
        checks.append(passed("feature_training_rows_end_at_complete_through", split["training_end"].isoformat()))

    embargo_training_rows = [
        {"segment_id": row["segment_id"], "observed_date": row["_date"].isoformat()}
        for row in series_rows
        if row["_include_in_training"] and row["_date"] in set(split["embargo_dates"])
    ]
    if embargo_training_rows:
        checks.append(
            failed(
                "embargo_dates_are_not_training_rows",
                len(embargo_training_rows),
                "embargo dates excluded from training",
                embargo_training_rows[:10],
            )
        )
    else:
        checks.append(passed("embargo_dates_are_not_training_rows", [day.isoformat() for day in split["embargo_dates"]]))

    contract = {
        "leakage_audit_id": spec["leakage_audit_id"],
        "forecast_id": spec["forecast_id"],
        "target_metric": spec["target_metric"],
        "target_segments": spec["target_segments"],
        "timezone": spec["timezone_name"],
        "frequency": spec["frequency"],
        "forecast_origin": spec["forecast_origin"].isoformat(),
        "training_start": split["training_start"].isoformat(),
        "training_end": split["training_end"].isoformat(),
        "first_forecast_date": split["first_forecast_date"].isoformat(),
        "horizon_end": split["horizon_end"].isoformat(),
        "horizon_days": spec["horizon_days"],
        "embargo_dates": [day.isoformat() for day in split["embargo_dates"]],
        "split_type": split["split_type"],
        "revision_policy": spec["revision_policy"],
    }
    return contract, checks


def audit_feature_catalog(
    *,
    feature_columns: list[str],
    parsed_feature_audit: list[dict[str, Any]],
    parsed_calendar: list[dict[str, Any]],
    spec: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    checks: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    selected_forbidden = []
    selected_missing_evidence = []
    known_future_failures = []
    window_audit_failures = []
    feature_names_in_audit = {row["feature_name"] for row in parsed_feature_audit}
    calendar_columns = set(parsed_calendar[0].keys()) if parsed_calendar else set()

    for feature in spec["candidate_features"]:
        name = str(feature["name"])
        availability_type = str(feature["availability_type"])
        selected = bool(feature["selected"])
        source = str(feature["source"])
        decision = "reject" if availability_type in spec["forbidden_availability_types"] else "allow"
        reason = "safe at cutoff" if decision == "allow" else f"forbidden availability: {availability_type}"
        evidence_status = "not_selected"
        if availability_type == "past_observation":
            if name not in feature_columns:
                evidence_status = "missing_feature_column"
                if selected:
                    selected_missing_evidence.append({"feature_name": name, "reason": evidence_status})
            elif name not in feature_names_in_audit:
                evidence_status = "missing_leakage_audit"
                if selected:
                    selected_missing_evidence.append({"feature_name": name, "reason": evidence_status})
            else:
                feature_audit_failures = [
                    row
                    for row in parsed_feature_audit
                    if row["feature_name"] == name
                    and (not row["_valid"] or (row["_latest_source_date"] is not None and row["_latest_source_date"] >= row["_feature_date"]))
                ]
                if feature_audit_failures:
                    evidence_status = "leakage_audit_failed"
                    if selected:
                        window_audit_failures.extend(feature_audit_failures[:10])
                else:
                    evidence_status = "past_only_audit_passed"
        elif availability_type == "known_future_calendar":
            if name not in calendar_columns:
                evidence_status = "missing_calendar_column"
                if selected:
                    selected_missing_evidence.append({"feature_name": name, "reason": evidence_status})
            else:
                failures = known_future_calendar_failures(name, parsed_calendar, spec)
                if failures:
                    evidence_status = "known_after_origin"
                    if selected:
                        known_future_failures.extend(failures[:10])
                else:
                    evidence_status = "known_before_origin"

        if selected and decision == "reject":
            selected_forbidden.append({"feature_name": name, "availability_type": availability_type, "source": source})

        rows.append(
            {
                "feature_name": name,
                "source": source,
                "availability_type": availability_type,
                "selected": str(selected).lower(),
                "decision": decision,
                "reason": reason,
                "evidence_status": evidence_status,
            }
        )

    if selected_forbidden:
        checks.append(
            failed(
                "selected_features_do_not_use_forbidden_availability",
                len(selected_forbidden),
                "no selected feature has forbidden availability",
                selected_forbidden,
            )
        )
    else:
        checks.append(passed("selected_features_do_not_use_forbidden_availability", sum(1 for row in rows if row["selected"] == "true")))

    if selected_missing_evidence:
        checks.append(
            failed(
                "selected_features_are_available_at_cutoff",
                len(selected_missing_evidence),
                "selected features have source columns and audit evidence",
                selected_missing_evidence,
            )
        )
    else:
        checks.append(passed("selected_features_are_available_at_cutoff", sum(1 for row in rows if row["selected"] == "true")))

    if known_future_failures:
        checks.append(
            failed(
                "known_future_features_known_before_origin",
                len(known_future_failures),
                "known future feature values are known before forecast origin",
                known_future_failures,
            )
        )
    else:
        checks.append(passed("known_future_features_known_before_origin", "selected calendar features"))

    if window_audit_failures:
        checks.append(
            failed(
                "window_features_have_past_only_audit",
                len(window_audit_failures),
                "selected window features use only source dates before feature date",
                [
                    {
                        "segment_id": row["segment_id"],
                        "feature_date": row["feature_date"],
                        "feature_name": row["feature_name"],
                        "latest_source_date_used": row["latest_source_date_used"],
                    }
                    for row in window_audit_failures
                ],
            )
        )
    else:
        checks.append(passed("window_features_have_past_only_audit", "selected window features"))

    rejected = [row for row in rows if row["decision"] == "reject"]
    if rejected:
        checks.append(
            failed(
                "forbidden_feature_candidates_rejected",
                len(rejected),
                "forbidden candidates are visible and rejected",
                rejected,
                severity="warning",
            )
        )
    else:
        checks.append(passed("forbidden_feature_candidates_rejected", 0))

    return rows, checks


def known_future_calendar_failures(
    feature_name: str,
    calendar_rows: list[dict[str, Any]],
    spec: dict[str, Any],
) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    split = spec["split_plan"]
    origin_date = spec["forecast_origin_date"]
    for row in calendar_rows:
        day = row["_date"]
        if day < split["first_forecast_date"] or day > split["horizon_end"]:
            continue
        value = row.get(feature_name, "")
        is_active_boolean = value.strip().lower() == "true" if isinstance(value, str) else False
        if feature_name in {"day_of_week", "week_start", "date"}:
            continue
        if is_active_boolean and row["_known_before_date"] > origin_date:
            failures.append(
                {
                    "feature_name": feature_name,
                    "date": day.isoformat(),
                    "known_before_date": row["_known_before_date"].isoformat(),
                    "forecast_origin_date": origin_date.isoformat(),
                }
            )
    return failures


def audit_revisions(revision_rows: list[dict[str, Any]], spec: dict[str, Any]) -> list[dict[str, Any]]:
    after_origin = [
        {
            "metric_id": row["metric_id"],
            "segment_id": row["segment_id"],
            "observed_date": row["_observed_date"].isoformat(),
            "revision_number": row["revision_number"],
            "revised_at": row["_revised_at"].isoformat(),
        }
        for row in revision_rows
        if row.get("metric_id") == spec["target_metric"]
        and row.get("segment_id") in set(spec["target_segments"])
        and row["_observed_date"] <= spec["split_plan"]["training_end"]
        and row["_revised_at"] > spec["forecast_origin"]
    ]
    if after_origin:
        return [
            failed(
                "revisions_after_origin_are_excluded",
                len(after_origin),
                "revisions published after forecast origin are excluded from training snapshot",
                after_origin,
                severity="warning",
            )
        ]
    return [passed("revisions_after_origin_are_excluded", 0)]


def build_report(
    spec: dict[str, Any],
    scenario: dict[str, Any],
    checks: list[dict[str, Any]],
    cutoff_contract: dict[str, Any],
    forbidden_feature_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    error_failures = [check for check in checks if not check["valid"] and check["severity"] == "error"]
    warning_failures = [check for check in checks if not check["valid"] and check["severity"] == "warning"]
    selected = [row for row in forbidden_feature_rows if row.get("selected") == "true"]
    rejected_selected = [row for row in selected if row.get("decision") == "reject"]
    return {
        "audit_id": "temporal-leakage-audit",
        "leakage_audit_id": spec.get("leakage_audit_id"),
        "forecast_id": scenario.get("forecast_id"),
        "valid": not error_failures,
        "warning_count": len(warning_failures),
        "error_count": len(error_failures),
        "checks": checks,
        "cutoff_contract": cutoff_contract,
        "outputs": {
            "feature_candidates": len(forbidden_feature_rows),
            "selected_features": len(selected),
            "rejected_feature_candidates": sum(1 for row in forbidden_feature_rows if row.get("decision") == "reject"),
            "rejected_selected_features": len(rejected_selected),
        },
        "summary": {
            "checks_total": len(checks),
            "checks_failed": len(error_failures) + len(warning_failures),
            "blocking_errors": [check["id"] for check in error_failures],
            "warnings": [check["id"] for check in warning_failures],
        },
    }


def write_package(output_dir: Path, package: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "cutoff_contract.json").write_text(
        json.dumps(package["cutoff_contract"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_csv(
        output_dir / "forbidden_feature_report.csv",
        package["forbidden_feature_rows"],
        ["feature_name", "source", "availability_type", "selected", "decision", "reason", "evidence_status"],
    )
    (output_dir / "temporal_leakage_report.json").write_text(
        json.dumps(package["report"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit temporal leakage for a forecast cutoff and feature catalog.")
    parser.add_argument("--series", type=Path, required=True)
    parser.add_argument("--features", type=Path, required=True)
    parser.add_argument("--feature-audit", type=Path, required=True)
    parser.add_argument("--calendar", type=Path, required=True)
    parser.add_argument("--revisions", type=Path, required=True)
    parser.add_argument("--scenario", type=Path, required=True)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("outputs"))
    parser.add_argument("--fail-on-warning", action="store_true")
    args = parser.parse_args()

    package = build_temporal_leakage_package(
        series_path=args.series,
        features_path=args.features,
        feature_audit_path=args.feature_audit,
        calendar_path=args.calendar,
        revisions_path=args.revisions,
        scenario_path=args.scenario,
        spec_path=args.spec,
    )
    write_package(args.output_dir, package)
    report = package["report"]
    print(
        json.dumps(
            {
                "valid": report["valid"],
                "warnings": report["summary"]["warnings"],
                "selected_features": report["outputs"]["selected_features"],
                "rejected_feature_candidates": report["outputs"]["rejected_feature_candidates"],
            },
            ensure_ascii=False,
        )
    )
    if not report["valid"] or (args.fail_on_warning and report["warning_count"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
