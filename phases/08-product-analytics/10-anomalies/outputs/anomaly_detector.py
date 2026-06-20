from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class DetectionResult:
    anomalies: dict[str, Any]
    report: dict[str, Any]


USER_COLUMNS = {
    "user_id",
    "registered_at",
    "is_test_user",
    "platform",
    "acquisition_channel",
}
EVENT_COLUMNS = {
    "event_id",
    "user_id",
    "event_name",
    "occurred_at",
    "received_at",
    "platform",
    "app_version",
}
RELEASE_COLUMNS = {"release_id", "released_at", "platform", "app_version", "change"}
SEGMENT_COLUMNS = {
    "metric_id",
    "row_type",
    "dimension",
    "segment_value",
    "is_exploratory",
    "baseline_rate",
    "comparison_rate",
    "baseline_share",
    "comparison_share",
    "within_segment_effect",
    "composition_effect",
    "total_delta_contribution",
}
GUARDRAIL_COLUMNS = {
    "metric_id",
    "row_type",
    "source",
    "risk_direction",
    "denominator",
    "numerator",
    "baseline_value",
    "comparison_value",
    "absolute_delta",
    "threshold_breached",
    "decision_status",
    "is_complete_window",
}


def read_csv(path: str | Path) -> tuple[list[dict[str, str]], list[str]]:
    with Path(path).open(encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        return list(reader), list(reader.fieldnames or [])


def read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: str | Path, payload: Any) -> None:
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed


def parse_iso_date(value: str) -> date:
    return date.fromisoformat(value)


def parse_float(value: str) -> float | None:
    if value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def bool_text(value: str) -> bool:
    return value.lower() == "true"


def period_by_id(spec: dict[str, Any], period_id: str) -> dict[str, str]:
    for period in spec["analysis_periods"]:
        if period["period_id"] == period_id:
            return period
    raise ValueError(f"missing period: {period_id}")


def date_in_period(value: date, period: dict[str, str]) -> bool:
    return parse_iso_date(period["date_from"]) <= value <= parse_iso_date(period["date_to"])


