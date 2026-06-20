from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any

DATA_FILES = ("users.csv", "orders.csv", "order_items.csv")

DEFECT_MATRIX = {
    "duplicate_order_id": {
        "class": "grain",
        "file": "orders.csv",
        "mutation": "repeat one complete order row",
        "expected_gates": ["invariant", "pandera", "sql"],
        "materializable": True,
    },
    "blank_user_id": {
        "class": "null_key",
        "file": "orders.csv",
        "mutation": "clear one order user_id",
        "expected_gates": ["invariant", "pandera"],
        "materializable": True,
    },
    "orphan_user": {
        "class": "relationship",
        "file": "orders.csv",
        "mutation": "replace one user_id with U999",
        "expected_gates": ["stage_contract", "sql"],
        "materializable": True,
    },
    "missing_currency_column": {
        "class": "schema_drift",
        "file": "orders.csv",
        "mutation": "remove the currency column",
        "expected_gates": ["invariant", "pandera"],
        "materializable": True,
    },
    "amount_type_drift": {
        "class": "type_drift",
        "file": "orders.csv",
        "mutation": "replace one amount with text",
        "expected_gates": ["parser", "pandera"],
        "materializable": True,
    },
    "negative_amount": {
        "class": "domain",
        "file": "orders.csv",
        "mutation": "make one order amount negative",
        "expected_gates": ["invariant", "pandera"],
        "materializable": True,
    },
    "item_total_mismatch": {
        "class": "reconciliation",
        "file": "order_items.csv",
        "mutation": "increase one item price by one kopeck",
        "expected_gates": ["stage_contract", "sql"],
        "materializable": True,
    },
    "stale_batch": {
        "class": "freshness",
        "file": "orders.csv",
        "mutation": "move all order timestamps thirty days back",
        "expected_gates": ["monitoring"],
        "materializable": True,
    },
    "unknown_config_field": {
        "class": "configuration",
        "file": "config.json",
        "mutation": "add an undeclared key",
        "expected_gates": ["pydantic"],
        "materializable": False,
    },
    "paid_rule_regression": {
        "class": "regression",
        "file": "pipeline code",
        "mutation": "count pending orders as paid revenue",
        "expected_gates": ["golden"],
        "materializable": False,
    },
    "volume_drop": {
        "class": "volume",
        "file": "orders.csv",
        "mutation": "publish a batch below the expected row range",
        "expected_gates": ["monitoring"],
        "materializable": False,
    },
    "failed_atomic_publication": {
        "class": "publication",
        "file": "current.json",
        "mutation": "fail after staging files but before pointer swap",
        "expected_gates": ["integration"],
        "materializable": False,
    },
}


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open(encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        return list(reader), list(reader.fieldnames or [])


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def mutate_duplicate(rows: list[dict[str, str]], fields: list[str]) -> None:
    rows.append(deepcopy(rows[0]))


def mutate_blank_user(rows: list[dict[str, str]], fields: list[str]) -> None:
    rows[0]["user_id"] = ""


def mutate_orphan(rows: list[dict[str, str]], fields: list[str]) -> None:
    rows[0]["user_id"] = "U999"


def mutate_missing_currency(rows: list[dict[str, str]], fields: list[str]) -> None:
    fields.remove("currency")
    for row in rows:
        row.pop("currency")


def mutate_amount_text(rows: list[dict[str, str]], fields: list[str]) -> None:
    rows[0]["amount_rub"] = "not-money"


def mutate_negative_amount(rows: list[dict[str, str]], fields: list[str]) -> None:
    rows[0]["amount_rub"] = "-1.00"


def mutate_item_total(rows: list[dict[str, str]], fields: list[str]) -> None:
    rows[0]["unit_price_rub"] = "700.01"


def mutate_stale_batch(rows: list[dict[str, str]], fields: list[str]) -> None:
    for row in rows:
        row["ordered_at"] = row["ordered_at"].replace("2026-06", "2026-05")


MUTATORS: dict[str, Callable[[list[dict[str, str]], list[str]], None]] = {
    "duplicate_order_id": mutate_duplicate,
    "blank_user_id": mutate_blank_user,
    "orphan_user": mutate_orphan,
    "missing_currency_column": mutate_missing_currency,
    "amount_type_drift": mutate_amount_text,
    "negative_amount": mutate_negative_amount,
    "item_total_mismatch": mutate_item_total,
    "stale_batch": mutate_stale_batch,
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def materialize_defect(
    baseline_dir: str | Path,
    scenario: str,
    output_dir: str | Path,
) -> dict[str, Any]:
    if scenario not in DEFECT_MATRIX:
        raise ValueError(f"unknown scenario: {scenario}")
    if scenario not in MUTATORS:
        raise ValueError(f"scenario is conceptual and cannot be materialized: {scenario}")

    baseline = Path(baseline_dir)
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    for filename in DATA_FILES:
        shutil.copyfile(baseline / filename, target / filename)

    spec = DEFECT_MATRIX[scenario]
    affected = target / str(spec["file"])
    rows, fields = read_csv(affected)
    before_rows = len(rows)
    MUTATORS[scenario](rows, fields)
    write_csv(affected, rows, fields)
    manifest = {
        "scenario": scenario,
        "defect_class": spec["class"],
        "mutation": spec["mutation"],
        "affected_file": affected.name,
        "expected_gates": spec["expected_gates"],
        "row_delta": len(rows) - before_rows,
        "files": {filename: {"sha256": sha256(target / filename)} for filename in DATA_FILES},
    }
    (target / "defect.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def matrix_report() -> dict[str, Any]:
    return {
        "scenario_count": len(DEFECT_MATRIX),
        "materializable_count": len(MUTATORS),
        "scenarios": [
            {"id": scenario_id, **spec} for scenario_id, spec in sorted(DEFECT_MATRIX.items())
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build minimal reliability defect datasets")
    parser.add_argument("--baseline-dir", type=Path)
    parser.add_argument("--scenario", choices=sorted(DEFECT_MATRIX))
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--matrix", action="store_true")
    args = parser.parse_args()
    if args.matrix:
        payload = matrix_report()
    elif args.baseline_dir and args.scenario and args.output_dir:
        try:
            payload = materialize_defect(args.baseline_dir, args.scenario, args.output_dir)
        except ValueError as error:
            parser.error(str(error))
    else:
        parser.error("use --matrix or provide --baseline-dir, --scenario and --output-dir")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
