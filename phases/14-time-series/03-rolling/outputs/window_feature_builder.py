from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


REQUIRED_SOURCE_COLUMNS = {
    "metric_id",
    "segment_id",
    "observed_date",
    "frequency",
    "delta_active",
    "value",
    "is_complete_period",
    "include_in_training",
}
REQUIRED_SCENARIO_FIELDS = {
    "forecast_id",
    "target_metric",
    "target_segments",
    "timezone",
    "frequency",
    "complete_through",
    "forecast_origin",
}
REQUIRED_SPEC_FIELDS = {
    "feature_set_id",
    "source_table",
    "target_metric",
    "target_segments",
    "time_column",
    "value_column",
    "delta_column",
    "complete_flag_column",
    "timezone",
    "frequency",
    "expected_start",
    "complete_through",
    "forecast_origin",
    "feature_date_policy",
    "warmup_policy",
    "partial_period_policy",
    "rules",
}
SUPPORTED_RULE_KINDS = {"lag", "rolling_mean", "expanding_mean"}


class WindowFeatureError(ValueError):
    """Raised when window feature inputs cannot be interpreted."""


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
        raise WindowFeatureError(f"{path.name} must contain a JSON object")
    return value


def parse_date(value: str, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise WindowFeatureError(f"{field} must be ISO date: {value}") from error


def parse_timestamp(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise WindowFeatureError(f"{field} must be ISO timestamp: {value}") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise WindowFeatureError(f"{field} must be timezone-aware: {value}")
    return parsed


def parse_bool(value: str, field: str) -> bool:
    normalized = value.strip().lower()
    if normalized not in {"true", "false"}:
        raise WindowFeatureError(f"{field} must be true or false: {value}")
    return normalized == "true"


def parse_int(value: str, field: str) -> int:
    try:
        return int(value)
    except ValueError as error:
        raise WindowFeatureError(f"{field} must be an integer: {value}") from error


def parse_number(value: str, field: str) -> float:
    try:
        return float(value)
    except ValueError as error:
        raise WindowFeatureError(f"{field} must be numeric: {value}") from error


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


def format_feature_value(value: float | int | None) -> str:
    if value is None:
        return ""
    if isinstance(value, int) or float(value).is_integer():
        return str(int(value))
    return f"{value:.6f}".rstrip("0").rstrip(".")


def normalize_spec(spec: dict[str, Any], scenario: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    checks: list[dict[str, Any]] = []
    missing_spec = sorted(REQUIRED_SPEC_FIELDS - set(spec))
    if missing_spec:
        checks.append(failed("window_spec_required_fields", missing_spec, "all required window feature fields"))
        return checks, None
    checks.append(passed("window_spec_required_fields", len(REQUIRED_SPEC_FIELDS)))

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

    rules = spec.get("rules")
    if not isinstance(rules, list) or not rules:
        checks.append(failed("feature_rules_declared", rules, "non-empty list of feature rules"))
        return checks, None
    checks.append(passed("feature_rules_declared", len(rules)))

    alignment_errors = []
    for field in ("target_metric", "target_segments", "timezone", "frequency", "complete_through", "forecast_origin"):
        if spec[field] != scenario[field]:
            alignment_errors.append({"field": field, "spec": spec[field], "scenario": scenario[field]})
    if alignment_errors:
        checks.append(failed("scenario_and_window_spec_align", len(alignment_errors), "matching forecast setup fields", alignment_errors))
    else:
        checks.append(passed("scenario_and_window_spec_align", 6))

    policy_errors = []
    expected_policies = {
        "feature_date_policy": "features_use_strictly_past_observations",
        "warmup_policy": "emit_rows_but_exclude_from_training",
        "partial_period_policy": "emit_rows_but_exclude_from_training",
    }
    for field, expected in expected_policies.items():
        if spec[field] != expected:
            policy_errors.append({"field": field, "observed": spec[field], "expected": expected})
    if policy_errors:
        checks.append(failed("window_policies_supported", len(policy_errors), "supported leakage-safe policies", policy_errors))
    else:
        checks.append(passed("window_policies_supported", expected_policies))

    rule_errors = validate_rules(rules)
    if rule_errors:
        checks.append(failed("feature_rules_are_past_only", len(rule_errors), "lag >= 1 and center=false for all required rules", rule_errors))
    else:
        checks.append(passed("feature_rules_are_past_only", len(rules)))

    normalized = {
        "feature_set_id": str(spec["feature_set_id"]),
        "forecast_id": str(scenario["forecast_id"]),
        "target_metric": str(spec["target_metric"]),
        "target_segments": [str(segment) for segment in segments],
        "time_column": str(spec["time_column"]),
        "value_column": str(spec["value_column"]),
        "delta_column": str(spec["delta_column"]),
        "complete_flag_column": str(spec["complete_flag_column"]),
        "timezone": timezone,
        "timezone_name": str(spec["timezone"]),
        "frequency": str(spec["frequency"]),
        "expected_start": parse_date(str(spec["expected_start"]), "expected_start"),
        "complete_through": parse_date(str(spec["complete_through"]), "complete_through"),
        "forecast_origin": parse_timestamp(str(spec["forecast_origin"]), "forecast_origin"),
        "rules": rules,
    }
    return checks, normalized


def validate_rules(rules: list[Any]) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    names: list[str] = []
    for index, rule in enumerate(rules):
        if not isinstance(rule, dict):
            errors.append({"rule_index": index, "error": "rule must be an object"})
            continue
        name = str(rule.get("name", ""))
        names.append(name)
        kind = rule.get("kind")
        lag = int(rule.get("lag", 0))
        if not name:
            errors.append({"rule_index": index, "field": "name", "error": "required"})
        if kind not in SUPPORTED_RULE_KINDS:
            errors.append({"rule": name, "field": "kind", "observed": kind, "expected": sorted(SUPPORTED_RULE_KINDS)})
        if lag < 1:
            errors.append({"rule": name, "field": "lag", "observed": lag, "expected": ">= 1"})
        if rule.get("center", False) is True:
            errors.append({"rule": name, "field": "center", "observed": True, "expected": False})
        if kind == "rolling_mean":
            window = int(rule.get("window", 0))
            min_periods = int(rule.get("min_periods", 0))
            if window < 1:
                errors.append({"rule": name, "field": "window", "observed": window, "expected": ">= 1"})
            if min_periods < 1 or min_periods > window:
                errors.append({"rule": name, "field": "min_periods", "observed": min_periods, "expected": "1..window"})
        if kind == "expanding_mean":
            min_periods = int(rule.get("min_periods", 0))
            if min_periods < 1:
                errors.append({"rule": name, "field": "min_periods", "observed": min_periods, "expected": ">= 1"})
    duplicate_names = [name for name, count in Counter(names).items() if name and count > 1]
    for name in duplicate_names:
        errors.append({"rule": name, "field": "name", "error": "duplicate"})
    return errors


def build_window_feature_package(
    *,
    series_path: Path,
    scenario_path: Path,
    spec_path: Path,
) -> dict[str, Any]:
    source_rows, source_columns = read_csv(series_path)
    scenario = read_json(scenario_path)
    spec = read_json(spec_path)

    spec_checks, normalized = normalize_spec(spec, scenario)
    checks = list(spec_checks)

    missing_source_columns = sorted(REQUIRED_SOURCE_COLUMNS - set(source_columns))
    if missing_source_columns:
        checks.append(failed("source_columns_present", missing_source_columns, "all required daily source columns"))
    else:
        checks.append(passed("source_columns_present", len(source_columns)))

    if normalized is None or missing_source_columns:
        report = build_report(spec, scenario, checks, [], [])
        return {"report": report, "feature_rows": [], "leakage_audit_rows": []}

    rule_input_columns = sorted(
        {
            str(rule.get("input_column", ""))
            for rule in normalized["rules"]
            if isinstance(rule, dict) and rule.get("input_column")
        }
    )
    missing_rule_columns = sorted(set(rule_input_columns) - set(source_columns))
    if missing_rule_columns:
        checks.append(failed("feature_input_columns_present", missing_rule_columns, "all feature input columns exist in source"))
    else:
        checks.append(passed("feature_input_columns_present", rule_input_columns))

    parsed_rows, parse_checks = parse_source_rows(source_rows, normalized)
    checks.extend(parse_checks)

    keys = [(row["segment_id"], row["_date"]) for row in parsed_rows]
    duplicates = [{"segment_id": segment, "observed_date": day.isoformat()} for (segment, day), count in Counter(keys).items() if count > 1]
    if duplicates:
        checks.append(failed("source_segment_date_unique", len(duplicates), "0 duplicate segment/date keys", duplicates[:10]))
    else:
        checks.append(passed("source_segment_date_unique", len(parsed_rows)))

    missing_complete = find_missing_complete_dates(parsed_rows, normalized)
    if missing_complete:
        checks.append(
            failed(
                "complete_history_has_no_missing_dates",
                len(missing_complete),
                "every target segment has every complete date",
                missing_complete,
            )
        )
    else:
        expected_points = len(daterange(normalized["expected_start"], normalized["complete_through"])) * len(normalized["target_segments"])
        checks.append(passed("complete_history_has_no_missing_dates", expected_points))

    if missing_rule_columns or duplicates or missing_complete:
        report = build_report(spec, scenario, checks, [], [])
        return {"report": report, "feature_rows": [], "leakage_audit_rows": []}

    feature_rows, leakage_audit_rows = build_feature_rows(parsed_rows, normalized)
    leakage_failures = [
        row
        for row in leakage_audit_rows
        if row["valid"] == "false"
    ]
    if leakage_failures:
        checks.append(
            failed(
                "feature_source_dates_precede_feature_date",
                len(leakage_failures),
                "every feature uses only dates before the feature date",
                leakage_failures[:10],
            )
        )
    else:
        checks.append(passed("feature_source_dates_precede_feature_date", len(leakage_audit_rows)))

    warmup_rows = [row for row in feature_rows if row["source_is_complete"] == "true" and row["feature_complete"] == "false"]
    if warmup_rows:
        checks.append(
            failed(
                "warmup_rows_excluded_from_training",
                len(warmup_rows),
                "rows without enough history are emitted but not used for training",
                warmup_rows[:10],
                severity="warning",
            )
        )
    else:
        checks.append(passed("warmup_rows_excluded_from_training", 0))

    partial_rows = [row for row in feature_rows if row["source_is_complete"] == "false"]
    if partial_rows:
        checks.append(
            failed(
                "partial_source_rows_excluded_from_training",
                len(partial_rows),
                "partial source rows are emitted but not used for training",
                partial_rows[:10],
                severity="warning",
            )
        )
    else:
        checks.append(passed("partial_source_rows_excluded_from_training", 0))

    report = build_report(spec, scenario, checks, feature_rows, leakage_audit_rows)
    return {"report": report, "feature_rows": feature_rows, "leakage_audit_rows": leakage_audit_rows}


def parse_source_rows(rows: list[dict[str, str]], spec: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    parsed: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    parse_errors: list[dict[str, Any]] = []
    target_segments = set(spec["target_segments"])
    for index, row in enumerate(rows, start=2):
        if row.get("metric_id") != spec["target_metric"] or row.get("segment_id") not in target_segments:
            continue
        try:
            observed_date = parse_date(row.get(spec["time_column"], ""), spec["time_column"])
            include_flag = parse_bool(row.get(spec["complete_flag_column"], ""), spec["complete_flag_column"])
            parsed.append(
                {
                    **row,
                    "_row": index,
                    "_date": observed_date,
                    "_include_flag": include_flag,
                    "_value": parse_number(row.get(spec["value_column"], ""), spec["value_column"]),
                    "_delta": parse_number(row.get(spec["delta_column"], ""), spec["delta_column"]),
                    "_is_complete_period": parse_bool(row.get("is_complete_period", ""), "is_complete_period"),
                }
            )
        except WindowFeatureError as error:
            parse_errors.append({"row": index, "error": str(error), "segment_id": row.get("segment_id")})
    if parse_errors:
        checks.append(failed("source_rows_parse", len(parse_errors), "valid dates, booleans, and numeric inputs", parse_errors[:10]))
    else:
        checks.append(passed("source_rows_parse", len(parsed)))
    return parsed, checks


def find_missing_complete_dates(rows: list[dict[str, Any]], spec: dict[str, Any]) -> list[dict[str, Any]]:
    by_segment: dict[str, set[date]] = defaultdict(set)
    for row in rows:
        if row["_date"] <= spec["complete_through"] and row["_include_flag"]:
            by_segment[row["segment_id"]].add(row["_date"])
    expected = set(daterange(spec["expected_start"], spec["complete_through"]))
    missing: list[dict[str, Any]] = []
    for segment_id in spec["target_segments"]:
        segment_missing = sorted(expected - by_segment.get(segment_id, set()))
        if segment_missing:
            missing.append({"segment_id": segment_id, "missing_dates": [day.isoformat() for day in segment_missing]})
    return missing


def build_feature_rows(
    rows: list[dict[str, Any]],
    spec: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows_by_segment_date: dict[tuple[str, date], dict[str, Any]] = {
        (row["segment_id"], row["_date"]): row
        for row in rows
    }
    sorted_rows = sorted(rows, key=lambda row: (row["segment_id"], row["_date"]))
    feature_rows: list[dict[str, Any]] = []
    leakage_audit_rows: list[dict[str, Any]] = []
    rule_names = [rule["name"] for rule in spec["rules"]]

    for row in sorted_rows:
        feature_date = row["_date"]
        segment_id = row["segment_id"]
        history_points = sum(
            1
            for candidate in rows
            if candidate["segment_id"] == segment_id and candidate["_date"] < feature_date and candidate["_include_flag"]
        )
        feature_values: dict[str, str] = {}
        all_required_present = True
        for rule in spec["rules"]:
            value, source_dates = evaluate_rule(rule, segment_id, feature_date, rows_by_segment_date)
            feature_values[rule["name"]] = format_feature_value(value)
            if rule.get("required", True) and value is None:
                all_required_present = False
            latest_source_date = max(source_dates).isoformat() if source_dates else ""
            valid_source_dates = all(source_date < feature_date for source_date in source_dates)
            leakage_audit_rows.append(
                {
                    "feature_set_id": spec["feature_set_id"],
                    "segment_id": segment_id,
                    "feature_date": feature_date.isoformat(),
                    "feature_name": rule["name"],
                    "source_dates_used": ",".join(day.isoformat() for day in source_dates),
                    "latest_source_date_used": latest_source_date,
                    "valid": str(valid_source_dates).lower(),
                }
            )

        source_complete = row["_include_flag"]
        include_in_training = source_complete and all_required_present
        feature_rows.append(
            {
                "metric_id": row["metric_id"],
                "segment_id": segment_id,
                "observed_date": feature_date.isoformat(),
                "frequency": row["frequency"],
                "value": format_feature_value(row["_value"]),
                "delta_active": format_feature_value(row["_delta"]),
                **{name: feature_values[name] for name in rule_names},
                "history_points_before": history_points,
                "source_is_complete": str(source_complete).lower(),
                "feature_complete": str(all_required_present).lower(),
                "include_in_training": str(include_in_training).lower(),
            }
        )
    return feature_rows, leakage_audit_rows


def evaluate_rule(
    rule: dict[str, Any],
    segment_id: str,
    feature_date: date,
    rows_by_segment_date: dict[tuple[str, date], dict[str, Any]],
) -> tuple[float | int | None, list[date]]:
    kind = rule["kind"]
    input_column = rule["input_column"]
    lag = int(rule["lag"])
    end_date = feature_date - timedelta(days=lag)

    if kind == "lag":
        source_row = rows_by_segment_date.get((segment_id, end_date))
        if source_row is None or not source_row["_include_flag"]:
            return None, []
        return parse_number(source_row[input_column], input_column), [end_date]

    if kind == "rolling_mean":
        window = int(rule["window"])
        min_periods = int(rule["min_periods"])
        window_dates = daterange(end_date - timedelta(days=window - 1), end_date)
        values: list[float] = []
        source_dates: list[date] = []
        for day in window_dates:
            source_row = rows_by_segment_date.get((segment_id, day))
            if source_row is None or not source_row["_include_flag"]:
                continue
            values.append(parse_number(source_row[input_column], input_column))
            source_dates.append(day)
        if len(values) < min_periods:
            return None, source_dates
        return sum(values) / len(values), source_dates

    if kind == "expanding_mean":
        min_periods = int(rule["min_periods"])
        segment_rows = [
            row
            for (candidate_segment, day), row in rows_by_segment_date.items()
            if candidate_segment == segment_id and day <= end_date and row["_include_flag"]
        ]
        ordered = sorted(segment_rows, key=lambda row: row["_date"])
        if len(ordered) < min_periods:
            return None, [row["_date"] for row in ordered]
        values = [parse_number(row[input_column], input_column) for row in ordered]
        return sum(values) / len(values), [row["_date"] for row in ordered]

    raise WindowFeatureError(f"unsupported feature kind: {kind}")


def build_report(
    spec: dict[str, Any],
    scenario: dict[str, Any],
    checks: list[dict[str, Any]],
    feature_rows: list[dict[str, Any]],
    leakage_audit_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    error_failures = [check for check in checks if not check["valid"] and check["severity"] == "error"]
    warning_failures = [check for check in checks if not check["valid"] and check["severity"] == "warning"]
    return {
        "audit_id": "window-feature-audit",
        "feature_set_id": spec.get("feature_set_id"),
        "forecast_id": scenario.get("forecast_id"),
        "valid": not error_failures,
        "warning_count": len(warning_failures),
        "error_count": len(error_failures),
        "checks": checks,
        "series": summarize_series(feature_rows),
        "outputs": {
            "feature_rows": len(feature_rows),
            "leakage_audit_rows": len(leakage_audit_rows),
            "training_feature_rows": sum(1 for row in feature_rows if row.get("include_in_training") == "true"),
            "warmup_rows": sum(1 for row in feature_rows if row.get("source_is_complete") == "true" and row.get("feature_complete") == "false"),
            "partial_rows": sum(1 for row in feature_rows if row.get("source_is_complete") == "false"),
        },
        "summary": {
            "checks_total": len(checks),
            "checks_failed": len(error_failures) + len(warning_failures),
            "blocking_errors": [check["id"] for check in error_failures],
            "warnings": [check["id"] for check in warning_failures],
        },
    }


def summarize_series(feature_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for segment_id in sorted({row["segment_id"] for row in feature_rows}):
        segment_rows = [row for row in feature_rows if row["segment_id"] == segment_id]
        training_rows = [row for row in segment_rows if row["include_in_training"] == "true"]
        summaries.append(
            {
                "segment_id": segment_id,
                "feature_rows": len(segment_rows),
                "training_feature_rows": len(training_rows),
                "first_training_date": training_rows[0]["observed_date"] if training_rows else None,
                "last_training_date": training_rows[-1]["observed_date"] if training_rows else None,
            }
        )
    return summaries


def write_package(output_dir: Path, package: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    feature_rows = package["feature_rows"]
    report = package["report"]
    rule_names = []
    if feature_rows:
        base_fields = {
            "metric_id",
            "segment_id",
            "observed_date",
            "frequency",
            "value",
            "delta_active",
            "history_points_before",
            "source_is_complete",
            "feature_complete",
            "include_in_training",
        }
        rule_names = [field for field in feature_rows[0] if field not in base_fields]
    write_csv(
        output_dir / "window_features.csv",
        feature_rows,
        [
            "metric_id",
            "segment_id",
            "observed_date",
            "frequency",
            "value",
            "delta_active",
            *rule_names,
            "history_points_before",
            "source_is_complete",
            "feature_complete",
            "include_in_training",
        ],
    )
    write_csv(
        output_dir / "leakage_audit.csv",
        package["leakage_audit_rows"],
        [
            "feature_set_id",
            "segment_id",
            "feature_date",
            "feature_name",
            "source_dates_used",
            "latest_source_date_used",
            "valid",
        ],
    )
    (output_dir / "window_feature_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Build lagged, rolling, and expanding features with strict temporal leakage checks.")
    parser.add_argument("--series", type=Path, required=True, help="daily_resampled.csv from the resampling lesson")
    parser.add_argument("--scenario", type=Path, required=True, help="forecast_scenario.json")
    parser.add_argument("--spec", type=Path, required=True, help="window_feature_spec.json")
    parser.add_argument("--output-dir", type=Path, help="directory for feature and audit outputs")
    parser.add_argument("--fail-on-warning", action="store_true", help="return non-zero when warning checks fail")
    args = parser.parse_args()
    try:
        package = build_window_feature_package(
            series_path=args.series,
            scenario_path=args.scenario,
            spec_path=args.spec,
        )
    except (OSError, WindowFeatureError) as error:
        parser.error(str(error))

    if args.output_dir:
        write_package(args.output_dir, package)
    print(json.dumps(package["report"], ensure_ascii=False, indent=2))
    report = package["report"]
    if not report["valid"] or (args.fail_on_warning and report["warning_count"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
