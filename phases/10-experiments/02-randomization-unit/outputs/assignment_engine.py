from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

ASSIGNMENT_FIELDS = [
    "experiment_id",
    "assignment_unit_type",
    "assignment_unit_id",
    "user_id",
    "variant_id",
    "bucket",
    "assigned_at",
    "allocation_ratio",
    "is_eligible",
    "assignment_source",
]
EXPOSURE_FIELDS = [
    "exposure_id",
    "experiment_id",
    "assignment_unit_id",
    "user_id",
    "variant_id",
    "exposure_event",
    "exposed_at",
    "received_at",
    "platform",
    "app_version",
]
SUPPORTED_HASH_METHODS = {"sha256"}
SUPPORTED_OPERATORS = {"=="}


def passed(check_id: str, observed: Any = None, expected: Any = None) -> dict[str, Any]:
    return {
        "id": check_id,
        "severity": "error",
        "valid": True,
        "observed": observed,
        "expected": expected,
        "sample": [],
    }


def failed(check_id: str, observed: Any, expected: Any, sample: list[Any] | None = None) -> dict[str, Any]:
    return {
        "id": check_id,
        "severity": "error",
        "valid": False,
        "observed": observed,
        "expected": expected,
        "sample": sample or [],
    }


def read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as source:
        value = json.load(source)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def parse_bool(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    normalized = value.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise ValueError(f"expected boolean value, got {value!r}")


def parse_float(value: str | float | int) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if value.strip() == "":
        raise ValueError("empty float value")
    return float(value)


def parse_iso_datetime(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed


def normalize_filter_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def row_matches_filters(row: dict[str, str], filters: list[dict[str, Any]]) -> bool:
    for item in filters:
        if item.get("operator") not in SUPPORTED_OPERATORS:
            raise ValueError(f"unsupported eligibility operator: {item.get('operator')}")
        field = item.get("field")
        if not isinstance(field, str) or field not in row:
            return False
        if row[field].strip().lower() != normalize_filter_value(item.get("value")).strip().lower():
            return False
    return True


def eligibility_filters(protocol: dict[str, Any], spec: dict[str, Any]) -> list[dict[str, Any]]:
    filters = spec.get("eligibility", {}).get("filters")
    if filters is None:
        filters = protocol.get("eligible_population", {}).get("filters")
    if not isinstance(filters, list):
        raise ValueError("eligibility filters must be a list")
    return filters


def eligible_users(users: list[dict[str, str]], protocol: dict[str, Any], spec: dict[str, Any]) -> list[dict[str, str]]:
    filters = eligibility_filters(protocol, spec)
    return [row for row in users if row_matches_filters(row, filters)]


def hash_bucket(experiment_id: str, unit_id: str, spec: dict[str, Any]) -> int:
    method = spec.get("hash_method")
    if method not in SUPPORTED_HASH_METHODS:
        raise ValueError(f"unsupported hash_method: {method}")
    bucket_count = int(spec.get("bucket_count", 0))
    if bucket_count <= 0:
        raise ValueError("bucket_count must be positive")
    salt = str(spec.get("salt", ""))
    digest = hashlib.sha256(f"{salt}:{experiment_id}:{unit_id}".encode("utf-8")).hexdigest()
    return int(digest[:16], 16) % bucket_count


def variant_for_bucket(bucket: int, protocol: dict[str, Any], spec: dict[str, Any]) -> str:
    bucket_count = int(spec["bucket_count"])
    allocation = protocol["traffic_allocation"]
    cumulative = 0.0
    last_variant = ""
    for variant_id in sorted(allocation):
        last_variant = variant_id
        cumulative += float(allocation[variant_id])
        if bucket < round(cumulative * bucket_count):
            return variant_id
    return last_variant


def build_assignments(users: list[dict[str, str]], protocol: dict[str, Any], spec: dict[str, Any]) -> list[dict[str, Any]]:
    experiment_id = protocol["experiment_id"]
    unit = spec["assignment_unit"]
    assigned_at = spec["assigned_at"]
    allocation = protocol["traffic_allocation"]
    result: list[dict[str, Any]] = []
    for row in eligible_users(users, protocol, spec):
        unit_id = row[unit]
        bucket = hash_bucket(experiment_id, unit_id, spec)
        variant_id = variant_for_bucket(bucket, protocol, spec)
        result.append(
            {
                "experiment_id": experiment_id,
                "assignment_unit_type": unit,
                "assignment_unit_id": unit_id,
                "user_id": row["user_id"],
                "variant_id": variant_id,
                "bucket": bucket,
                "assigned_at": assigned_at,
                "allocation_ratio": allocation[variant_id],
                "is_eligible": "true",
                "assignment_source": spec.get("assignment_source", "deterministic_hash"),
            }
        )
    return result


def first_paywall_events(events: list[dict[str, str]], protocol: dict[str, Any]) -> dict[str, dict[str, str]]:
    exposure_event = protocol["exposure_event"]
    by_user: dict[str, dict[str, str]] = {}
    for row in sorted(events, key=lambda item: item["occurred_at"]):
        if row.get("event_name") != exposure_event:
            continue
        user_id = row.get("user_id", "")
        by_user.setdefault(user_id, row)
    return by_user


def build_exposures(
    assignments: list[dict[str, Any]],
    events: list[dict[str, str]],
    protocol: dict[str, Any],
) -> list[dict[str, Any]]:
    events_by_user = first_paywall_events(events, protocol)
    result: list[dict[str, Any]] = []
    for assignment in assignments:
        event = events_by_user.get(str(assignment["user_id"]))
        if event is None:
            continue
        user_id = str(assignment["user_id"])
        result.append(
            {
                "exposure_id": f"X-{protocol['experiment_id']}-{user_id}",
                "experiment_id": protocol["experiment_id"],
                "assignment_unit_id": assignment["assignment_unit_id"],
                "user_id": user_id,
                "variant_id": assignment["variant_id"],
                "exposure_event": protocol["exposure_event"],
                "exposed_at": event["occurred_at"],
                "received_at": event["received_at"],
                "platform": event.get("platform", ""),
                "app_version": event.get("app_version", ""),
            }
        )
    return result


def duplicate_values(rows: list[dict[str, Any]], column: str) -> list[str]:
    counts = Counter(str(row.get(column, "")) for row in rows)
    return sorted(value for value, count in counts.items() if value and count > 1)


def validate_spec(protocol: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    if spec.get("experiment_id") != protocol.get("experiment_id"):
        errors.append({"field": "experiment_id", "value": spec.get("experiment_id")})
    if spec.get("assignment_unit") != protocol.get("randomization_unit"):
        errors.append({"field": "assignment_unit", "value": spec.get("assignment_unit")})
    if spec.get("analysis_unit") != protocol.get("analysis_unit"):
        errors.append({"field": "analysis_unit", "value": spec.get("analysis_unit")})
    if spec.get("hash_method") not in SUPPORTED_HASH_METHODS:
        errors.append({"field": "hash_method", "value": spec.get("hash_method")})
    if int(spec.get("bucket_count", 0)) <= 0:
        errors.append({"field": "bucket_count", "value": spec.get("bucket_count")})
    if parse_iso_datetime(str(spec.get("assigned_at", ""))) is None:
        errors.append({"field": "assigned_at", "value": spec.get("assigned_at")})
    if not isinstance(spec.get("interference_columns"), list):
        errors.append({"field": "interference_columns", "value": spec.get("interference_columns")})
    if errors:
        return failed("randomization_spec_matches_protocol", len(errors), "spec matches protocol randomization contract", errors)
    return passed("randomization_spec_matches_protocol", spec.get("assignment_unit"), "spec matches protocol randomization contract")


def validate_assignments(
    assignments: list[dict[str, Any]],
    users: list[dict[str, str]],
    protocol: dict[str, Any],
    spec: dict[str, Any],
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    eligible = eligible_users(users, protocol, spec)
    eligible_ids = {row["user_id"] for row in eligible}
    assignment_ids = [str(row.get("assignment_unit_id", "")) for row in assignments]
    duplicate_units = duplicate_values(assignments, "assignment_unit_id")
    if duplicate_units:
        checks.append(failed("one_assignment_per_unit", duplicate_units, "one assignment per randomization unit", duplicate_units))
    else:
        checks.append(passed("one_assignment_per_unit", len(assignments), "one assignment per randomization unit"))

    missing = sorted(eligible_ids - set(assignment_ids))
    extra = sorted(set(assignment_ids) - eligible_ids)
    if missing or extra:
        checks.append(failed("assignment_matches_eligibility", {"missing": missing, "extra": extra}, "assign exactly eligible units", missing + extra))
    else:
        checks.append(passed("assignment_matches_eligibility", len(assignment_ids), "assign exactly eligible units"))

    variant_errors: list[dict[str, Any]] = []
    allocation = protocol["traffic_allocation"]
    for row in assignments:
        unit_id = str(row.get("assignment_unit_id", ""))
        try:
            expected_bucket = hash_bucket(protocol["experiment_id"], unit_id, spec)
            observed_bucket = int(row["bucket"])
        except (KeyError, ValueError):
            variant_errors.append({"assignment_unit_id": unit_id, "reason": "invalid bucket"})
            continue
        expected_variant = variant_for_bucket(expected_bucket, protocol, spec)
        if observed_bucket != expected_bucket or row.get("variant_id") != expected_variant:
            variant_errors.append(
                {
                    "assignment_unit_id": unit_id,
                    "observed_bucket": observed_bucket,
                    "expected_bucket": expected_bucket,
                    "observed_variant": row.get("variant_id"),
                    "expected_variant": expected_variant,
                }
            )
        if row.get("variant_id") not in allocation:
            variant_errors.append({"assignment_unit_id": unit_id, "variant_id": row.get("variant_id"), "reason": "unknown variant"})
    if variant_errors:
        checks.append(failed("assignment_hash_is_stable", len(variant_errors), "bucket and variant match deterministic hash", variant_errors))
    else:
        checks.append(passed("assignment_hash_is_stable", len(assignments), "bucket and variant match deterministic hash"))

    counts = Counter(str(row.get("variant_id", "")) for row in assignments)
    total = len(assignments)
    tolerance = float(spec.get("balance_tolerance", 0.2))
    balance_errors: list[dict[str, Any]] = []
    for variant_id, expected_share in allocation.items():
        observed_share = counts.get(variant_id, 0) / total if total else 0
        if abs(observed_share - float(expected_share)) > tolerance:
            balance_errors.append(
                {
                    "variant_id": variant_id,
                    "observed_share": round(observed_share, 6),
                    "expected_share": expected_share,
                }
            )
    if balance_errors:
        checks.append(failed("assignment_balance_within_tolerance", len(balance_errors), f"share within {tolerance}", balance_errors))
    else:
        checks.append(passed("assignment_balance_within_tolerance", dict(counts), f"share within {tolerance}"))
    return checks


def validate_exposures(
    exposures: list[dict[str, Any]],
    assignments: list[dict[str, Any]],
    protocol: dict[str, Any],
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    duplicate_exposures = duplicate_values(exposures, "exposure_id")
    if duplicate_exposures:
        checks.append(failed("exposure_ids_unique", duplicate_exposures, "unique exposure_id", duplicate_exposures))
    else:
        checks.append(passed("exposure_ids_unique", len(exposures), "unique exposure_id"))

    assignment_by_unit = {str(row["assignment_unit_id"]): row for row in assignments}
    start = parse_iso_datetime(protocol["start_at"])
    end = parse_iso_datetime(protocol["planned_end_at"])
    exposure_errors: list[dict[str, Any]] = []
    for row in exposures:
        unit_id = str(row.get("assignment_unit_id", ""))
        assignment = assignment_by_unit.get(unit_id)
        if assignment is None:
            exposure_errors.append({"exposure_id": row.get("exposure_id"), "assignment_unit_id": unit_id, "reason": "missing assignment"})
            continue
        if row.get("variant_id") != assignment.get("variant_id"):
            exposure_errors.append(
                {
                    "exposure_id": row.get("exposure_id"),
                    "observed_variant": row.get("variant_id"),
                    "expected_variant": assignment.get("variant_id"),
                }
            )
        if row.get("exposure_event") != protocol.get("exposure_event"):
            exposure_errors.append({"exposure_id": row.get("exposure_id"), "exposure_event": row.get("exposure_event")})
        assigned_at = parse_iso_datetime(str(assignment.get("assigned_at", "")))
        exposed_at = parse_iso_datetime(str(row.get("exposed_at", "")))
        received_at = parse_iso_datetime(str(row.get("received_at", "")))
        if assigned_at is None or exposed_at is None or received_at is None:
            exposure_errors.append({"exposure_id": row.get("exposure_id"), "reason": "invalid timestamp"})
            continue
        if exposed_at < assigned_at:
            exposure_errors.append({"exposure_id": row.get("exposure_id"), "reason": "exposure before assignment"})
        if received_at < exposed_at:
            exposure_errors.append({"exposure_id": row.get("exposure_id"), "reason": "received before exposed"})
        if start is not None and end is not None and not (start <= exposed_at <= end):
            exposure_errors.append({"exposure_id": row.get("exposure_id"), "reason": "exposure outside experiment window"})
    if exposure_errors:
        checks.append(failed("exposures_match_assignments_and_timing", len(exposure_errors), "exposures match assigned variant and timing", exposure_errors))
    else:
        checks.append(passed("exposures_match_assignments_and_timing", len(exposures), "exposures match assigned variant and timing"))
    return checks


def validate_interference(
    assignments: list[dict[str, Any]],
    users: list[dict[str, str]],
    spec: dict[str, Any],
) -> dict[str, Any]:
    user_by_id = {row["user_id"]: row for row in users}
    columns = spec.get("interference_columns", [])
    errors: list[dict[str, Any]] = []
    for column in columns:
        buckets: dict[str, set[str]] = defaultdict(set)
        for assignment in assignments:
            user = user_by_id.get(str(assignment.get("user_id", "")))
            if user is None:
                continue
            value = user.get(column, "")
            if value:
                buckets[value].add(str(assignment.get("variant_id", "")))
        for value, variants in buckets.items():
            if len(variants) > 1:
                errors.append({"column": column, "value": value, "variants": sorted(variants)})
    if errors:
        return failed("interference_units_not_split", len(errors), "shared interference units stay in one variant", errors)
    return passed("interference_units_not_split", columns, "shared interference units stay in one variant")


def audit_assignment(
    assignments: list[dict[str, Any]],
    exposures: list[dict[str, Any]],
    users: list[dict[str, str]],
    protocol: dict[str, Any],
    spec: dict[str, Any],
) -> dict[str, Any]:
    checks = [validate_spec(protocol, spec)]
    checks.extend(validate_assignments(assignments, users, protocol, spec))
    checks.extend(validate_exposures(exposures, assignments, protocol))
    checks.append(validate_interference(assignments, users, spec))
    valid = all(check["valid"] for check in checks)
    counts = Counter(str(row.get("variant_id", "")) for row in assignments)
    return {
        "valid": valid,
        "checks": checks,
        "summary": {
            "experiment_id": protocol.get("experiment_id"),
            "assignment_unit": spec.get("assignment_unit"),
            "analysis_unit": spec.get("analysis_unit"),
            "assigned_units": len(assignments),
            "exposed_units": len(exposures),
            "variant_counts": dict(sorted(counts.items())),
        },
    }


def run(
    users_path: Path,
    events_path: Path,
    protocol_path: Path,
    spec_path: Path,
    assignments_path: Path | None = None,
    exposures_path: Path | None = None,
) -> dict[str, Any]:
    users = read_csv(users_path)
    events = read_csv(events_path)
    protocol = read_json(protocol_path)
    spec = read_json(spec_path)
    assignments = read_csv(assignments_path) if assignments_path is not None else build_assignments(users, protocol, spec)
    exposures = read_csv(exposures_path) if exposures_path is not None else build_exposures(assignments, events, protocol)
    return audit_assignment(assignments, exposures, users, protocol, spec)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build deterministic A/B assignments and audit exposure quality")
    parser.add_argument("--users", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--assignments", type=Path)
    parser.add_argument("--exposures", type=Path)
    parser.add_argument("--write-assignments", type=Path)
    parser.add_argument("--write-exposures", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--allow-failures", action="store_true")
    args = parser.parse_args(argv)
    try:
        users = read_csv(args.users)
        events = read_csv(args.events)
        protocol = read_json(args.protocol)
        spec = read_json(args.spec)
        assignments = read_csv(args.assignments) if args.assignments is not None else build_assignments(users, protocol, spec)
        exposures = read_csv(args.exposures) if args.exposures is not None else build_exposures(assignments, events, protocol)
        report = audit_assignment(assignments, exposures, users, protocol, spec)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2
    if args.write_assignments is not None:
        write_csv(args.write_assignments, assignments, ASSIGNMENT_FIELDS)
    if args.write_exposures is not None:
        write_csv(args.write_exposures, exposures, EXPOSURE_FIELDS)
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    if report["valid"] or args.allow_failures:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
