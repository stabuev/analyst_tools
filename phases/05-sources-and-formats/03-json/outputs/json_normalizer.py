from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

SUPPORTED_TYPES = {"string", "integer", "number", "timestamp"}
UNKNOWN_PATH_POLICIES = {"error", "warn"}
MISSING = object()


class JsonContractError(ValueError):
    """Raised when JSON input, the contract, or delivery cannot be processed."""


def read_bytes(path: str | Path, *, label: str) -> tuple[Path, bytes]:
    source = Path(path)
    if not source.is_file():
        raise JsonContractError(f"{label} file does not exist: {source}")
    try:
        return source, source.read_bytes()
    except OSError as error:
        raise JsonContractError(f"cannot read {label} file {source}: {error}") from error


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise JsonContractError(f"duplicate object key: {key}")
        result[key] = value
    return result


def reject_non_finite_number(value: str) -> None:
    raise JsonContractError(f"non-finite number is not valid JSON: {value}")


def parse_json_bytes(raw: bytes, *, label: str) -> Any:
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise JsonContractError(f"{label} is not valid UTF-8 at byte {error.start}") from error
    try:
        return json.loads(
            text,
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_non_finite_number,
        )
    except JsonContractError:
        raise
    except json.JSONDecodeError as error:
        raise JsonContractError(
            f"invalid JSON in {label} at line {error.lineno}, column {error.colno}: {error.msg}"
        ) from error


def validate_path(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise JsonContractError(f"{label} must be a non-empty dotted path")
    if "[]" in value or any(not part for part in value.split(".")):
        raise JsonContractError(f"{label} must use non-empty object keys separated by dots")
    return value


def validate_fields(value: Any, *, label: str) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict) or not value:
        raise JsonContractError(f"{label} must be a non-empty object")
    for output_name, field in value.items():
        if not isinstance(output_name, str) or not output_name:
            raise JsonContractError(f"{label} names must be non-empty strings")
        if not isinstance(field, dict):
            raise JsonContractError(f"{label}.{output_name} must be an object")
        validate_path(field.get("path"), label=f"{label}.{output_name}.path")
        if field.get("type") not in SUPPORTED_TYPES:
            raise JsonContractError(
                f"{label}.{output_name} has unsupported type: {field.get('type')!r}"
            )
        for property_name in ("required", "nullable"):
            if not isinstance(field.get(property_name), bool):
                raise JsonContractError(f"{label}.{output_name}.{property_name} must be boolean")
        if field["type"] == "timestamp" and not isinstance(
            field.get("require_timezone"),
            bool,
        ):
            raise JsonContractError(
                f"{label}.{output_name} timestamp must declare require_timezone"
            )
    return value


def full_path(prefix: str, relative: str) -> str:
    return f"{prefix}.{relative}" if relative else prefix


