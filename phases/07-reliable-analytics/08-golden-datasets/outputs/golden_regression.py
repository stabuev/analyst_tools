from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any

GOLDEN_VERSION = "1.0.0"


def read_orders(data_dir: str | Path) -> list[dict[str, str]]:
    with (Path(data_dir) / "orders.csv").open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def semantic_snapshot(data_dir: str | Path) -> dict[str, Any]:
    rows = read_orders(data_dir)
    daily: dict[str, dict[str, int]] = defaultdict(
        lambda: {"order_count": 0, "paid_order_count": 0, "paid_revenue_kopecks": 0}
    )
    statuses: Counter[str] = Counter()
    paid_total = 0
    for row in rows:
        day = row["ordered_at"][:10]
        amount_kopecks = int(Decimal(row["amount_rub"]) * 100)
        statuses[row["status"]] += 1
        daily[day]["order_count"] += 1
        if row["status"] == "paid":
            daily[day]["paid_order_count"] += 1
            daily[day]["paid_revenue_kopecks"] += amount_kopecks
            paid_total += amount_kopecks
    return {
        "golden_version": GOLDEN_VERSION,
        "summary": {
            "order_count": len(rows),
            "paid_order_count": statuses["paid"],
            "paid_revenue_kopecks": paid_total,
            "status_counts": dict(sorted(statuses.items())),
        },
        "daily_metrics": [{"ordered_date": day, **daily[day]} for day in sorted(daily)],
    }


def semantic_diff(expected: Any, actual: Any, path: str = "$") -> list[dict[str, Any]]:
    if isinstance(expected, dict) and isinstance(actual, dict):
        differences: list[dict[str, Any]] = []
        for key in sorted(set(expected) | set(actual)):
            child = f"{path}.{key}"
            if key not in expected:
                differences.append({"path": child, "expected": None, "actual": actual[key]})
            elif key not in actual:
                differences.append({"path": child, "expected": expected[key], "actual": None})
            else:
                differences.extend(semantic_diff(expected[key], actual[key], child))
        return differences
    if isinstance(expected, list) and isinstance(actual, list):
        differences = []
        for index in range(max(len(expected), len(actual))):
            child = f"{path}[{index}]"
            if index >= len(expected):
                differences.append({"path": child, "expected": None, "actual": actual[index]})
            elif index >= len(actual):
                differences.append({"path": child, "expected": expected[index], "actual": None})
            else:
                differences.extend(semantic_diff(expected[index], actual[index], child))
        return differences
    if expected != actual:
        return [{"path": path, "expected": expected, "actual": actual}]
    return []


def compare_with_golden(data_dir: str | Path, golden_path: str | Path) -> dict[str, Any]:
    expected = json.loads(Path(golden_path).read_text(encoding="utf-8"))
    actual = semantic_snapshot(data_dir)
    differences = semantic_diff(expected, actual)
    return {
        "valid": not differences,
        "golden_version": expected.get("golden_version"),
        "difference_count": len(differences),
        "differences": differences,
        "actual": actual,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare semantic output with a reviewed golden")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--golden", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = compare_with_golden(args.data_dir, args.golden)
    except (OSError, ValueError, KeyError) as error:
        report = {"valid": False, "error": {"class": "system_failure", "message": str(error)}}
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    raise SystemExit(0 if report["valid"] else 1)


if __name__ == "__main__":
    main()
