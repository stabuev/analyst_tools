from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from collections.abc import Iterable
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import soupsieve
from bs4 import BeautifulSoup

CONTRACT_VERSION = "2.0.0"
SUPPORTED_PARSER = "html.parser"
SUPPORTED_ENCODING = "utf-8"
DECIMAL_PATTERN = re.compile(r"^[+-]?\d+(?:\.\d+)?$")
TOP_LEVEL_KEYS = {
    "version",
    "parser",
    "encoding",
    "container_selector",
    "record_selector",
    "record_count",
    "record_id",
    "fields",
}


class HtmlContractError(ValueError):
    """Raised when configuration or input bytes cannot be inspected safely."""


def _object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise HtmlContractError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _require_keys(value: Any, expected: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise HtmlContractError(f"{label} must be an object")
    missing = expected - set(value)
    unknown = set(value) - expected
    if missing:
        raise HtmlContractError(f"{label} misses keys: {sorted(missing)}")
    if unknown:
        raise HtmlContractError(f"{label} has unknown keys: {sorted(unknown)}")
    return value


def _non_blank_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HtmlContractError(f"{label} must be a non-blank string")
    return value


def _validate_selector(value: Any, label: str) -> str:
    selector = _non_blank_string(value, label)
    try:
        soupsieve.compile(selector)
    except soupsieve.SelectorSyntaxError as error:
        raise HtmlContractError(f"{label} is not a valid CSS selector: {error}") from error
    return selector


def _parse_contract(raw: bytes) -> dict[str, Any]:
    try:
        text = raw.decode(SUPPORTED_ENCODING, errors="strict")
    except UnicodeDecodeError as error:
        raise HtmlContractError(f"contract is not valid UTF-8 at byte {error.start}") from error
    try:
        value = json.loads(text, object_pairs_hook=_object_without_duplicates)
    except json.JSONDecodeError as error:
        raise HtmlContractError(f"invalid contract JSON: {error.msg}") from error

    contract = _require_keys(value, TOP_LEVEL_KEYS, "contract")
    if contract["version"] != CONTRACT_VERSION:
        raise HtmlContractError(
            f"unsupported contract version: {contract['version']!r}; expected {CONTRACT_VERSION!r}"
        )
    if contract["parser"] != SUPPORTED_PARSER:
        raise HtmlContractError(
            f"unsupported parser: {contract['parser']!r}; expected {SUPPORTED_PARSER!r}"
        )
    if str(contract["encoding"]).lower() != SUPPORTED_ENCODING:
        raise HtmlContractError(
            f"unsupported encoding: {contract['encoding']!r}; expected {SUPPORTED_ENCODING!r}"
        )
    _validate_selector(contract["container_selector"], "container_selector")
    _validate_selector(contract["record_selector"], "record_selector")

    count = _require_keys(contract["record_count"], {"mode", "value"}, "record_count")
    if count["mode"] not in {"exact", "min"}:
        raise HtmlContractError("record_count.mode must be 'exact' or 'min'")
    if isinstance(count["value"], bool) or not isinstance(count["value"], int):
        raise HtmlContractError("record_count.value must be an integer")
    if count["value"] < 1:
        raise HtmlContractError("record_count.value must be at least 1")

    record_id = _require_keys(contract["record_id"], {"name", "attribute"}, "record_id")
    _non_blank_string(record_id["name"], "record_id.name")
    _non_blank_string(record_id["attribute"], "record_id.attribute")

    fields = contract["fields"]
    if not isinstance(fields, dict) or not fields:
        raise HtmlContractError("fields must be a non-empty object")
    if record_id["name"] in fields:
        raise HtmlContractError("record_id.name must not collide with a field name")
    for name, raw_field in fields.items():
        _non_blank_string(name, "field name")
        if not isinstance(raw_field, dict):
            raise HtmlContractError(f"field {name!r} must be an object")
        source = raw_field.get("source")
        expected_keys = {"selector", "source", "type", "non_blank"}
        if source == "attribute":
            expected_keys.add("attribute")
        field = _require_keys(raw_field, expected_keys, f"field {name!r}")
        _validate_selector(field["selector"], f"field {name!r}.selector")
        if source not in {"text", "attribute"}:
            raise HtmlContractError(f"field {name!r}.source must be 'text' or 'attribute'")
        if source == "attribute":
            _non_blank_string(field["attribute"], f"field {name!r}.attribute")
        if field["type"] not in {"string", "decimal"}:
            raise HtmlContractError(f"field {name!r}.type must be 'string' or 'decimal'")
        if not isinstance(field["non_blank"], bool):
            raise HtmlContractError(f"field {name!r}.non_blank must be boolean")
    return contract


def load_contract(path: str | Path) -> dict[str, Any]:
    contract_path = Path(path)
    try:
        raw = contract_path.read_bytes()
    except OSError as error:
        raise HtmlContractError(
            f"cannot read contract file {contract_path.name!r}: {error}"
        ) from error
    return _parse_contract(raw)


def _convert(value: str, value_type: str) -> str | Decimal:
    if value_type == "string":
        return value
    if value_type == "decimal":
        if not DECIMAL_PATTERN.fullmatch(value):
            raise HtmlContractError(f"invalid decimal: {value!r}")
        try:
            number = Decimal(value)
        except InvalidOperation as error:
            raise HtmlContractError(f"invalid decimal: {value!r}") from error
        if not number.is_finite():
            raise HtmlContractError(f"decimal must be finite: {value!r}")
        return number
    raise HtmlContractError(f"unsupported field type: {value_type}")


def _record_count_matches(actual: int, policy: dict[str, Any]) -> bool:
    if policy["mode"] == "exact":
        return actual == policy["value"]
    return actual >= policy["value"]


def extract_html(
    input_path: str | Path,
    contract_path: str | Path,
    *,
    max_bytes: int = 5_000_000,
) -> dict[str, Any]:
    """Audit one saved HTML document without publishing partial records."""

    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1:
        raise HtmlContractError("max_bytes must be a positive integer")
    path = Path(input_path)
    contract_file = Path(contract_path)
    try:
        contract_raw = contract_file.read_bytes()
    except OSError as error:
        raise HtmlContractError(
            f"cannot read contract file {contract_file.name!r}: {error}"
        ) from error
    contract = _parse_contract(contract_raw)
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise HtmlContractError(f"cannot read HTML file {path.name!r}: {error}") from error
    if len(raw) > max_bytes:
        raise HtmlContractError(f"HTML exceeds max_bytes: {len(raw)} > {max_bytes}")
    try:
        text = raw.decode(SUPPORTED_ENCODING, errors="strict")
    except UnicodeDecodeError as error:
        raise HtmlContractError(f"HTML is not valid UTF-8 at byte {error.start}") from error

    soup = BeautifulSoup(text, contract["parser"])
    containers = soup.select(contract["container_selector"])
    charset_nodes = soup.select("meta[charset]")
    charset_matches = len(charset_nodes) == 1 and str(
        charset_nodes[0].get("charset", "")
    ).lower() in {"utf-8", "utf8"}
    errors: list[dict[str, Any]] = []
    if not charset_matches:
        errors.append(
            {
                "kind": "document",
                "field": "charset",
                "matches": len(charset_nodes),
                "error": "expected exactly one UTF-8 meta charset declaration",
            }
        )
    if len(containers) != 1:
        errors.append(
            {
                "kind": "container",
                "selector": contract["container_selector"],
                "matches": len(containers),
                "error": "container selector must match exactly one node",
            }
        )
    nodes = containers[0].select(contract["record_selector"]) if len(containers) == 1 else []
    count_matches = _record_count_matches(len(nodes), contract["record_count"])
    if not count_matches:
        errors.append(
            {
                "kind": "record_count",
                "actual": len(nodes),
                "policy": contract["record_count"],
                "error": "record count does not satisfy the contract",
            }
        )

    records: list[dict[str, Any]] = []
    selector_counts: dict[str, list[int]] = {name: [] for name in contract["fields"]}
    present_ids = True
    fields_valid = True
    id_name = contract["record_id"]["name"]
    id_attribute = contract["record_id"]["attribute"]
    for position, node in enumerate(nodes, start=1):
        raw_id = node.get(id_attribute)
        record_id = str(raw_id).strip() if raw_id is not None else ""
        record: dict[str, Any] = {id_name: record_id or None}
        if not record_id:
            present_ids = False
            errors.append(
                {
                    "kind": "record_id",
                    "record": position,
                    "attribute": id_attribute,
                    "error": "record id attribute is missing or blank",
                }
            )
        for name, field in contract["fields"].items():
            matches = node.select(field["selector"])
            selector_counts[name].append(len(matches))
            if len(matches) != 1:
                fields_valid = False
                errors.append(
                    {
                        "kind": "field",
                        "record": position,
                        "record_id": record_id or None,
                        "field": name,
                        "selector": field["selector"],
                        "matches": len(matches),
                        "error": "field selector must match exactly one node",
                    }
                )
                record[name] = None
                continue
            match = matches[0]
            if field["source"] == "text":
                raw_value: Any = match.get_text(" ", strip=True)
            else:
                raw_value = match.get(field["attribute"])
            value = str(raw_value).strip() if raw_value is not None else ""
            if field["non_blank"] and not value:
                fields_valid = False
                errors.append(
                    {
                        "kind": "field",
                        "record": position,
                        "record_id": record_id or None,
                        "field": name,
                        "error": "selected value is missing or blank",
                    }
                )
                record[name] = None
                continue
            try:
                record[name] = _convert(value, field["type"])
            except HtmlContractError as error:
                fields_valid = False
                errors.append(
                    {
                        "kind": "field",
                        "record": position,
                        "record_id": record_id or None,
                        "field": name,
                        "error": str(error),
                    }
                )
                record[name] = None
        records.append(record)

    ids = [record[id_name] for record in records if record[id_name] is not None]
    duplicate_ids = sorted({value for value in ids if ids.count(value) > 1})
    if duplicate_ids:
        errors.append(
            {
                "kind": "grain",
                "field": id_name,
                "values": duplicate_ids,
                "error": "record ids must be unique",
            }
        )
    checks = {
        "charset_declaration_matches": charset_matches,
        "container_exactly_one": len(containers) == 1,
        "record_count_matches": count_matches,
        "record_ids_present": present_ids and bool(nodes),
        "record_ids_unique": not duplicate_ids,
        "required_fields_valid": fields_valid and bool(nodes),
    }
    failed_checks = [name for name, passed in checks.items() if not passed]
    return {
        "source": {
            "file_name": path.name,
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "parser": contract["parser"],
            "encoding": SUPPORTED_ENCODING,
        },
        "contract": contract,
        "contract_source": {
            "file_name": contract_file.name,
            "sha256": hashlib.sha256(contract_raw).hexdigest(),
        },
        "records": records,
        "selector_counts": {
            "containers": len(containers),
            "records": len(nodes),
            "fields": selector_counts,
        },
        "errors": errors,
        "checks": checks,
        "summary": {
            "valid": not failed_checks,
            "published": False,
            "record_count": len(records),
            "failed_checks": failed_checks,
        },
    }


def json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"cannot serialize {type(value).__name__}")