def load_contract(path: str | Path) -> dict[str, Any]:
    source, raw = read_bytes(path, label="contract")
    contract = parse_json_bytes(raw, label=str(source))
    if not isinstance(contract, dict):
        raise JsonContractError("contract must be an object")
    required = {
        "root_path",
        "envelope_fields",
        "record_grain",
        "record_fields",
        "array",
        "unknown_path_policy",
        "allowed_paths",
    }
    missing = required - set(contract)
    if missing:
        raise JsonContractError(f"contract misses fields: {sorted(missing)}")

    root_path = validate_path(contract["root_path"], label="root_path")
    envelope_fields = validate_fields(
        contract["envelope_fields"],
        label="envelope_fields",
    )
    record_fields = validate_fields(contract["record_fields"], label="record_fields")
    record_grain = contract["record_grain"]
    if (
        not isinstance(record_grain, list)
        or not record_grain
        or len(record_grain) != len(set(record_grain))
        or not all(isinstance(name, str) and name in record_fields for name in record_grain)
    ):
        raise JsonContractError(
            "record_grain must be a non-empty list of unique record field names"
        )
    for name in record_grain:
        field = record_fields[name]
        if not field["required"] or field["nullable"]:
            raise JsonContractError(f"record grain field {name} must be required and non-nullable")

    array = contract["array"]
    required_array_fields = {
        "path",
        "required",
        "nullable",
        "position_field",
        "grain",
        "fields",
    }
    if not isinstance(array, dict):
        raise JsonContractError("array must be an object")
    missing_array_fields = required_array_fields - set(array)
    if missing_array_fields:
        raise JsonContractError(f"array misses fields: {sorted(missing_array_fields)}")
    array_path = validate_path(array["path"], label="array.path")
    for property_name in ("required", "nullable"):
        if not isinstance(array[property_name], bool):
            raise JsonContractError(f"array.{property_name} must be boolean")
    position_field = array["position_field"]
    if not isinstance(position_field, str) or not position_field:
        raise JsonContractError("array.position_field must be a non-empty string")
    child_fields = validate_fields(array["fields"], label="array.fields")
    if position_field in child_fields or position_field in record_grain:
        raise JsonContractError("array.position_field collides with an output field")
    collisions = set(record_grain) & set(child_fields)
    if collisions:
        raise JsonContractError(
            f"array fields collide with parent grain fields: {sorted(collisions)}"
        )
    expected_child_grain = [*record_grain, position_field]
    if array["grain"] != expected_child_grain:
        raise JsonContractError(
            f"array.grain must equal parent grain plus position field: {expected_child_grain}"
        )

    if contract["unknown_path_policy"] not in UNKNOWN_PATH_POLICIES:
        raise JsonContractError("unknown_path_policy must be error or warn")
    allowed_paths = contract["allowed_paths"]
    if (
        not isinstance(allowed_paths, list)
        or not allowed_paths
        or len(allowed_paths) != len(set(allowed_paths))
        or not all(isinstance(value, str) and value for value in allowed_paths)
    ):
        raise JsonContractError("allowed_paths must be a non-empty list of unique strings")

    record_prefix = f"{root_path}[]"
    array_prefix = full_path(record_prefix, array_path)
    declared_paths = {
        root_path,
        f"{root_path}[]",
        *[field["path"] for field in envelope_fields.values()],
        *[full_path(record_prefix, field["path"]) for field in record_fields.values()],
        array_prefix,
        f"{array_prefix}[]",
        *[full_path(f"{array_prefix}[]", field["path"]) for field in child_fields.values()],
    }
    absent_from_inventory = declared_paths - set(allowed_paths)
    if absent_from_inventory:
        raise JsonContractError(
            f"allowed_paths misses declared paths: {sorted(absent_from_inventory)}"
        )
    return contract


def get_path(value: Any, path: str, *, default: Any = MISSING) -> Any:
    current = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return default
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


def json_type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def type_matches(value: Any, field: dict[str, Any]) -> bool:
    expected = field["type"]
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        if isinstance(value, int) and not isinstance(value, bool):
            return True
        return isinstance(value, float) and math.isfinite(value)
    if expected == "timestamp":
        if not isinstance(value, str):
            return False
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return False
        return not field["require_timezone"] or parsed.utcoffset() is not None
    raise JsonContractError(f"unsupported type: {expected}")


