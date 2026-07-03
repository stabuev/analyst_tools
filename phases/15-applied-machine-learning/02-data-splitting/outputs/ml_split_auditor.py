from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

REQUIRED_MANIFEST_COLUMNS = {
    "snapshot_id",
    "user_id",
    "prediction_time",
    "split",
    "split_order",
    "role",
    "assigned_by_policy",
}
REQUIRED_SNAPSHOT_COLUMNS = {
    "snapshot_id",
    "user_id",
    "prediction_time",
    "eligible_for_offer",
    "days_until_trial_end",
}
REQUIRED_LABEL_COLUMNS = {
    "snapshot_id",
    "target_name",
    "label_observed_at",
    "churned_14d",
    "label_window_complete",
}
SPLIT_ORDER = {"train": 1, "validation": 2, "test": 3}
ROLE_BY_SPLIT = {
    "train": "fit_preprocessing_and_estimator",
    "validation": "model_selection_and_threshold_selection",
    "test": "final_once_only_evaluation",
}


class MLSplitAuditError(ValueError):
    """Raised when split-audit inputs cannot be parsed."""


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


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise MLSplitAuditError(f"{path} must contain a JSON object")
    return value


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open(encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        return list(reader), list(reader.fieldnames or [])


def parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized == "true":
            return True
        if normalized == "false":
            return False
    raise MLSplitAuditError(f"expected boolean, got {value!r}")


def parse_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise MLSplitAuditError(f"expected integer, got {value!r}") from error


def parse_timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise MLSplitAuditError(f"{field} must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise MLSplitAuditError(f"{field} must be an ISO timestamp: {value}") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise MLSplitAuditError(f"{field} must be timezone-aware: {value}")
    return parsed


def criterion_matches(observed: Any, operator: str, expected: Any) -> bool:
    if operator == "==":
        return observed == expected
    if operator == ">=":
        return observed >= expected
    if operator == "<=":
        return observed <= expected
    if operator == ">":
        return observed > expected
    if operator == "<":
        return observed < expected
    raise MLSplitAuditError(f"unsupported operator: {operator}")


def coerce_like(value: Any, expected: Any) -> Any:
    if isinstance(expected, bool):
        return parse_bool(value)
    if isinstance(expected, int):
        return parse_int(value)
    return value


def eligible_snapshot_ids(
    spec: dict[str, Any], snapshots: list[dict[str, str]]
) -> tuple[set[str], list[dict[str, Any]]]:
    population = spec.get("eligible_population")
    if not isinstance(population, dict):
        return set(), [{"field": "eligible_population", "reason": "object required"}]
    criteria = population.get("criteria")
    if not isinstance(criteria, list) or not criteria:
        return set(), [{"field": "eligible_population.criteria", "reason": "non-empty list"}]

    errors: list[dict[str, Any]] = []
    selected: set[str] = set()
    for row in snapshots:
        include = True
        for criterion in criteria:
            if not isinstance(criterion, dict):
                errors.append({"criterion": criterion, "reason": "criterion must be object"})
                include = False
                continue
            field = criterion.get("field")
            if field not in row:
                errors.append({"field": field, "reason": "criterion field missing"})
                include = False
                continue
            expected = criterion.get("value")
            observed = coerce_like(row[field], expected)
            operator = str(criterion.get("operator"))
            if not criterion_matches(observed, operator, expected):
                include = False
                break
        if include:
            selected.add(row["snapshot_id"])
    return selected, errors


def validate_split_policy(spec: dict[str, Any]) -> dict[str, Any]:
    split_policy = spec.get("split_policy")
    if not isinstance(split_policy, dict):
        return failed("split_policy_is_declared", "missing", "split_policy object")

    expected = {
        "split_type": "group_time_aware",
        "group_key": "user_id",
        "time_key": "prediction_time",
        "validation_role": "model_and_threshold_selection",
        "test_role": "final_once_only_evaluation",
    }
    errors = [
        {"field": field, "observed": split_policy.get(field), "expected": value}
        for field, value in expected.items()
        if split_policy.get(field) != value
    ]
    if errors:
        return failed("split_policy_is_declared", len(errors), expected, errors)
    return passed("split_policy_is_declared", expected, "group/time aware split policy")


def validate_manifest_schema_and_coverage(
    spec: dict[str, Any],
    snapshots: list[dict[str, str]],
    snapshot_columns: list[str],
    manifest: list[dict[str, str]],
    manifest_columns: list[str],
) -> tuple[dict[str, Any], set[str]]:
    errors: list[dict[str, Any]] = []
    missing_snapshot_columns = sorted(REQUIRED_SNAPSHOT_COLUMNS - set(snapshot_columns))
    missing_manifest_columns = sorted(REQUIRED_MANIFEST_COLUMNS - set(manifest_columns))
    if missing_snapshot_columns:
        errors.append({"field": "ml_scoring_snapshots", "missing": missing_snapshot_columns})
    if missing_manifest_columns:
        errors.append({"field": "ml_split_manifest", "missing": missing_manifest_columns})
    if errors:
        return (
            failed("manifest_schema_and_coverage", len(errors), "required columns", errors),
            set(),
        )

    eligible_ids, population_errors = eligible_snapshot_ids(spec, snapshots)
    errors.extend(population_errors)
    snapshot_ids = {row["snapshot_id"] for row in snapshots}
    manifest_ids = [row["snapshot_id"] for row in manifest]
    duplicate_ids = sorted(
        snapshot_id for snapshot_id, count in Counter(manifest_ids).items() if count > 1
    )
    unknown_ids = sorted(set(manifest_ids) - snapshot_ids)
    missing_ids = sorted(eligible_ids - set(manifest_ids))
    extra_ids = sorted(set(manifest_ids) - eligible_ids)
    split_values = {row["split"] for row in manifest}
    missing_splits = sorted(set(SPLIT_ORDER) - split_values)
    unknown_splits = sorted(split_values - set(SPLIT_ORDER))

    if duplicate_ids:
        errors.append(
            {
                "field": "snapshot_id",
                "reason": "duplicate manifest rows",
                "sample": duplicate_ids,
            }
        )
    if unknown_ids:
        errors.append(
            {
                "field": "snapshot_id",
                "reason": "unknown snapshot ids",
                "sample": unknown_ids,
            }
        )
    if missing_ids:
        errors.append(
            {
                "field": "snapshot_id",
                "reason": "eligible rows missing",
                "sample": missing_ids,
            }
        )
    if extra_ids:
        errors.append(
            {
                "field": "snapshot_id",
                "reason": "manifest contains ineligible rows",
                "sample": extra_ids,
            }
        )
    if missing_splits or unknown_splits:
        errors.append(
            {
                "field": "split",
                "missing": missing_splits,
                "unknown": unknown_splits,
            }
        )

    if errors:
        return (
            failed(
                "manifest_schema_and_coverage",
                len(errors),
                "one row for every eligible snapshot and all three splits",
                errors,
            ),
            eligible_ids,
        )
    return (
        passed(
            "manifest_schema_and_coverage",
            {"eligible_rows": len(eligible_ids), "manifest_rows": len(manifest)},
            "one row for every eligible snapshot and all three splits",
        ),
        eligible_ids,
    )


def validate_manifest_matches_snapshots(
    snapshots: list[dict[str, str]], manifest: list[dict[str, str]]
) -> dict[str, Any]:
    snapshots_by_id = {row["snapshot_id"]: row for row in snapshots}
    errors: list[dict[str, Any]] = []
    for row in manifest:
        snapshot = snapshots_by_id.get(row["snapshot_id"])
        if snapshot is None:
            continue
        split = row["split"]
        expected_order = SPLIT_ORDER.get(split)
        expected_role = ROLE_BY_SPLIT.get(split)
        if row["user_id"] != snapshot["user_id"]:
            errors.append(
                {
                    "snapshot_id": row["snapshot_id"],
                    "field": "user_id",
                    "observed": row["user_id"],
                    "expected": snapshot["user_id"],
                }
            )
        if row["prediction_time"] != snapshot["prediction_time"]:
            errors.append(
                {
                    "snapshot_id": row["snapshot_id"],
                    "field": "prediction_time",
                    "observed": row["prediction_time"],
                    "expected": snapshot["prediction_time"],
                }
            )
        if expected_order is not None and parse_int(row["split_order"]) != expected_order:
            errors.append(
                {
                    "snapshot_id": row["snapshot_id"],
                    "field": "split_order",
                    "observed": row["split_order"],
                    "expected": expected_order,
                }
            )
        if expected_role is not None and row["role"] != expected_role:
            errors.append(
                {
                    "snapshot_id": row["snapshot_id"],
                    "field": "role",
                    "observed": row["role"],
                    "expected": expected_role,
                }
            )
        if row["assigned_by_policy"] != "chronological_group_holdout":
            errors.append(
                {
                    "snapshot_id": row["snapshot_id"],
                    "field": "assigned_by_policy",
                    "observed": row["assigned_by_policy"],
                    "expected": "chronological_group_holdout",
                }
            )
    if errors:
        return failed(
            "manifest_matches_snapshot_rows",
            len(errors),
            "manifest mirrors immutable snapshot fields and declared split roles",
            errors,
        )
    return passed(
        "manifest_matches_snapshot_rows",
        len(manifest),
        "manifest mirrors immutable snapshot fields and declared split roles",
    )


def validate_group_isolation(manifest: list[dict[str, str]]) -> dict[str, Any]:
    splits_by_user: dict[str, set[str]] = defaultdict(set)
    for row in manifest:
        splits_by_user[row["user_id"]].add(row["split"])
    leaking_users = {
        user_id: sorted(splits) for user_id, splits in splits_by_user.items() if len(splits) > 1
    }
    if leaking_users:
        return failed(
            "groups_do_not_cross_splits",
            len(leaking_users),
            "each user_id belongs to exactly one split",
            [{"user_id": user_id, "splits": splits} for user_id, splits in leaking_users.items()],
        )
    return passed(
        "groups_do_not_cross_splits",
        len(splits_by_user),
        "each user_id belongs to exactly one split",
    )


def validate_time_order(manifest: list[dict[str, str]]) -> dict[str, Any]:
    times_by_split: dict[str, list[datetime]] = defaultdict(list)
    for row in manifest:
        if row["split"] in SPLIT_ORDER:
            times_by_split[row["split"]].append(
                parse_timestamp(row["prediction_time"], "prediction_time")
            )
    errors: list[dict[str, Any]] = []
    for split in SPLIT_ORDER:
        if not times_by_split.get(split):
            errors.append({"split": split, "reason": "split has no rows"})
    if not errors:
        train_max = max(times_by_split["train"])
        validation_min = min(times_by_split["validation"])
        validation_max = max(times_by_split["validation"])
        test_min = min(times_by_split["test"])
        if not train_max < validation_min:
            errors.append(
                {
                    "boundary": "train_before_validation",
                    "train_max": train_max.isoformat(),
                    "validation_min": validation_min.isoformat(),
                }
            )
        if not validation_max < test_min:
            errors.append(
                {
                    "boundary": "validation_before_test",
                    "validation_max": validation_max.isoformat(),
                    "test_min": test_min.isoformat(),
                }
            )
    if errors:
        return failed(
            "prediction_time_order_respects_holdout",
            len(errors),
            "train prediction_time < validation prediction_time < test prediction_time",
            errors,
        )
    ordered_ranges = sorted(times_by_split.items(), key=lambda item: SPLIT_ORDER[item[0]])
    return passed(
        "prediction_time_order_respects_holdout",
        {
            split: {
                "min": min(values).isoformat(),
                "max": max(values).isoformat(),
            }
            for split, values in ordered_ranges
        },
        "train prediction_time < validation prediction_time < test prediction_time",
    )


def validate_label_horizon(
    spec: dict[str, Any],
    manifest: list[dict[str, str]],
    labels: list[dict[str, str]],
    label_columns: list[str],
) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    missing_columns = sorted(REQUIRED_LABEL_COLUMNS - set(label_columns))
    if missing_columns:
        return failed(
            "labels_are_observed_after_horizon",
            missing_columns,
            "required label columns",
            [{"missing_columns": missing_columns}],
        )
    target_definition = spec.get("target_definition")
    label_window = spec.get("label_window")
    if not isinstance(target_definition, dict) or not isinstance(label_window, dict):
        return failed(
            "labels_are_observed_after_horizon",
            "missing target contract",
            "target_definition and label_window objects",
        )
    target_name = str(spec.get("target_name"))
    target_column = str(target_definition.get("target_column"))
    horizon_days = parse_int(label_window.get("duration_days"))
    labels_by_snapshot = {row["snapshot_id"]: row for row in labels}
    for row in manifest:
        label = labels_by_snapshot.get(row["snapshot_id"])
        if label is None:
            errors.append({"snapshot_id": row["snapshot_id"], "reason": "missing label"})
            continue
        if label["target_name"] != target_name:
            errors.append(
                {
                    "snapshot_id": row["snapshot_id"],
                    "field": "target_name",
                    "observed": label["target_name"],
                    "expected": target_name,
                }
            )
        if target_column not in label:
            errors.append({"snapshot_id": row["snapshot_id"], "field": target_column})
            continue
        prediction_time = parse_timestamp(row["prediction_time"], "prediction_time")
        observed_at = parse_timestamp(label["label_observed_at"], "label_observed_at")
        if observed_at < prediction_time + timedelta(days=horizon_days):
            errors.append(
                {
                    "snapshot_id": row["snapshot_id"],
                    "field": "label_observed_at",
                    "observed": observed_at.isoformat(),
                    "expected": f">= prediction_time + {horizon_days} days",
                }
            )
        if not parse_bool(label["label_window_complete"]):
            errors.append(
                {
                    "snapshot_id": row["snapshot_id"],
                    "field": "label_window_complete",
                    "reason": "incomplete label window cannot enter any split",
                }
            )
    if errors:
        return failed(
            "labels_are_observed_after_horizon",
            len(errors),
            "labels complete after prediction horizon for all split rows",
            errors,
        )
    return passed(
        "labels_are_observed_after_horizon",
        {"rows": len(manifest), "horizon_days": horizon_days},
        "labels complete after prediction horizon for all split rows",
    )


def validate_validation_test_roles(manifest: list[dict[str, str]]) -> dict[str, Any]:
    errors = []
    for row in manifest:
        if row["split"] == "test" and row["role"] != ROLE_BY_SPLIT["test"]:
            errors.append(
                {
                    "snapshot_id": row["snapshot_id"],
                    "reason": "test rows cannot be used for threshold or model selection",
                    "observed": row["role"],
                }
            )
        if row["split"] == "validation" and "threshold" not in row["role"]:
            errors.append(
                {
                    "snapshot_id": row["snapshot_id"],
                    "reason": "validation must be the threshold-selection split",
                    "observed": row["role"],
                }
            )
    if errors:
        return failed(
            "validation_and_test_roles_are_separate",
            len(errors),
            "validation selects, test evaluates once",
            errors,
        )
    return passed(
        "validation_and_test_roles_are_separate",
        {"validation_role": ROLE_BY_SPLIT["validation"], "test_role": ROLE_BY_SPLIT["test"]},
        "validation selects, test evaluates once",
    )


def build_summary(
    spec: dict[str, Any],
    manifest: list[dict[str, str]],
    labels: list[dict[str, str]],
    checks: list[dict[str, Any]],
) -> dict[str, Any]:
    rows_by_split = Counter(row["split"] for row in manifest)
    label_by_snapshot = {row["snapshot_id"]: row for row in labels}
    target_column = str((spec.get("target_definition") or {}).get("target_column", "churned_14d"))
    positives_by_split: Counter[str] = Counter()
    negatives_by_split: Counter[str] = Counter()
    ranges: dict[str, dict[str, str]] = {}
    for split in SPLIT_ORDER:
        split_rows = [row for row in manifest if row["split"] == split]
        for row in split_rows:
            label = label_by_snapshot.get(row["snapshot_id"])
            if label and parse_bool(label[target_column]):
                positives_by_split[split] += 1
            else:
                negatives_by_split[split] += 1
        times = [parse_timestamp(row["prediction_time"], "prediction_time") for row in split_rows]
        if times:
            ranges[split] = {"min": min(times).isoformat(), "max": max(times).isoformat()}

    if rows_by_split and min(rows_by_split.values()) < 5:
        checks.append(
            failed(
                "tiny_split_expected",
                min(rows_by_split.values()),
                "production splits need larger samples before model selection",
                [{"rows_by_split": dict(rows_by_split)}],
                severity="warning",
            )
        )

    return {
        "problem_id": spec.get("problem_id"),
        "manifest_rows": len(manifest),
        "rows_by_split": {split: rows_by_split[split] for split in SPLIT_ORDER},
        "positives_by_split": {split: positives_by_split[split] for split in SPLIT_ORDER},
        "negatives_by_split": {split: negatives_by_split[split] for split in SPLIT_ORDER},
        "prediction_time_range_by_split": ranges,
        "readiness_status": "ready_for_metric_policy",
    }


def build_report(
    spec: dict[str, Any], checks: list[dict[str, Any]], summary: dict[str, Any]
) -> dict[str, Any]:
    errors = [check for check in checks if not check["valid"] and check["severity"] == "error"]
    warnings = [check for check in checks if not check["valid"] and check["severity"] == "warning"]
    return {
        "audit_id": "ml-split-manifest-audit",
        "problem_id": spec.get("problem_id"),
        "valid": not errors,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "checks": checks,
        "summary": {
            **summary,
            "checks_total": len(checks),
            "checks_failed": len(errors) + len(warnings),
            "blocking_errors": [check["id"] for check in errors],
            "warnings": [check["id"] for check in warnings],
        },
    }


def audit_split_manifest(
    *,
    spec: dict[str, Any],
    snapshots: list[dict[str, str]],
    snapshot_columns: list[str],
    labels: list[dict[str, str]],
    label_columns: list[str],
    manifest: list[dict[str, str]],
    manifest_columns: list[str],
) -> dict[str, Any]:
    checks = [validate_split_policy(spec)]
    coverage_check, _eligible_ids = validate_manifest_schema_and_coverage(
        spec, snapshots, snapshot_columns, manifest, manifest_columns
    )
    checks.append(coverage_check)
    if coverage_check["valid"]:
        checks.extend(
            [
                validate_manifest_matches_snapshots(snapshots, manifest),
                validate_group_isolation(manifest),
                validate_time_order(manifest),
                validate_label_horizon(spec, manifest, labels, label_columns),
                validate_validation_test_roles(manifest),
            ]
        )

    summary: dict[str, Any] = {}
    if all(check["valid"] or check["severity"] != "error" for check in checks):
        summary = build_summary(spec, manifest, labels, checks)
    return build_report(spec, checks, summary)


def run(
    *,
    spec_path: Path,
    snapshots_path: Path,
    labels_path: Path,
    manifest_path: Path,
) -> dict[str, Any]:
    snapshots, snapshot_columns = read_csv(snapshots_path)
    labels, label_columns = read_csv(labels_path)
    manifest, manifest_columns = read_csv(manifest_path)
    return audit_split_manifest(
        spec=read_json(spec_path),
        snapshots=snapshots,
        snapshot_columns=snapshot_columns,
        labels=labels,
        label_columns=label_columns,
        manifest=manifest,
        manifest_columns=manifest_columns,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit a train/validation/test split manifest before modeling."
    )
    parser.add_argument("--spec", type=Path, required=True, help="problem_spec.json")
    parser.add_argument("--snapshots", type=Path, required=True, help="ml_scoring_snapshots.csv")
    parser.add_argument("--labels", type=Path, required=True, help="ml_labels.csv")
    parser.add_argument("--manifest", type=Path, required=True, help="ml_split_manifest.csv")
    parser.add_argument("--output", type=Path, help="Optional JSON report path")
    parser.add_argument(
        "--fail-on-warning",
        action="store_true",
        help="Return non-zero when warnings are present.",
    )
    args = parser.parse_args()

    try:
        report = run(
            spec_path=args.spec,
            snapshots_path=args.snapshots,
            labels_path=args.labels,
            manifest_path=args.manifest,
        )
    except (OSError, json.JSONDecodeError, MLSplitAuditError) as error:
        print(f"ml split audit failed: {error}", file=sys.stderr)
        raise SystemExit(2) from error

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))

    if not report["valid"] or (args.fail_on_warning and report["warning_count"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
