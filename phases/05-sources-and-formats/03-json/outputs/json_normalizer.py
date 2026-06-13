from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


class JsonContractError(ValueError):
    """Raised when JSON input or its normalization contract is invalid."""


def load_json(path: str | Path) -> Any:
    source = Path(path)
    if not source.is_file():
        raise JsonContractError(f"file does not exist: {source}")
    try:
        return json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise JsonContractError(f"invalid JSON in {source}: {error.msg}") from error


def load_contract(path: str | Path) -> dict[str, Any]:
    contract = load_json(path)
    if not isinstance(contract, dict):
        raise JsonContractError("contract must be an object")
    required = {"root", "record_grain", "record_fields", "array", "allowed_paths"}
    missing = required - set(contract)
    if missing:
        raise JsonContractError(f"contract misses fields: {sorted(missing)}")
    if not isinstance(contract["record_fields"], dict) or not contract["record_fields"]:
        raise JsonContractError("record_fields must be a non-empty object")
    if not isinstance(contract["array"], dict) or "fields" not in contract["array"]:
        raise JsonContractError("array must declare path, grain and fields")
    return contract


def get_path(value: Any, path: str) -> Any:
    current = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def collect_paths(value: Any, prefix: str = "") -> set[str]:
    paths: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else key
            paths.add(path)
            paths.update(collect_paths(child, path))
    elif isinstance(value, list):
        array_path = f"{prefix}[]"
        paths.add(array_path)
        for child in value:
            paths.update(collect_paths(child, array_path))
    return paths


def type_matches(value: Any, expected: str) -> bool:
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "timestamp":
        if not isinstance(value, str):
            return False
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return False
        return True
    raise JsonContractError(f"unsupported type: {expected}")


def extract_fields(
    source: dict[str, Any],
    fields: dict[str, Any],
    location: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    record: dict[str, Any] = {}
    errors: list[dict[str, Any]] = []
    for output_name, field in fields.items():
        value = get_path(source, field["path"])
        record[output_name] = value
        if value is None:
            if not field["nullable"]:
                errors.append(
                    {"location": location, "field": output_name, "error": "null is forbidden"}
                )
        elif not type_matches(value, field["type"]):
            errors.append(
                {
                    "location": location,
                    "field": output_name,
                    "expected": field["type"],
                    "actual": type(value).__name__,
                    "error": "type mismatch",
                }
            )
    return record, errors


def normalize_json(input_path: str | Path, contract_path: str | Path) -> dict[str, Any]:
    path = Path(input_path)
    payload = load_json(path)
    contract = load_contract(contract_path)
    if not isinstance(payload, dict):
        raise JsonContractError("input root must be an object")
    source_records = payload.get(contract["root"])
    if not isinstance(source_records, list):
        raise JsonContractError(f"root path must contain a list: {contract['root']}")

    records: list[dict[str, Any]] = []
    items: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    observed_paths: set[str] = set()
    array_contract = contract["array"]
    for position, source in enumerate(source_records, start=1):
        if not isinstance(source, dict):
            errors.append({"location": f"record[{position}]", "error": "record is not an object"})
            continue
        observed_paths.update(collect_paths(source))
        record, record_errors = extract_fields(
            source,
            contract["record_fields"],
            f"record[{position}]",
        )
        records.append(record)
        errors.extend(record_errors)
        nested = get_path(source, array_contract["path"])
        if not isinstance(nested, list):
            errors.append(
                {
                    "location": f"record[{position}]",
                    "field": array_contract["path"],
                    "error": "array path is not a list",
                }
            )
            continue
        for item_position, item in enumerate(nested, start=1):
            if not isinstance(item, dict):
                errors.append(
                    {
                        "location": f"record[{position}].{array_contract['path']}[{item_position}]",
                        "error": "item is not an object",
                    }
                )
                continue
            child, child_errors = extract_fields(
                item,
                array_contract["fields"],
                f"record[{position}].{array_contract['path']}[{item_position}]",
            )
            child["event_id"] = record.get("event_id")
            child["item_position"] = item_position
            items.append(child)
            errors.extend(child_errors)

    grain = contract["record_grain"]
    grain_values = [tuple(record.get(name) for name in grain) for record in records]
    duplicate_grain = sorted({value for value in grain_values if grain_values.count(value) > 1})
    unknown_paths = sorted(observed_paths - set(contract["allowed_paths"]))
    checks = {
        "record_grain_unique": not duplicate_grain,
        "types_valid": not errors,
        "schema_paths_known": not unknown_paths,
    }
    return {
        "source": {
            "path": str(path),
            "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        },
        "records": {"grain": grain, "rows": len(records), "data": records},
        "items": {
            "grain": array_contract["grain"],
            "rows": len(items),
            "data": items,
        },
        "schema": {
            "observed_paths": sorted(observed_paths),
            "unknown_paths": unknown_paths,
        },
        "errors": errors[:20],
        "checks": checks,
        "summary": {
            "valid": all(checks.values()),
            "failed_checks": sum(not value for value in checks.values()),
        },
    }


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    content = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)
    path.write_text(content, encoding="utf-8")


def export_result(
    report: dict[str, Any],
    input_path: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    raw_path = output / "raw.json"
    shutil.copyfile(input_path, raw_path)
    write_jsonl(output / "events.jsonl", report["records"]["data"])
    write_jsonl(output / "items.jsonl", report["items"]["data"])
    exported = {key: value for key, value in report.items() if key not in {"records", "items"}}
    exported["records"] = {key: value for key, value in report["records"].items() if key != "data"}
    exported["items"] = {key: value for key, value in report["items"].items() if key != "data"}
    exported["raw_copy_sha256"] = hashlib.sha256(raw_path.read_bytes()).hexdigest()
    (output / "report.json").write_text(
        json.dumps(exported, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return exported


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize nested JSON with an explicit grain")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--allow-failures", action="store_true")
    args = parser.parse_args()
    try:
        report = normalize_json(args.input, args.contract)
        printed = export_result(report, args.input, args.output_dir) if args.output_dir else report
    except JsonContractError as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False))
        raise SystemExit(2) from error
    json.dump(printed, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    if not report["summary"]["valid"] and not args.allow_failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