def extract_fields(
    source: dict[str, Any],
    fields: dict[str, dict[str, Any]],
    location: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    record: dict[str, Any] = {}
    errors: list[dict[str, Any]] = []
    for output_name, field in fields.items():
        value = get_path(source, field["path"])
        if value is MISSING:
            record[output_name] = None
            if field["required"]:
                errors.append(
                    {
                        "location": location,
                        "field": output_name,
                        "path": field["path"],
                        "error": "missing required path",
                    }
                )
            continue
        record[output_name] = value
        if value is None:
            if not field["nullable"]:
                errors.append(
                    {
                        "location": location,
                        "field": output_name,
                        "path": field["path"],
                        "error": "null is forbidden",
                    }
                )
        elif not type_matches(value, field):
            errors.append(
                {
                    "location": location,
                    "field": output_name,
                    "path": field["path"],
                    "expected": field["type"],
                    "actual": json_type_name(value),
                    "error": "type mismatch",
                }
            )
    return record, errors


def inspect_grain(
    rows: list[dict[str, Any]],
    grain: list[str],
) -> dict[str, Any]:
    first_seen: dict[tuple[Any, ...], int] = {}
    null_rows = []
    duplicate_rows = []
    for position, row in enumerate(rows, start=1):
        value = tuple(row.get(name) for name in grain)
        if any(part is None for part in value):
            null_rows.append(position)
        elif value in first_seen:
            duplicate_rows.append(
                {
                    "row": position,
                    "duplicates_row": first_seen[value],
                    "value": list(value),
                }
            )
        else:
            first_seen[value] = position
    return {
        "columns": grain,
        "null_rows": null_rows,
        "duplicate_rows": duplicate_rows,
        "valid": not null_rows and not duplicate_rows,
    }


def normalize_json(input_path: str | Path, contract_path: str | Path) -> dict[str, Any]:
    path, raw = read_bytes(input_path, label="input")
    payload = parse_json_bytes(raw, label=str(path))
    contract = load_contract(contract_path)
    errors: list[dict[str, Any]] = []

    if isinstance(payload, dict):
        envelope, envelope_errors = extract_fields(
            payload,
            contract["envelope_fields"],
            "document",
        )
        errors.extend(envelope_errors)
    else:
        envelope = {name: None for name in contract["envelope_fields"]}
        errors.append(
            {
                "location": "document",
                "expected": "object",
                "actual": json_type_name(payload),
                "error": "input root is not an object",
            }
        )

    source_records = get_path(payload, contract["root_path"])
    if source_records is MISSING:
        errors.append(
            {
                "location": "document",
                "path": contract["root_path"],
                "error": "missing root path",
            }
        )
        source_records = []
    elif not isinstance(source_records, list):
        errors.append(
            {
                "location": "document",
                "path": contract["root_path"],
                "expected": "array",
                "actual": json_type_name(source_records),
                "error": "root path is not an array",
            }
        )
        source_records = []

    records: list[dict[str, Any]] = []
    items: list[dict[str, Any]] = []
    array_contract = contract["array"]
    for record_position, source in enumerate(source_records, start=1):
        record_location = f"{contract['root_path']}[{record_position}]"
        if not isinstance(source, dict):
            errors.append(
                {
                    "location": record_location,
                    "expected": "object",
                    "actual": json_type_name(source),
                    "error": "record is not an object",
                }
            )
            continue
        record, record_errors = extract_fields(
            source,
            contract["record_fields"],
            record_location,
        )
        records.append(record)
        errors.extend(record_errors)

        nested = get_path(source, array_contract["path"])
        if nested is MISSING:
            if array_contract["required"]:
                errors.append(
                    {
                        "location": record_location,
                        "path": array_contract["path"],
                        "error": "missing required array path",
                    }
                )
            continue
        if nested is None:
            if not array_contract["nullable"]:
                errors.append(
                    {
                        "location": record_location,
                        "path": array_contract["path"],
                        "error": "null array is forbidden",
                    }
                )
            continue
        if not isinstance(nested, list):
            errors.append(
                {
                    "location": record_location,
                    "path": array_contract["path"],
                    "expected": "array",
                    "actual": json_type_name(nested),
                    "error": "array path has wrong type",
                }
            )
            continue
        for item_position, item in enumerate(nested, start=1):
            item_location = f"{record_location}.{array_contract['path']}[{item_position}]"
            if not isinstance(item, dict):
                errors.append(
                    {
                        "location": item_location,
                        "expected": "object",
                        "actual": json_type_name(item),
                        "error": "array item is not an object",
                    }
                )
                continue
            child, child_errors = extract_fields(
                item,
                array_contract["fields"],
                item_location,
            )
            child = {
                **{name: record.get(name) for name in contract["record_grain"]},
                array_contract["position_field"]: item_position,
                **child,
            }
            items.append(child)
            errors.extend(child_errors)

    observed_paths = collect_paths(payload)
    unknown_paths = sorted(observed_paths - set(contract["allowed_paths"]))
    record_grain = inspect_grain(records, contract["record_grain"])
    child_grain = inspect_grain(items, array_contract["grain"])
    fields_and_shape_valid = not errors
    paths_valid = not unknown_paths or contract["unknown_path_policy"] == "warn"
    checks = {
        "fields_and_shape_valid": fields_and_shape_valid,
        "record_grain_valid": record_grain["valid"],
        "child_grain_valid": child_grain["valid"],
        "schema_paths_allowed": paths_valid,
    }
    failed_checks = [name for name, valid in checks.items() if not valid]
    warnings = []
    if unknown_paths and contract["unknown_path_policy"] == "warn":
        warnings.append(
            {
                "warning": "unknown paths accepted by policy",
                "paths": unknown_paths,
            }
        )
    missing_required_paths = [
        {
            "location": error["location"],
            "field": error.get("field"),
            "path": error.get("path"),
        }
        for error in errors
        if error["error"] in {"missing required path", "missing required array path"}
    ]
    return {
        "source": {
            "path": str(path),
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        },
        "envelope": {"data": envelope},
        "records": {
            "grain": record_grain,
            "rows": len(records),
            "data": records,
        },
        "items": {
            "grain": child_grain,
            "rows": len(items),
            "data": items,
        },
        "schema": {
            "unknown_path_policy": contract["unknown_path_policy"],
            "observed_paths": sorted(observed_paths),
            "unknown_paths": unknown_paths,
            "missing_required_paths": missing_required_paths,
        },
        "error_count": len(errors),
        "errors": errors[:20],
        "errors_truncated": len(errors) > 20,
        "warnings": warnings,
        "checks": checks,
        "summary": {
            "valid": not failed_checks,
            "failed_checks": failed_checks,
            "failed_check_count": len(failed_checks),
        },
    }


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    content = "".join(
        json.dumps(
            row,
            ensure_ascii=False,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
        for row in rows
    )
    path.write_text(content, encoding="utf-8")


def file_facts(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    return {
        "path": path.name,
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def export_result(
    report: dict[str, Any],
    input_path: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    if not report["summary"]["valid"]:
        raise JsonContractError("refusing to export normalized rows from an invalid report")
    source, raw = read_bytes(input_path, label="input")
    if hashlib.sha256(raw).hexdigest() != report["source"]["sha256"]:
        raise JsonContractError(f"input changed after normalization: {source}")

    output = Path(output_dir)
    if output.exists():
        if not output.is_dir():
            raise JsonContractError(f"output path is not a directory: {output}")
        if any(output.iterdir()):
            raise JsonContractError(f"output directory must be empty: {output}")
    try:
        output.mkdir(parents=True, exist_ok=True)
        raw_path = output / "raw.json"
        events_path = output / "events.jsonl"
        items_path = output / "items.jsonl"
        raw_path.write_bytes(raw)
        write_jsonl(events_path, report["records"]["data"])
        write_jsonl(items_path, report["items"]["data"])
        exported = {key: value for key, value in report.items() if key not in {"records", "items"}}
        exported["records"] = {
            key: value for key, value in report["records"].items() if key != "data"
        }
        exported["items"] = {key: value for key, value in report["items"].items() if key != "data"}
        exported["delivery"] = {
            "written": True,
            "files": [
                file_facts(raw_path),
                file_facts(events_path),
                file_facts(items_path),
            ],
        }
        report_path = output / "report.json"
        report_path.write_text(
            json.dumps(
                exported,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            + "\n",
            encoding="utf-8",
        )
    except OSError as error:
        raise JsonContractError(f"cannot write delivery {output}: {error}") from error
    return exported


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize one parent and one child JSON grain")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--allow-failures", action="store_true")
    args = parser.parse_args()
    try:
        report = normalize_json(args.input, args.contract)
        if args.output_dir and report["summary"]["valid"]:
            printed = export_result(report, args.input, args.output_dir)
        else:
            if args.output_dir:
                report["delivery"] = {
                    "written": False,
                    "reason": "normalization report is invalid",
                }
            printed = report
    except JsonContractError as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False))
        raise SystemExit(2) from error
    json.dump(
        printed,
        sys.stdout,
        ensure_ascii=False,
        indent=2,
        allow_nan=False,
    )
    sys.stdout.write("\n")
    if not report["summary"]["valid"] and not args.allow_failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
