from __future__ import annotations

import argparse
import codecs
import csv
import hashlib
import io
import json
import sys
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import pandas as pd

SUPPORTED_TYPES = {"string", "integer", "decimal", "timestamp"}
BOMS = (
    (codecs.BOM_UTF32_LE, "utf-32-le"),
    (codecs.BOM_UTF32_BE, "utf-32-be"),
    (codecs.BOM_UTF8, "utf-8"),
    (codecs.BOM_UTF16_LE, "utf-16-le"),
    (codecs.BOM_UTF16_BE, "utf-16-be"),
)


class CsvContractError(ValueError):
    """Raised when a CSV contract or input path cannot be audited."""


def load_contract(path: str | Path) -> dict[str, Any]:
    contract_path = Path(path)
    if not contract_path.is_file():
        raise CsvContractError(f"contract file does not exist: {contract_path}")
    try:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise CsvContractError(f"invalid contract JSON: {error.msg}") from error
    return validate_contract(contract)


def validate_contract(contract: Any) -> dict[str, Any]:
    if not isinstance(contract, dict):
        raise CsvContractError("contract must be a JSON object")

    encoding = contract.get("encoding")
    if not isinstance(encoding, str) or not encoding:
        raise CsvContractError("contract must declare a non-empty encoding")
    try:
        codecs.lookup(encoding)
    except LookupError as error:
        raise CsvContractError(f"unknown encoding: {encoding}") from error

    dialect = contract.get("dialect")
    if not isinstance(dialect, dict):
        raise CsvContractError("contract must declare a dialect object")
    for field in ("delimiter", "quotechar"):
        value = dialect.get(field)
        if not isinstance(value, str) or len(value) != 1:
            raise CsvContractError(f"dialect.{field} must contain one character")
    for field in ("doublequote", "skipinitialspace"):
        if not isinstance(dialect.get(field), bool):
            raise CsvContractError(f"dialect.{field} must be boolean")

    null_values = contract.get("null_values")
    if not isinstance(null_values, list) or not all(
        isinstance(value, str) for value in null_values
    ):
        raise CsvContractError("null_values must be a list of strings")

    number_format = contract.get("number_format")
    if not isinstance(number_format, dict):
        raise CsvContractError("contract must declare number_format")
    decimal_mark = number_format.get("decimal")
    thousands = number_format.get("thousands")
    if not isinstance(decimal_mark, str) or len(decimal_mark) != 1:
        raise CsvContractError("number_format.decimal must contain one character")
    if not isinstance(thousands, str) or len(thousands) > 1:
        raise CsvContractError("number_format.thousands must contain at most one character")
    if thousands and thousands == decimal_mark:
        raise CsvContractError("decimal and thousands separators must differ")

    columns = contract.get("columns")
    if not isinstance(columns, dict) or not columns:
        raise CsvContractError("contract must declare a non-empty columns object")
    for name, column in columns.items():
        if not isinstance(name, str) or not name:
            raise CsvContractError("column names must be non-empty strings")
        if not isinstance(column, dict):
            raise CsvContractError(f"column contract must be an object: {name}")
        if column.get("type") not in SUPPORTED_TYPES:
            raise CsvContractError(f"unsupported type for {name}: {column.get('type')}")
        if not isinstance(column.get("nullable"), bool):
            raise CsvContractError(f"column {name} must declare nullable")

    expected_rows = contract.get("expected_rows")
    if not isinstance(expected_rows, int) or expected_rows < 0:
        raise CsvContractError("expected_rows must be a non-negative integer")
    if contract.get("header") is not True:
        raise CsvContractError("this auditor requires header=true")
    return contract


def detect_bom(raw: bytes) -> str | None:
    for prefix, name in BOMS:
        if raw.startswith(prefix):
            return name
    return None


def parse_decimal(
    value: str,
    *,
    decimal_mark: str,
    thousands: str,
) -> Decimal:
    normalized = value.replace(thousands, "") if thousands else value
    if decimal_mark != ".":
        normalized = normalized.replace(decimal_mark, ".")
    try:
        return Decimal(normalized)
    except InvalidOperation as error:
        raise ValueError(f"invalid decimal: {value!r}") from error


def parse_timestamp(value: str) -> datetime:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        return datetime.fromisoformat(normalized)
    except ValueError as error:
        raise ValueError(f"invalid ISO timestamp: {value!r}") from error


def validate_value(value: str, column: dict[str, Any], contract: dict[str, Any]) -> None:
    value_type = column["type"]
    if value_type == "string":
        return
    if value_type == "integer":
        int(value)
        return
    if value_type == "decimal":
        number_format = contract["number_format"]
        parse_decimal(
            value,
            decimal_mark=number_format["decimal"],
            thousands=number_format["thousands"],
        )
        return
    if value_type == "timestamp":
        parse_timestamp(value)
        return
    raise CsvContractError(f"unsupported type: {value_type}")