def normalize_spec(raw: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    spec = dict(raw)
    quality_gates = dict(spec.get("quality_gates", {}))
    thresholds = dict(spec.get("thresholds", {}))
    spec["quality_gates"] = {
        "max_late_minutes": int(quality_gates.get("max_late_minutes", 1440)),
        "min_events_per_period": int(quality_gates.get("min_events_per_period", 1)),
        "required_event_names": list(quality_gates.get("required_event_names", [])),
        "freshness_max_lag_days": int(quality_gates.get("freshness_max_lag_days", 0)),
    }
    spec["thresholds"] = {
        "guardrail_delta": float(thresholds.get("guardrail_delta", 0.0)),
        "composition_effect": float(thresholds.get("composition_effect", 0.0)),
        "release_window_days": int(thresholds.get("release_window_days", 0)),
    }
    spec["allowed_classifications"] = list(
        spec.get("allowed_classifications", ["data_quality", "composition", "calendar_effect", "product_signal"])
    )
    checks: list[dict[str, Any]] = []
    required_fields = {
        "version",
        "business_timezone",
        "analysis_periods",
        "observation_end_date",
        "quality_gates",
        "thresholds",
        "allowed_classifications",
    }
    missing = sorted(required_fields - set(raw))
    checks.append(check("spec_required_fields", not missing, observed=missing, expected=sorted(required_fields)))
    try:
        ZoneInfo(spec["business_timezone"])
        timezone_valid = True
    except Exception:
        timezone_valid = False
    checks.append(check("business_timezone_valid", timezone_valid, observed=spec.get("business_timezone")))
    period_ids = [period.get("period_id") for period in spec.get("analysis_periods", [])]
    periods_valid = period_ids == ["baseline", "comparison"]
    for period in spec.get("analysis_periods", []):
        try:
            periods_valid = periods_valid and parse_iso_date(period["date_from"]) <= parse_iso_date(period["date_to"])
        except Exception:
            periods_valid = False
    checks.append(check("analysis_periods_valid", periods_valid, observed=period_ids, expected=["baseline", "comparison"]))
    try:
        parse_iso_date(spec["observation_end_date"])
        observation_valid = True
    except Exception:
        observation_valid = False
    checks.append(check("observation_end_date_valid", observation_valid, observed=spec.get("observation_end_date")))
    allowed = set(spec["allowed_classifications"])
    required_classes = {"data_quality", "composition", "calendar_effect", "product_signal"}
    checks.append(
        check(
            "classifications_complete",
            required_classes.issubset(allowed),
            observed=sorted(allowed),
            expected=sorted(required_classes),
        )
    )
    return spec, checks


def check(
    check_id: str,
    valid: bool,
    *,
    observed: Any = None,
    expected: Any = None,
    sample: list[Any] | None = None,
    severity: str = "error",
    message: str = "",
) -> dict[str, Any]:
    return {
        "id": check_id,
        "valid": bool(valid),
        "severity": severity,
        "observed": observed,
        "expected": expected,
        "sample": sample or [],
        "message": message,
    }


def columns_check(check_id: str, columns: list[str], required: set[str]) -> dict[str, Any]:
    missing = sorted(required - set(columns))
    return check(check_id, not missing, observed=missing, expected=sorted(required))


def tracking_event_names(tracking_plan: dict[str, Any]) -> set[str]:
    return {event["event_name"] for event in tracking_plan.get("events", [])}


def duplicate_values(rows: list[dict[str, str]], key: str) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for row in rows:
        value = row.get(key, "")
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return sorted(duplicates)


def parsed_event_times(events: list[dict[str, str]]) -> tuple[dict[str, tuple[datetime, datetime]], list[str]]:
    parsed: dict[str, tuple[datetime, datetime]] = {}
    invalid: list[str] = []
    for event in events:
        event_id = event.get("event_id", "")
        try:
            occurred = parse_timestamp(event.get("occurred_at", ""))
            received = parse_timestamp(event.get("received_at", ""))
        except Exception:
            invalid.append(event_id)
            continue
        parsed[event_id] = (occurred, received)
    return parsed, invalid


def build_quality_gates(
    users: list[dict[str, str]],
    events: list[dict[str, str]],
    tracking_plan: dict[str, Any],
    spec: dict[str, Any],
) -> list[dict[str, Any]]:
    timezone = ZoneInfo(spec["business_timezone"])
    gate_spec = spec["quality_gates"]
    gates: list[dict[str, Any]] = []
    duplicate_event_ids = duplicate_values(events, "event_id")
    gates.append(
        check(
            "event_ids_unique",
            not duplicate_event_ids,
            observed=len(duplicate_event_ids),
            expected=0,
            sample=duplicate_event_ids[:5],
            message="Event IDs must be unique before metric anomalies can be trusted.",
        )
    )
    event_times, invalid_timestamps = parsed_event_times(events)
    gates.append(
        check(
            "event_timestamps_valid",
            not invalid_timestamps,
            observed=len(invalid_timestamps),
            expected=0,
            sample=invalid_timestamps[:5],
            message="occurred_at and received_at must be timezone-aware timestamps.",
        )
    )
    received_before_occurred = [
        event_id for event_id, (occurred, received) in event_times.items() if received < occurred
    ]
    gates.append(
        check(
            "received_after_occurred",
            not received_before_occurred,
            observed=len(received_before_occurred),
            expected=0,
            sample=received_before_occurred[:5],
            message="received_at cannot be earlier than occurred_at.",
        )
    )
    late_event_ids = []
    for event_id, (occurred, received) in event_times.items():
        delay_minutes = (received - occurred).total_seconds() / 60
        if delay_minutes > gate_spec["max_late_minutes"]:
            late_event_ids.append(event_id)
    gates.append(
        check(
            "late_events_within_policy",
            not late_event_ids,
            observed=len(late_event_ids),
            expected=f"<= {gate_spec['max_late_minutes']} minutes",
            sample=late_event_ids[:5],
            message="Late arrivals beyond policy can move events across analysis windows.",
        )
    )
    known_names = tracking_event_names(tracking_plan)
    unknown_event_names = sorted({event["event_name"] for event in events if event.get("event_name") not in known_names})
    gates.append(
        check(
            "known_event_names",
            not unknown_event_names,
            observed=unknown_event_names,
            expected=sorted(known_names),
            sample=unknown_event_names[:5],
            message="Events outside the tracking plan are instrumentation anomalies.",
        )
    )
    required_names = set(gate_spec["required_event_names"])
    observed_names = {event["event_name"] for event in events}
    missing_required = sorted(required_names - observed_names)
    gates.append(
        check(
            "required_events_present",
            not missing_required,
            observed=missing_required,
            expected=sorted(required_names),
            sample=missing_required[:5],
            message="Required product events must be present in the observation slice.",
        )
    )
    known_user_ids = {user["user_id"] for user in users}
    unknown_users = sorted({event["user_id"] for event in events if event.get("user_id") and event["user_id"] not in known_user_ids})
    gates.append(
        check(
            "events_reference_known_users",
            not unknown_users,
            observed=len(unknown_users),
            expected=0,
            sample=unknown_users[:5],
            message="Event users must resolve to the user table.",
        )
    )
    volume_observed: dict[str, int] = {}
    for period in spec["analysis_periods"]:
        count = 0
        for occurred, _received in event_times.values():
            if date_in_period(occurred.astimezone(timezone).date(), period):
                count += 1
        volume_observed[period["period_id"]] = count
    low_volume = [
        period_id
        for period_id, count in volume_observed.items()
        if count < gate_spec["min_events_per_period"]
    ]
    gates.append(
        check(
            "period_event_volume",
            not low_volume,
            observed=volume_observed,
            expected=f">= {gate_spec['min_events_per_period']} events per period",
            sample=low_volume,
            message="Both baseline and comparison periods need enough events for anomaly diagnosis.",
        )
    )
    max_received_date = None
    if event_times:
        max_received_date = max(received.astimezone(timezone).date() for _occurred, received in event_times.values())
    required_fresh_date = parse_iso_date(spec["observation_end_date"]) - timedelta(days=gate_spec["freshness_max_lag_days"])
    gates.append(
        check(
            "freshness",
            max_received_date is not None and max_received_date >= required_fresh_date,
            observed=max_received_date.isoformat() if max_received_date else None,
            expected=f">= {required_fresh_date.isoformat()}",
            sample=[],
            message="The event stream must be fresh enough before interpreting a spike as product behavior.",
        )
    )
    return gates


def data_quality_candidates(gates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = []
    critical = {
        "event_ids_unique",
        "event_timestamps_valid",
        "received_after_occurred",
        "late_events_within_policy",
        "known_event_names",
        "required_events_present",
        "freshness",
    }
    for gate in gates:
        if gate["valid"]:
            continue
        severity = "critical" if gate["id"] in critical else "warning"
        candidates.append(
            {
                "candidate_id": f"data-quality-{gate['id']}",
                "classification": "data_quality",
                "severity": severity,
                "metric_id": "__data_quality__",
                "period": "__all__",
                "observed": gate["observed"],
                "expected": gate["expected"],
                "evidence": gate["sample"] or [gate["message"]],
                "recommended_action": "fix_data_quality_before_product_decision",
            }
        )
    return candidates


def product_signal_candidates(guardrails: list[dict[str, str]], spec: dict[str, Any]) -> list[dict[str, Any]]:
    threshold = spec["thresholds"]["guardrail_delta"]
    candidates = []
    for row in guardrails:
        if row.get("row_type") != "assessment":
            continue
        delta = parse_float(row.get("absolute_delta", ""))
        breached = row.get("decision_status") == "breached" and bool_text(row.get("threshold_breached", "false"))
        if delta is None or not breached or abs(delta) < threshold:
            continue
        candidates.append(
            {
                "candidate_id": f"guardrail-{row['metric_id']}",
                "classification": "product_signal",
                "severity": "critical",
                "metric_id": row["metric_id"],
                "period": "comparison",
                "observed": row["comparison_value"],
                "expected": row["baseline_value"],
                "delta": f"{delta:.6f}",
                "evidence": [
                    f"baseline={row['baseline_value']}",
                    f"comparison={row['comparison_value']}",
                    f"absolute_delta={delta:.6f}",
                    f"denominator={row['denominator']}",
                    f"numerator={row['numerator']}",
                ],
                "recommended_action": "investigate_product_change_before_rollout",
            }
        )
    return candidates


def composition_candidates(segments: list[dict[str, str]], spec: dict[str, Any]) -> list[dict[str, Any]]:
    threshold = spec["thresholds"]["composition_effect"]
    candidates = []
    for row in segments:
        if row.get("row_type") != "decomposition":
            continue
        if bool_text(row.get("is_exploratory", "false")):
            continue
        composition_effect = parse_float(row.get("composition_effect", ""))
        total_delta = parse_float(row.get("total_delta_contribution", ""))
        if composition_effect is None or total_delta is None:
            continue
        if total_delta >= 0 or abs(composition_effect) < threshold:
            continue
        candidates.append(
            {
                "candidate_id": f"composition-{row['dimension']}-{row['segment_value']}",
                "classification": "composition",
                "severity": "warning",
                "metric_id": row["metric_id"],
                "period": "comparison",
                "observed": row["comparison_share"],
                "expected": row["baseline_share"],
                "delta": f"{composition_effect:.6f}",
                "evidence": [
                    f"{row['dimension']}={row['segment_value']}",
                    f"baseline_share={row['baseline_share']}",
                    f"comparison_share={row['comparison_share']}",
                    f"within_segment_effect={row['within_segment_effect']}",
                    f"total_delta_contribution={row['total_delta_contribution']}",
                ],
                "recommended_action": "separate_mix_shift_from_within_segment_change",
            }
        )
    return candidates


def release_date(row: dict[str, str], timezone: ZoneInfo) -> date | None:
    try:
        return parse_timestamp(row["released_at"]).astimezone(timezone).date()
    except Exception:
        return None


def calendar_candidates(
    releases: list[dict[str, str]],
    product_candidates: list[dict[str, Any]],
    spec: dict[str, Any],
) -> list[dict[str, Any]]:
    if not product_candidates:
        return []
    timezone = ZoneInfo(spec["business_timezone"])
    comparison = period_by_id(spec, "comparison")
    comparison_from = parse_iso_date(comparison["date_from"])
    comparison_to = parse_iso_date(comparison["date_to"])
    window = timedelta(days=spec["thresholds"]["release_window_days"])
    metric_id = product_candidates[0]["metric_id"]
    product_ids = [candidate["candidate_id"] for candidate in product_candidates]
    candidates = []
    for row in releases:
        released_on = release_date(row, timezone)
        if released_on is None:
            continue
        if comparison_from - window <= released_on <= comparison_to + window:
            candidates.append(
                {
                    "candidate_id": f"calendar-{row['release_id']}-{row['platform']}",
                    "classification": "calendar_effect",
                    "severity": "warning",
                    "metric_id": metric_id,
                    "period": "comparison",
                    "observed": released_on.isoformat(),
                    "expected": f"{comparison['date_from']}..{comparison['date_to']}",
                    "delta": "",
                    "evidence": [
                        f"release_id={row['release_id']}",
                        f"platform={row['platform']}",
                        f"app_version={row['app_version']}",
                        f"change={row['change']}",
                        f"coincides_with={','.join(product_ids)}",
                    ],
                    "recommended_action": "check_release_notes_rollout_and_platform_split",
                }
            )
    return candidates


def class_counts(candidates: list[dict[str, Any]], allowed: list[str]) -> dict[str, int]:
    counts = {classification: 0 for classification in allowed}
    for candidate in candidates:
        counts[candidate["classification"]] = counts.get(candidate["classification"], 0) + 1
    return counts


def recommendation(candidates: list[dict[str, Any]], quality_gates_passed: bool) -> str:
    if not quality_gates_passed:
        return "fix_data_quality"
    if any(candidate["classification"] == "product_signal" for candidate in candidates):
        return "investigate_before_rollout"
    if candidates:
        return "inspect_context"
    return "no_action"


def detect_anomalies(
    users: list[dict[str, str]],
    user_columns: list[str],
    events: list[dict[str, str]],
    event_columns: list[str],
    tracking_plan: dict[str, Any],
    releases: list[dict[str, str]],
    release_columns: list[str],
    segments: list[dict[str, str]],
    segment_columns: list[str],
    guardrails: list[dict[str, str]],
    guardrail_columns: list[str],
    raw_spec: dict[str, Any],
) -> DetectionResult:
    spec, checks = normalize_spec(raw_spec)
    checks.extend(
        [
            columns_check("users_columns", user_columns, USER_COLUMNS),
            columns_check("events_columns", event_columns, EVENT_COLUMNS),
            columns_check("release_calendar_columns", release_columns, RELEASE_COLUMNS),
            columns_check("segments_columns", segment_columns, SEGMENT_COLUMNS),
            columns_check("guardrails_columns", guardrail_columns, GUARDRAIL_COLUMNS),
        ]
    )
    structural_valid = all(item["valid"] for item in checks)
    if structural_valid:
        gates = build_quality_gates(users, events, tracking_plan, spec)
    else:
        gates = [
            check(
                "structural_inputs_valid",
                False,
                observed=[item["id"] for item in checks if not item["valid"]],
                expected="valid spec and required input columns",
                message="Structural checks must pass before anomaly classification.",
            )
        ]
    quality_gates_passed = all(gate["valid"] for gate in gates)
    candidates: list[dict[str, Any]]
    if quality_gates_passed:
        product_candidates = product_signal_candidates(guardrails, spec)
        candidates = []
        candidates.extend(product_candidates)
        candidates.extend(composition_candidates(segments, spec))
        candidates.extend(calendar_candidates(releases, product_candidates, spec))
    else:
        candidates = data_quality_candidates(gates)
    counts = class_counts(candidates, spec["allowed_classifications"])
    summary = {
        "candidates": len(candidates),
        "by_classification": counts,
        "product_signal_allowed": quality_gates_passed,
        "recommended_action": recommendation(candidates, quality_gates_passed),
    }
    valid = structural_valid and quality_gates_passed
    report = {
        "valid": valid,
        "checks": checks,
        "quality_gates_passed": quality_gates_passed,
        "quality_gates": gates,
        "summary": summary,
    }
    anomalies = {
        "version": spec["version"],
        "analysis_periods": spec["analysis_periods"],
        "quality_gates_passed": quality_gates_passed,
        "summary": summary,
        "quality_gates": gates,
        "candidates": candidates,
    }
    return DetectionResult(anomalies=anomalies, report=report)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Classify product metric anomalies.")
    parser.add_argument("--users", required=True)
    parser.add_argument("--events", required=True)
    parser.add_argument("--tracking-plan", required=True)
    parser.add_argument("--release-calendar", required=True)
    parser.add_argument("--segments", required=True)
    parser.add_argument("--guardrails", required=True)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--report", default="")
    parser.add_argument("--allow-failures", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    users, user_columns = read_csv(args.users)
    events, event_columns = read_csv(args.events)
    releases, release_columns = read_csv(args.release_calendar)
    segments, segment_columns = read_csv(args.segments)
    guardrails, guardrail_columns = read_csv(args.guardrails)
    result = detect_anomalies(
        users,
        user_columns,
        events,
        event_columns,
        read_json(args.tracking_plan),
        releases,
        release_columns,
        segments,
        segment_columns,
        guardrails,
        guardrail_columns,
        read_json(args.spec),
    )
    write_json(args.output, result.anomalies)
    if args.report:
        write_json(args.report, result.report)
    if result.report["valid"] or args.allow_failures:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