def publish_snapshot(result: dict[str, Any], output: str | Path) -> Path:
    """Atomically publish one self-contained snapshot after a successful audit."""

    if not result.get("summary", {}).get("valid"):
        raise HtmlContractError("an invalid extraction result cannot be published")
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    published = json.loads(json.dumps(result, ensure_ascii=False, default=json_default))
    published["summary"]["published"] = True
    payload = json.dumps(published, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".part", dir=target.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return target


def extract_and_publish(
    input_path: str | Path,
    contract_path: str | Path,
    output: str | Path,
    *,
    max_bytes: int = 5_000_000,
) -> dict[str, Any]:
    result = extract_html(input_path, contract_path, max_bytes=max_bytes)
    publish_snapshot(result, output)
    result["summary"]["published"] = True
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit and publish saved HTML records")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--max-bytes", type=int, default=5_000_000)
    parser.add_argument(
        "--allow-failures",
        action="store_true",
        help="return zero for a failed audit; invalid records are still never published",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        result = extract_html(
            arguments.input,
            arguments.contract,
            max_bytes=arguments.max_bytes,
        )
        if result["summary"]["valid"] and arguments.output:
            publish_snapshot(result, arguments.output)
            result["summary"]["published"] = True
    except HtmlContractError as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False, indent=2))
        return 2
    except OSError as error:
        print(
            json.dumps({"error": f"cannot publish snapshot: {error}"}, ensure_ascii=False, indent=2)
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, default=json_default))
    if not result["summary"]["valid"] and not arguments.allow_failures:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
