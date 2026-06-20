from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

MONITOR_VERSION = "1.0.0"


def quality_check(
    check_id: str,
    *,
    observed: float | int,
    operator: str,
    threshold: float | int,
) -> dict[str, Any]:
    if operator == "<=":
        passed = observed <= threshold
    elif operator == ">=":
        passed = observed >= threshold
    else:
        raise ValueError(f"unsupported operator: {operator}")
    return {
        "id": check_id,
        "passed": passed,
        "observed": observed,
        "operator": operator,
        "threshold": threshold,
    }


def evaluate_orders(
    orders: pd.DataFrame,
    thresholds: dict[str, Any],
    observed_at: datetime,
) -> dict[str, Any]:
    required = {"order_id", "user_id", "ordered_at"}
    missing = sorted(required - set(orders.columns))
    if missing:
        raise ValueError(f"missing required columns: {missing}")
    timestamps = pd.to_datetime(orders["ordered_at"], utc=True, errors="coerce")
    if timestamps.isna().any() or orders.empty:
        raise ValueError("ordered_at must contain parseable timezone-aware values")
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("observed_at must be timezone-aware")

    row_count = len(orders)
    blank_key = (
        orders[["order_id", "user_id"]]
        .fillna("")
        .astype(str)
        .apply(lambda column: column.str.strip().eq(""))
        .any(axis=1)
    )
    duplicate_rows = orders["order_id"].duplicated(keep=False)
    latest = timestamps.max().to_pydatetime()
    freshness_delta = observed_at.astimezone(UTC) - latest
    freshness_hours = max(0.0, freshness_delta.total_seconds() / 3600)
    null_rate = float(blank_key.mean())
    duplicate_rate = float(duplicate_rows.mean())
    checks = [
        quality_check(
            "freshness",
            observed=round(freshness_hours, 3),
            operator="<=",
            threshold=thresholds["freshness_hours"],
        ),
        quality_check(
            "volume_min",
            observed=row_count,
            operator=">=",
            threshold=thresholds["min_orders"],
        ),
        quality_check(
            "volume_max",
            observed=row_count,
            operator="<=",
            threshold=thresholds["max_orders"],
        ),
        quality_check(
            "null_key_rate",
            observed=round(null_rate, 6),
            operator="<=",
            threshold=thresholds["max_null_rate"],
        ),
        quality_check(
            "duplicate_order_rate",
            observed=round(duplicate_rate, 6),
            operator="<=",
            threshold=thresholds["max_duplicate_rate"],
        ),
    ]
    valid = all(check["passed"] for check in checks)
    return {
        "monitor_version": MONITOR_VERSION,
        "status": "success" if valid else "failed",
        "failure_class": None if valid else "data_failure",
        "observed_at": observed_at.isoformat(),
        "metrics": {
            "row_count": row_count,
            "latest_ordered_at": latest.isoformat(),
            "freshness_hours": round(freshness_hours, 3),
            "null_key_rate": round(null_rate, 6),
            "duplicate_order_rate": round(duplicate_rate, 6),
        },
        "checks": checks,
    }


def monitor_batch(
    data_dir: str | Path,
    thresholds: dict[str, Any],
    observed_at: datetime,
) -> dict[str, Any]:
    try:
        orders = pd.read_csv(Path(data_dir) / "orders.csv", dtype=str)
        return evaluate_orders(orders, thresholds, observed_at)
    except (OSError, KeyError, TypeError, ValueError) as error:
        return {
            "monitor_version": MONITOR_VERSION,
            "status": "failed",
            "failure_class": "system_failure",
            "observed_at": observed_at.isoformat(),
            "metrics": {},
            "checks": [],
            "error": str(error),
        }


def append_event(log_path: str | Path, report: dict[str, Any]) -> None:
    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "event": "quality_monitor_finished",
        "status": report["status"],
        "failure_class": report["failure_class"],
        "observed_at": report["observed_at"],
        "failed_checks": [check["id"] for check in report.get("checks", []) if not check["passed"]],
        "metrics": report.get("metrics", {}),
    }
    with path.open("a", encoding="utf-8") as output:
        output.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Monitor batch freshness, volume and error rates")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--thresholds", type=Path, required=True)
    parser.add_argument("--observed-at", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--log", type=Path)
    args = parser.parse_args()
    try:
        thresholds = json.loads(args.thresholds.read_text(encoding="utf-8"))
        observed_at = datetime.fromisoformat(args.observed_at)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    report = monitor_batch(args.data_dir, thresholds, observed_at)
    if args.log:
        append_event(args.log, report)
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    raise SystemExit(0 if report["status"] == "success" else 1)


if __name__ == "__main__":
    main()
