from __future__ import annotations

import argparse
import hashlib
import json
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup


class HtmlContractError(ValueError):
    """Raised when an HTML extraction contract cannot be applied."""


def load_contract(path: str | Path) -> dict[str, Any]:
    contract_path = Path(path)
    if not contract_path.is_file():
        raise HtmlContractError(f"contract file does not exist: {contract_path}")
    try:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise HtmlContractError(f"invalid contract JSON: {error.msg}") from error
    required = {"record_selector", "record_id_attribute", "expected_records", "fields"}
    missing = required - set(contract)
    if missing:
        raise HtmlContractError(f"contract misses fields: {sorted(missing)}")
    return contract


def convert(value: str, value_type: str) -> str | Decimal:
    if value_type == "string":
        return value
    if value_type == "number":
        try:
            return Decimal(value)
        except InvalidOperation as error:
            raise HtmlContractError(f"invalid number: {value!r}") from error
    raise HtmlContractError(f"unsupported field type: {value_type}")


def extract_html(input_path: str | Path, contract_path: str | Path) -> dict[str, Any]:
    path = Path(input_path)
    if not path.is_file():
        raise HtmlContractError(f"HTML file does not exist: {path}")
    contract = load_contract(contract_path)
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise HtmlContractError(f"HTML is not valid UTF-8 at byte {error.start}") from error
    soup = BeautifulSoup(text, "html.parser")
    nodes = soup.select(contract["record_selector"])
    records: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    selector_counts: dict[str, list[int]] = {name: [] for name in contract["fields"]}
    for position, node in enumerate(nodes, start=1):
        record_id = node.get(contract["record_id_attribute"])
        record: dict[str, Any] = {"order_id": record_id}
        if not record_id:
            errors.append({"record": position, "error": "missing record id attribute"})
        for name, field in contract["fields"].items():
            matches = node.select(field["selector"])
            selector_counts[name].append(len(matches))
            if len(matches) != 1:
                errors.append(
                    {
                        "record": position,
                        "field": name,
                        "selector": field["selector"],
                        "matches": len(matches),
                        "error": "selector must match exactly one node",
                    }
                )
                record[name] = None
                continue
            attribute = field.get("attribute")
            raw_value = matches[0].get(attribute) if attribute else matches[0].get_text(strip=True)
            if raw_value is None:
                errors.append(
                    {"record": position, "field": name, "error": "selected value is missing"}
                )
                record[name] = None
                continue
            try:
                record[name] = convert(str(raw_value).strip(), field["type"])
            except HtmlContractError as error:
                errors.append({"record": position, "field": name, "error": str(error)})
                record[name] = None
        records.append(record)

    ids = [record["order_id"] for record in records if record["order_id"]]
    duplicate_ids = sorted({value for value in ids if ids.count(value) > 1})
    checks = {
        "record_count_matches": len(records) == contract["expected_records"],
        "record_ids_unique": not duplicate_ids,
        "selectors_valid": not errors,
    }
    return {
        "source": {
            "path": str(path),
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "parser": "html.parser",
        },
        "records": records,
        "selector_counts": selector_counts,
        "errors": errors,
        "checks": checks,
        "summary": {
            "valid": all(checks.values()),
            "record_count": len(records),
            "failed_checks": sum(not value for value in checks.values()),
        },
    }


def json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"cannot serialize {type(value).__name__}")


def export_result(result: dict[str, Any], output_dir: str | Path) -> None:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / "orders.jsonl").write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True, default=json_default) + "\n"
            for row in result["records"]
        ),
        encoding="utf-8",
    )
    report = {key: value for key, value in result.items() if key != "records"}
    (output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract HTML records by selector contract")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--allow-failures", action="store_true")
    args = parser.parse_args()
    try:
        result = extract_html(args.input, args.contract)
        if args.output_dir:
            export_result(result, args.output_dir)
    except HtmlContractError as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False))
        raise SystemExit(2) from error
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2, default=json_default)
    sys.stdout.write("\n")
    if not result["summary"]["valid"] and not args.allow_failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
