from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd


class AuditError(ValueError):
    """Raised when the input or contract cannot be audited."""


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_contract(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AuditError(f"cannot read contract: {error}") from error
    if not isinstance(value, dict) or not isinstance(value.get("table"), dict):
        raise AuditError("contract must contain a table object")
    return value


def load_frame(path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(path, dtype="string", keep_default_na=False)
    except OSError as error:
        raise AuditError(f"cannot read input: {error}") from error
    except pd.errors.ParserError as error:
        raise AuditError(f"cannot parse input CSV: {error}") from error


def numeric_series(frame: pd.DataFrame, column: str) -> tuple[pd.Series, list[int]]:
    raw = frame[column].replace("", pd.NA)
    parsed = pd.to_numeric(raw, errors="coerce")
    invalid_mask = raw.notna() & parsed.isna()
    return parsed, [int(index) + 2 for index in frame.index[invalid_mask]]


def boolean_series(frame: pd.DataFrame, column: str) -> tuple[pd.Series, list[int]]:
    raw = frame[column].replace("", pd.NA)
    normalized = raw.str.casefold()
    invalid_mask = raw.notna() & ~normalized.isin(["true", "false"])
    values = normalized.map({"true": True, "false": False}).astype("boolean")
    return values, [int(index) + 2 for index in frame.index[invalid_mask]]


def missingness_report(frame: pd.DataFrame) -> dict[str, dict[str, Any]]:
    report: dict[str, dict[str, Any]] = {}
    for column in frame.columns:
        missing = frame[column].eq("")
        policy = "not allowed"
        expected_mask = pd.Series(False, index=frame.index)
        if column == "app_version":
            policy = "structural for web"
            expected_mask = frame["platform"].eq("web")
        elif column in {
            "sessions_7d",
            "activated_7d",
            "first_order_amount_rub",
            "support_tickets_7d",
        }:
            policy = "allowed by observation or event policy"
            observed_days, _ = numeric_series(frame, "observed_days")
            if column == "first_order_amount_rub":
                expected_mask = observed_days.lt(7) | frame["activated_7d"].ne("true")
            else:
                expected_mask = observed_days.lt(7)
        elif column == "country":
            policy = "nullable but requires reporting"
            expected_mask = missing

        report[column] = {
            "missing": int(missing.sum()),
            "expected_missing": int((missing & expected_mask).sum()),
            "unexpected_missing": int((missing & ~expected_mask).sum()),
            "policy": policy,
        }
    return report


def audit_frame(
    frame: pd.DataFrame,
    contract: dict[str, Any],
    *,
    source_sha256: str | None = None,
) -> dict[str, Any]:
    table = contract["table"]
    expected_columns = list(table["columns"])
    missing_columns = sorted(set(expected_columns) - set(frame.columns))
    unexpected_columns = sorted(set(frame.columns) - set(expected_columns))
    if missing_columns:
        return {
            "version": "1.0.0",
            "valid": False,
            "ready_for_activation": False,
            "source": {"rows": len(frame), "sha256": source_sha256},
            "schema": {
                "missing_columns": missing_columns,
                "unexpected_columns": unexpected_columns,
            },
            "checks": [],
            "decision_log": ["Stop: required columns are missing."],
        }

    observed_days, observed_invalid = numeric_series(frame, "observed_days")
    onboarding, onboarding_invalid = numeric_series(frame, "onboarding_seconds")
    sessions, sessions_invalid = numeric_series(frame, "sessions_7d")
    tickets, tickets_invalid = numeric_series(frame, "support_tickets_7d")
    amounts, amount_invalid = numeric_series(frame, "first_order_amount_rub")
    activated, activation_invalid = boolean_series(frame, "activated_7d")

    duplicate_mask = frame.duplicated("user_id", keep=False)
    duplicate_ids = sorted(frame.loc[duplicate_mask, "user_id"].unique().tolist())
    incomplete_mask = observed_days.lt(7)
    complete_mask = observed_days.eq(7)
    incomplete_outcome_values = (
        frame.loc[
            incomplete_mask,
            ["sessions_7d", "activated_7d", "first_order_amount_rub", "support_tickets_7d"],
        ]
        .ne("")
        .any(axis=1)
    )
    complete_missing_outcomes = (
        frame.loc[complete_mask, ["sessions_7d", "activated_7d", "support_tickets_7d"]]
        .eq("")
        .any(axis=1)
    )
    app_version_invalid = (frame["platform"].eq("web") & frame["app_version"].ne("")) | (
        ~frame["platform"].eq("web") & frame["app_version"].eq("")
    )
    cohort = pd.to_datetime(frame["cohort_week"], errors="coerce")
    registered = pd.to_datetime(frame["registered_at"], errors="coerce", utc=True)
    allowed_categories = {
        "platform": {"web", "ios", "android"},
        "acquisition_channel": {"organic", "search", "paid_social", "partner"},
        "plan": {"trial", "basic", "premium"},
    }
    unknown_categories = {
        column: sorted(set(frame[column]) - allowed)
        for column, allowed in allowed_categories.items()
    }
    missingness = missingness_report(frame)

    checks = [
        {
            "id": "primary-key",
            "status": "fail" if duplicate_ids else "pass",
            "details": {"duplicate_user_ids": duplicate_ids},
        },
        {
            "id": "observed-days-range",
            "status": "fail"
            if observed_invalid or observed_days.lt(1).any() or observed_days.gt(7).any()
            else "pass",
            "details": {
                "invalid_lines": observed_invalid,
                "outside_range": int((observed_days.lt(1) | observed_days.gt(7)).sum()),
            },
        },
        {
            "id": "onboarding-range",
            "status": "fail" if onboarding_invalid or onboarding.lt(0).any() else "pass",
            "details": {
                "invalid_lines": onboarding_invalid,
                "negative_rows": int(onboarding.lt(0).sum()),
                "extreme_rows": int(onboarding.gt(1800).sum()),
            },
        },
        {
            "id": "numeric-types",
            "status": "fail" if sessions_invalid or tickets_invalid or amount_invalid else "pass",
            "details": {
                "sessions_invalid_lines": sessions_invalid,
                "tickets_invalid_lines": tickets_invalid,
                "amount_invalid_lines": amount_invalid,
                "negative_sessions": int(sessions.lt(0).sum()),
                "negative_tickets": int(tickets.lt(0).sum()),
                "negative_amounts": int(amounts.lt(0).sum()),
            },
        },
        {
            "id": "boolean-type",
            "status": "fail" if activation_invalid else "pass",
            "details": {"invalid_lines": activation_invalid},
        },
        {
            "id": "observation-window",
            "status": "fail"
            if incomplete_outcome_values.any() or complete_missing_outcomes.any()
            else "pass",
            "details": {
                "incomplete_windows": int(incomplete_mask.sum()),
                "incomplete_with_outcomes": int(incomplete_outcome_values.sum()),
                "complete_with_missing_required_outcomes": int(complete_missing_outcomes.sum()),
            },
        },
        {
            "id": "app-version-policy",
            "status": "fail" if app_version_invalid.any() else "pass",
            "details": {
                "structural_web_nulls": int(
                    (frame["platform"].eq("web") & frame["app_version"].eq("")).sum()
                ),
                "policy_violations": int(app_version_invalid.sum()),
            },
        },
        {
            "id": "categories",
            "status": "fail" if any(unknown_categories.values()) else "pass",
            "details": unknown_categories,
        },
        {
            "id": "timestamps",
            "status": "fail" if registered.isna().any() or cohort.isna().any() else "pass",
            "details": {
                "invalid_registered_at": int(registered.isna().sum()),
                "invalid_cohort_week": int(cohort.isna().sum()),
            },
        },
    ]
    failures = [check["id"] for check in checks if check["status"] == "fail"]
    activation_blockers = sorted(
        set(failures)
        & {
            "primary-key",
            "observed-days-range",
            "numeric-types",
            "boolean-type",
            "observation-window",
            "timestamps",
        }
    )
    decision_log = [
        "Remove exact duplicate deliveries before user-level aggregation."
        if duplicate_ids
        else "Primary key is unique.",
        (
            f"Exclude {int(incomplete_mask.sum())} incomplete windows from seven-day "
            "activation; do not convert their outcomes to false or zero."
        ),
        (
            "Treat empty app_version for web as structural missingness; report country "
            "missingness separately."
        ),
        (
            "Investigate negative onboarding durations before distribution analysis."
            if onboarding.lt(0).any()
            else "Onboarding duration has no impossible negative values."
        ),
    ]
    return {
        "version": "1.0.0",
        "valid": not failures,
        "ready_for_activation": not activation_blockers,
        "source": {
            "rows": len(frame),
            "unique_users": int(frame["user_id"].nunique()),
            "sha256": source_sha256,
        },
        "schema": {
            "expected_columns": expected_columns,
            "unexpected_columns": unexpected_columns,
        },
        "missingness": missingness,
        "checks": checks,
        "failure_ids": failures,
        "activation_blockers": activation_blockers,
        "decision_log": decision_log,
    }


def render_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit an EDA input before plotting")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--allow-failures", action="store_true")
    args = parser.parse_args(argv)
    try:
        frame = load_frame(args.input)
        contract = load_contract(args.contract)
        report = audit_frame(frame, contract, source_sha256=sha256_file(args.input))
    except AuditError as error:
        sys.stdout.write(render_json({"error": str(error)}))
        return 2
    content = render_json(report)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content, encoding="utf-8")
    sys.stdout.write(content)
    if report["valid"] or args.allow_failures:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
