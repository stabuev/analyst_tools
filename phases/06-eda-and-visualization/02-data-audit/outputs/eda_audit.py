from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

import pandas as pd


class AuditError(ValueError):
    """Raised when the input, contract, or audit evidence cannot be used safely."""


SUPPORTED_TYPES = {"string", "category", "integer", "decimal", "boolean", "timestamp", "date"}
TIMEZONE_SUFFIX = re.compile(r"(?:Z|[+-]\d{2}:\d{2})$")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_contract(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AuditError(f"cannot read contract: {error}") from error
    if not isinstance(value, dict) or not isinstance(value.get("table"), dict):
        raise AuditError("contract must contain a table object")
    table = value["table"]
    columns = table.get("columns")
    primary_key = table.get("primary_key")
    profiles = table.get("analysis_profiles")
    if not isinstance(columns, dict) or not columns:
        raise AuditError("contract table.columns must be a non-empty object")
    if not isinstance(primary_key, list) or not primary_key:
        raise AuditError("contract table.primary_key must be a non-empty list")
    if not isinstance(profiles, dict) or not profiles:
        raise AuditError("contract table.analysis_profiles must be a non-empty object")
    unknown_types = sorted(
        {
            spec.get("type")
            for spec in columns.values()
            if not isinstance(spec, dict) or spec.get("type") not in SUPPORTED_TYPES
        },
        key=str,
    )
    if unknown_types:
        raise AuditError(f"unsupported or missing column types: {unknown_types}")
    unknown_keys = sorted(set(primary_key) - set(columns))
    if unknown_keys:
        raise AuditError(f"primary key columns are not declared: {unknown_keys}")
    for name, profile in profiles.items():
        if not isinstance(profile, dict) or not isinstance(profile.get("required_columns"), list):
            raise AuditError(f"analysis profile {name} must declare required_columns")
        unknown = sorted(set(profile["required_columns"]) - set(columns))
        if unknown:
            raise AuditError(f"analysis profile {name} uses unknown columns: {unknown}")
    return value


def load_report(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AuditError(f"cannot read audit report: {error}") from error
    if not isinstance(value, dict) or "readiness" not in value or "source" not in value:
        raise AuditError("audit report misses readiness or source evidence")
    return value


def load_frame(path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(path, dtype="string", keep_default_na=False)
    except OSError as error:
        raise AuditError(f"cannot read input: {error}") from error
    except pd.errors.ParserError as error:
        raise AuditError(f"cannot parse input CSV: {error}") from error


def blank_mask(series: pd.Series) -> pd.Series:
    return series.astype("string").str.strip().eq("")


def line_numbers(mask: pd.Series, *, limit: int = 10) -> list[int]:
    return [position + 2 for position, value in enumerate(mask.fillna(False)) if bool(value)][
        :limit
    ]


def column_scopes(table: dict[str, Any], column: str) -> list[str]:
    scopes = [
        name
        for name, profile in table["analysis_profiles"].items()
        if column in profile["required_columns"]
    ]
    return scopes or ["dataset"]


def finding(
    check_id: str,
    status: str,
    severity: str,
    scopes: list[str],
    details: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": check_id,
        "status": status,
        "severity": severity,
        "scopes": scopes,
        "details": details,
    }


def parse_column(raw: pd.Series, kind: str) -> tuple[pd.Series, pd.Series, pd.Series]:
    missing = blank_mask(raw)
    invalid = pd.Series(False, index=raw.index)
    fractional = pd.Series(False, index=raw.index)
    if kind in {"integer", "decimal"}:
        parsed = pd.to_numeric(raw.mask(missing), errors="coerce")
        invalid = ~missing & parsed.isna()
        if kind == "integer":
            fractional = parsed.notna() & parsed.mod(1).ne(0)
    elif kind == "boolean":
        normalized = raw.astype("string").str.casefold()
        invalid = ~missing & ~normalized.isin(["true", "false"])
        parsed = normalized.map({"true": True, "false": False}).astype("boolean")
    elif kind in {"timestamp", "date"}:
        parsed = pd.to_datetime(raw.mask(missing), errors="coerce", utc=kind == "timestamp")
        invalid = ~missing & parsed.isna()
    else:
        parsed = raw.astype("string").mask(missing)
    return parsed, invalid, fractional


def key_evidence(frame: pd.DataFrame, key: list[str]) -> dict[str, Any]:
    blank = pd.Series(False, index=frame.index)
    for column in key:
        blank |= blank_mask(frame[column])
    exact: list[dict[str, str]] = []
    conflicts: list[dict[str, str]] = []
    duplicate_mask = frame.duplicated(key, keep=False) & ~blank
    if duplicate_mask.any():
        grouper: str | list[str] = key[0] if len(key) == 1 else key
        for group_key, group in frame.loc[duplicate_mask].groupby(grouper, dropna=False, sort=True):
            values = (group_key,) if len(key) == 1 else tuple(group_key)
            evidence = {column: str(value) for column, value in zip(key, values, strict=True)}
            if len(group.drop_duplicates()) == 1:
                exact.append(evidence)
            else:
                conflicts.append(evidence)
    return {
        "blank_key_rows": line_numbers(blank),
        "exact_duplicate_keys": exact,
        "conflicting_duplicate_keys": conflicts,
    }


def build_readiness(
    table: dict[str, Any],
    checks: list[dict[str, Any]],
    source_sha256: str | None,
    key_details: dict[str, Any],
    parsed_types: dict[str, str],
    frame: pd.DataFrame,
) -> dict[str, Any]:
    readiness: dict[str, Any] = {}
    for analysis_id, profile in table["analysis_profiles"].items():
        applies = [
            check for check in checks if analysis_id in check["scopes"] or "all" in check["scopes"]
        ]
        blockers = [check["id"] for check in applies if check["status"] == "fail"]
        decisions = [
            check["id"]
            for check in applies
            if check["status"] == "warn" and check["severity"] == "requires-decision"
        ]
        status = "blocked" if blockers else "ready_with_decisions" if decisions else "ready"
        eligibility = profile.get("eligibility")
        excluded_rows = 0
        if eligibility and eligibility.get("column") in frame:
            if eligibility.get("operator") != "eq":
                raise AuditError(f"unsupported eligibility operator in {analysis_id}")
            excluded_rows = int(
                frame[eligibility["column"]].astype("string").ne(str(eligibility["value"])).sum()
            )
        readiness[analysis_id] = {
            "status": status,
            "blocker_ids": blockers,
            "decision_ids": decisions,
            "selection_plan": {
                "source_sha256": source_sha256,
                "key": table["primary_key"],
                "drop_exact_duplicates": bool(key_details["exact_duplicate_keys"]),
                "exact_duplicate_keys": key_details["exact_duplicate_keys"],
                "eligibility": eligibility,
                "excluded_by_eligibility": excluded_rows,
                "required_columns": profile["required_columns"],
                "column_types": {
                    column: parsed_types[column] for column in profile["required_columns"]
                },
            },
        }
    return readiness


def audit_frame(
    frame: pd.DataFrame,
    contract: dict[str, Any],
    *,
    source_sha256: str | None = None,
    contract_sha256: str | None = None,
) -> dict[str, Any]:
    table = contract["table"]
    columns = table["columns"]
    expected = list(columns)
    missing_columns = sorted(set(expected) - set(frame.columns))
    unexpected_columns = sorted(set(frame.columns) - set(expected))
    checks: list[dict[str, Any]] = [
        finding(
            "schema-required-columns",
            "fail" if missing_columns else "pass",
            "blocker" if missing_columns else "info",
            ["all"],
            {"missing_columns": missing_columns},
        ),
        finding(
            "schema-unexpected-columns",
            "warn" if unexpected_columns else "pass",
            "warning" if unexpected_columns else "info",
            ["dataset"],
            {"unexpected_columns": unexpected_columns},
        ),
    ]
    key_details = {
        "blank_key_rows": [],
        "exact_duplicate_keys": [],
        "conflicting_duplicate_keys": [],
    }
    parsed_types = {name: spec["type"] for name, spec in columns.items()}
    if not missing_columns:
        key_details = key_evidence(frame, table["primary_key"])
        key_failed = bool(
            key_details["blank_key_rows"] or key_details["conflicting_duplicate_keys"]
        )
        checks.append(
            finding(
                "primary-key-integrity",
                "fail" if key_failed else "pass",
                "blocker" if key_failed else "info",
                ["all"],
                {
                    "key": table["primary_key"],
                    "blank_key_rows": key_details["blank_key_rows"],
                    "conflicting_duplicate_keys": key_details["conflicting_duplicate_keys"],
                },
            )
        )
        checks.append(
            finding(
                "exact-duplicate-deliveries",
                "warn" if key_details["exact_duplicate_keys"] else "pass",
                "requires-decision" if key_details["exact_duplicate_keys"] else "info",
                ["all"],
                {"keys": key_details["exact_duplicate_keys"]},
            )
        )

        parsed: dict[str, pd.Series] = {}
        missingness: dict[str, Any] = {}
        for name, spec in columns.items():
            raw = frame[name]
            missing = blank_mask(raw)
            value, invalid, fractional = parse_column(raw, spec["type"])
            parsed[name] = value
            missingness[name] = {
                "missing": int(missing.sum()),
                "lines": line_numbers(missing),
                "nullable": bool(spec["nullable"]),
            }
            required_failure = not spec["nullable"] and missing.any()
            checks.append(
                finding(
                    f"required:{name}",
                    "fail" if required_failure else "pass",
                    "blocker" if required_failure else "info",
                    column_scopes(table, name),
                    {"missing_rows": line_numbers(missing)},
                )
            )
            type_failure = invalid.any() or fractional.any()
            checks.append(
                finding(
                    f"type:{name}",
                    "fail" if type_failure else "pass",
                    "blocker" if type_failure else "info",
                    column_scopes(table, name),
                    {
                        "expected_type": spec["type"],
                        "invalid_rows": line_numbers(invalid),
                        "fractional_rows": line_numbers(fractional),
                    },
                )
            )
            if spec.get("timezone_required"):
                timezone_missing = ~missing & ~raw.astype("string").str.contains(TIMEZONE_SUFFIX)
                checks.append(
                    finding(
                        f"timezone:{name}",
                        "fail" if timezone_missing.any() else "pass",
                        "blocker" if timezone_missing.any() else "info",
                        column_scopes(table, name),
                        {"missing_timezone_rows": line_numbers(timezone_missing)},
                    )
                )
            if "allowed" in spec:
                unknown = sorted(set(raw.loc[~missing]) - set(spec["allowed"]))
                checks.append(
                    finding(
                        f"allowed:{name}",
                        "fail" if unknown else "pass",
                        "blocker" if unknown else "info",
                        column_scopes(table, name),
                        {"unknown_values": unknown},
                    )
                )
            if "min" in spec or "max" in spec:
                below = value.notna() & value.lt(spec.get("min", float("-inf")))
                above = value.notna() & value.gt(spec.get("max", float("inf")))
                failed = below.any() or above.any()
                checks.append(
                    finding(
                        f"domain:{name}",
                        "fail" if failed else "pass",
                        "blocker" if failed else "info",
                        column_scopes(table, name),
                        {
                            "below_min_rows": line_numbers(below),
                            "above_max_rows": line_numbers(above),
                            "min": spec.get("min"),
                            "max": spec.get("max"),
                        },
                    )
                )

        time_range = table["time_range"]
        time_column = time_range["column"]
        time_values = parsed[time_column]
        minimum = pd.Timestamp(time_range["min"]).tz_convert("UTC")
        maximum = pd.Timestamp(time_range["max"]).tz_convert("UTC")
        outside = time_values.notna() & ((time_values < minimum) | (time_values > maximum))
        checks.append(
            finding(
                "time-range",
                "fail" if outside.any() else "pass",
                "blocker" if outside.any() else "info",
                column_scopes(table, time_column),
                {"outside_rows": line_numbers(outside), "min": str(minimum), "max": str(maximum)},
            )
        )

        alignment = table["rules"]["cohort_alignment"]
        registered = parsed[alignment["registered_column"]]
        cohort = parsed[alignment["cohort_column"]]
        expected_cohort = registered.dt.normalize() - pd.to_timedelta(
            registered.dt.weekday - alignment["week_starts_on"], unit="D"
        )
        mismatch = registered.notna() & cohort.notna() & (expected_cohort.dt.date != cohort.dt.date)
        checks.append(
            finding(
                "cohort-alignment",
                "fail" if mismatch.any() else "pass",
                "blocker" if mismatch.any() else "info",
                list(
                    set(column_scopes(table, alignment["registered_column"]))
                    | set(column_scopes(table, alignment["cohort_column"]))
                ),
                {"mismatch_rows": line_numbers(mismatch)},
            )
        )

        app_rule = table["rules"]["app_version"]
        app_missing = blank_mask(frame[app_rule["column"]])
        condition = frame[app_rule["not_applicable_when"]["column"]].eq(
            app_rule["not_applicable_when"]["equals"]
        )
        app_invalid = (condition & ~app_missing) | (~condition & app_missing)
        checks.append(
            finding(
                "app-version-policy",
                "fail" if app_invalid.any() else "pass",
                "blocker" if app_invalid.any() else "info",
                ["dataset"],
                {
                    "structural_missing": int((condition & app_missing).sum()),
                    "violation_rows": line_numbers(app_invalid),
                },
            )
        )

        window = table["rules"]["observation_window"]
        observed = parsed[window["column"]]
        complete = observed.eq(window["complete_value"])
        incomplete = observed.notna() & ~complete
        complete_missing = pd.Series(False, index=frame.index)
        incomplete_filled = pd.Series(False, index=frame.index)
        for name in window["required_when_complete"]:
            complete_missing |= complete & blank_mask(frame[name])
        for name in window["must_be_missing_when_incomplete"]:
            incomplete_filled |= incomplete & ~blank_mask(frame[name])
        window_failed = complete_missing.any() or incomplete_filled.any()
        checks.append(
            finding(
                "observation-window-policy",
                "fail" if window_failed else "pass",
                "blocker" if window_failed else "info",
                ["activation_7d"],
                {
                    "incomplete_windows": int(incomplete.sum()),
                    "complete_missing_outcome_rows": line_numbers(complete_missing),
                    "incomplete_with_outcome_rows": line_numbers(incomplete_filled),
                },
            )
        )

        amount_rule = table["rules"]["first_order_amount"]
        required_when = amount_rule["required_when"]
        amount_required = frame[required_when["column"]].str.casefold().eq(required_when["equals"])
        amount_missing = blank_mask(frame[amount_rule["column"]])
        amount_failure = amount_required & amount_missing
        checks.append(
            finding(
                "first-order-amount-policy",
                "fail" if amount_failure.any() else "pass",
                "blocker" if amount_failure.any() else "info",
                ["dataset"],
                {"required_but_missing_rows": line_numbers(amount_failure)},
            )
        )

        nullable_unexplained = {
            name: details["missing"]
            for name, details in missingness.items()
            if details["nullable"] and details["missing"] and name == "country"
        }
        checks.append(
            finding(
                "nullable-missingness",
                "warn" if nullable_unexplained else "pass",
                "warning" if nullable_unexplained else "info",
                ["dataset"],
                {"reported_counts": nullable_unexplained},
            )
        )
    else:
        missingness = {}

    readiness = build_readiness(
        table,
        checks,
        source_sha256,
        key_details,
        parsed_types,
        frame,
    )
    failures = [check["id"] for check in checks if check["status"] == "fail"]
    decision_log: list[dict[str, Any]] = []
    if key_details["exact_duplicate_keys"]:
        decision_log.append(
            {
                "id": "resolve-exact-deliveries",
                "finding": "exact-duplicate-deliveries",
                "scope": "all analyses",
                "decision": (
                    "Retain one byte-equivalent row per key; never apply this to conflicts."
                ),
                "evidence": key_details["exact_duplicate_keys"],
            }
        )
    incomplete_count = 0
    if not missing_columns:
        window = table["rules"]["observation_window"]
        incomplete_count = int(parsed[window["column"]].ne(window["complete_value"]).sum())
    decision_log.append(
        {
            "id": "activation-window",
            "finding": "observation-window-policy",
            "scope": "activation_7d",
            "decision": (
                "Exclude incomplete windows from this denominator; do not rewrite outcomes."
            ),
            "evidence": {"excluded_rows": incomplete_count},
        }
    )
    return {
        "version": "2.0.0",
        "valid": not failures,
        "source": {
            "rows": len(frame),
            "sha256": source_sha256,
        },
        "contract": {
            "version": contract.get("version"),
            "sha256": contract_sha256,
            "table": table["name"],
            "grain": table["grain"],
            "primary_key": table["primary_key"],
        },
        "schema": {
            "expected_columns": expected,
            "missing_columns": missing_columns,
            "unexpected_columns": unexpected_columns,
        },
        "missingness": missingness,
        "checks": checks,
        "failure_ids": failures,
        "readiness": readiness,
        "decision_log": decision_log,
    }


def convert_selected_types(frame: pd.DataFrame, column_types: dict[str, str]) -> pd.DataFrame:
    converted = frame.copy()
    for column, kind in column_types.items():
        if kind == "integer":
            converted[column] = pd.to_numeric(converted[column]).astype("Int64")
        elif kind == "decimal":
            converted[column] = pd.to_numeric(converted[column]).astype("Float64")
        elif kind == "boolean":
            converted[column] = (
                converted[column]
                .str.casefold()
                .map({"true": True, "false": False})
                .astype("boolean")
            )
        elif kind == "timestamp":
            converted[column] = pd.to_datetime(converted[column], utc=True)
        elif kind == "date":
            converted[column] = pd.to_datetime(converted[column])
        else:
            converted[column] = converted[column].astype("string")
    return converted


def prepare_analysis_frame(
    input_path: Path,
    report: dict[str, Any],
    analysis_id: str,
) -> pd.DataFrame:
    try:
        readiness = report["readiness"][analysis_id]
        plan = readiness["selection_plan"]
    except KeyError as error:
        raise AuditError(f"audit report has no analysis profile: {analysis_id}") from error
    if readiness["status"] == "blocked":
        raise AuditError(f"analysis {analysis_id} is blocked by {readiness['blocker_ids']}")
    current_sha256 = sha256_file(input_path)
    if not plan.get("source_sha256") or current_sha256 != plan["source_sha256"]:
        raise AuditError("input checksum does not match audit evidence")
    frame = load_frame(input_path)
    key = plan["key"]
    if plan["drop_exact_duplicates"]:
        duplicate_mask = frame.duplicated(key, keep=False)
        grouper: str | list[str] = key[0] if len(key) == 1 else key
        for _, group in frame.loc[duplicate_mask].groupby(grouper, dropna=False):
            if len(group.drop_duplicates()) != 1:
                raise AuditError("selection plan cannot resolve conflicting duplicate keys")
        frame = frame.drop_duplicates(key, keep="first")
    eligibility = plan.get("eligibility")
    if eligibility:
        if eligibility.get("operator") != "eq":
            raise AuditError("unsupported eligibility operator in selection plan")
        frame = frame[frame[eligibility["column"]].astype("string").eq(str(eligibility["value"]))]
    frame = frame[plan["required_columns"]]
    return convert_selected_types(frame, plan["column_types"]).reset_index(drop=True)


def render_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit an EDA input and issue analysis-scoped readiness evidence"
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--analysis", default="activation_7d")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        contract = load_contract(args.contract)
        frame = load_frame(args.input)
        report = audit_frame(
            frame,
            contract,
            source_sha256=sha256_file(args.input),
            contract_sha256=sha256_file(args.contract),
        )
        if args.analysis not in report["readiness"]:
            raise AuditError(f"unknown analysis profile: {args.analysis}")
    except (AuditError, OSError) as error:
        sys.stdout.write(render_json({"error": str(error)}))
        return 2
    content = render_json(report)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content, encoding="utf-8")
    sys.stdout.write(content)
    if args.report_only or report["readiness"][args.analysis]["status"] != "blocked":
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