def inspect_rows(text: str, contract: dict[str, Any]) -> dict[str, Any]:
    expected_columns = list(contract["columns"])
    dialect = contract["dialect"]
    reader = csv.reader(
        io.StringIO(text, newline=""),
        delimiter=dialect["delimiter"],
        quotechar=dialect["quotechar"],
        doublequote=dialect["doublequote"],
        skipinitialspace=dialect["skipinitialspace"],
        strict=True,
    )

    parse_errors: list[dict[str, Any]] = []
    try:
        header = next(reader)
    except StopIteration:
        header = []
        parse_errors.append({"line": 1, "error": "empty CSV"})
    except csv.Error as error:
        header = []
        parse_errors.append({"line": reader.line_num or 1, "error": str(error)})

    duplicate_headers = sorted({name for name in header if header.count(name) > 1})
    missing_columns = [name for name in expected_columns if name not in header]
    unexpected_columns = [name for name in header if name not in expected_columns]
    order_matches = header == expected_columns

    rows: list[tuple[int, dict[str, str]]] = []
    malformed_rows: list[dict[str, Any]] = []
    data_rows = 0
    if header:
        try:
            for row in reader:
                data_rows += 1
                if len(row) != len(header):
                    malformed_rows.append(
                        {
                            "line": reader.line_num,
                            "expected_fields": len(header),
                            "actual_fields": len(row),
                            "values": row,
                        }
                    )
                    continue
                rows.append((reader.line_num, dict(zip(header, row, strict=True))))
        except csv.Error as error:
            parse_errors.append({"line": reader.line_num, "error": str(error)})

    expected_rows = contract["expected_rows"]
    row_count_matches = data_rows == expected_rows
    header_valid = (
        not duplicate_headers and not missing_columns and not unexpected_columns and order_matches
    )
    return {
        "header": header,
        "expected_header": expected_columns,
        "duplicate_headers": duplicate_headers,
        "missing_columns": missing_columns,
        "unexpected_columns": unexpected_columns,
        "order_matches": order_matches,
        "data_rows": data_rows,
        "expected_rows": expected_rows,
        "row_count_matches": row_count_matches,
        "malformed_rows": malformed_rows[:5],
        "parse_errors": parse_errors,
        "records": rows,
        "valid": header_valid and row_count_matches and not malformed_rows and not parse_errors,
    }


def inspect_columns(
    rows: list[tuple[int, dict[str, str]]],
    contract: dict[str, Any],
) -> dict[str, Any]:
    null_values = set(contract["null_values"])
    report: dict[str, Any] = {}
    for name, column in contract["columns"].items():
        null_count = 0
        invalid: list[dict[str, Any]] = []
        for line, row in rows:
            if name not in row:
                continue
            value = row[name]
            if value in null_values:
                null_count += 1
                if not column["nullable"]:
                    invalid.append({"line": line, "value": value, "error": "null is forbidden"})
                continue
            try:
                validate_value(value, column, contract)
            except (TypeError, ValueError) as error:
                invalid.append({"line": line, "value": value, "error": str(error)})
        report[name] = {
            "type": column["type"],
            "nullable": column["nullable"],
            "null_count": null_count,
            "invalid_count": len(invalid),
            "sample_invalid": invalid[:5],
            "valid": not invalid,
        }
    return report


def inspect_with_pandas(path: Path, contract: dict[str, Any]) -> dict[str, Any]:
    dialect = contract["dialect"]
    try:
        frame = pd.read_csv(
            path,
            encoding=contract["encoding"],
            sep=dialect["delimiter"],
            quotechar=dialect["quotechar"],
            doublequote=dialect["doublequote"],
            skipinitialspace=dialect["skipinitialspace"],
            dtype="string",
            keep_default_na=False,
            na_filter=False,
            on_bad_lines="error",
        )
    except (OSError, UnicodeError, pd.errors.ParserError) as error:
        return {"loaded": False, "error": str(error), "valid": False}
    return {
        "loaded": True,
        "rows": len(frame),
        "columns": frame.columns.tolist(),
        "dtypes": {name: str(dtype) for name, dtype in frame.dtypes.items()},
        "preview": frame.head(3).to_dict(orient="records"),
        "valid": frame.columns.tolist() == list(contract["columns"])
        and len(frame) == contract["expected_rows"],
    }


def audit_csv(input_path: str | Path, contract_path: str | Path) -> dict[str, Any]:
    path = Path(input_path)
    if not path.is_file():
        raise CsvContractError(f"input file does not exist: {path}")
    contract = load_contract(contract_path)
    raw = path.read_bytes()
    encoding_report: dict[str, Any] = {
        "declared": contract["encoding"],
        "bom": detect_bom(raw),
        "valid": True,
        "error": None,
    }
    try:
        text = raw.decode(contract["encoding"], errors="strict")
    except UnicodeDecodeError as error:
        text = None
        encoding_report.update(
            {
                "valid": False,
                "error": f"cannot decode byte {error.start} as {contract['encoding']}",
            }
        )

    if text is None:
        structure = {
            "valid": False,
            "error": "structure was not inspected because decoding failed",
            "records": [],
        }
        columns = {
            name: {
                "type": column["type"],
                "nullable": column["nullable"],
                "null_count": None,
                "invalid_count": None,
                "sample_invalid": [],
                "valid": False,
            }
            for name, column in contract["columns"].items()
        }
        pandas_report = {"loaded": False, "error": "decoding failed", "valid": False}
    else:
        structure = inspect_rows(text, contract)
        columns = inspect_columns(structure["records"], contract)
        pandas_report = inspect_with_pandas(path, contract)

    structure_for_output = {key: value for key, value in structure.items() if key != "records"}
    checks = {
        "encoding": encoding_report["valid"],
        "structure": structure_for_output["valid"],
        "columns": all(column["valid"] for column in columns.values()),
        "pandas": pandas_report["valid"],
    }
    return {
        "source": str(path),
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "encoding": encoding_report,
        "dialect": contract["dialect"],
        "null_values": contract["null_values"],
        "structure": structure_for_output,
        "columns": columns,
        "pandas": pandas_report,
        "summary": {
            "checks": checks,
            "failed_checks": sum(not valid for valid in checks.values()),
            "valid": all(checks.values()),
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit CSV against an explicit contract")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--allow-failures", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        report = audit_csv(args.input, args.contract)
    except (CsvContractError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    if report["summary"]["valid"] or args.allow_failures:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
