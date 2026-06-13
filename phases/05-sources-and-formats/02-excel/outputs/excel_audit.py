from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from openpyxl import load_workbook
from openpyxl.utils.cell import get_column_letter, range_boundaries


class ExcelAuditError(ValueError):
    """Raised when the workbook or extraction specification cannot be audited."""


def load_spec(path: str | Path) -> dict[str, Any]:
    spec_path = Path(path)
    if not spec_path.is_file():
        raise ExcelAuditError(f"spec file does not exist: {spec_path}")
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ExcelAuditError(f"invalid spec JSON: {error.msg}") from error
    required = {
        "sheet",
        "range",
        "header_row",
        "expected_rows",
        "columns",
        "formula_policy",
        "allow_blank_rows",
    }
    missing = required - set(spec)
    if missing:
        raise ExcelAuditError(f"spec misses fields: {sorted(missing)}")
    if spec["formula_policy"] not in {"allow", "forbid_in_range"}:
        raise ExcelAuditError("formula_policy must be allow or forbid_in_range")
    if not isinstance(spec["columns"], list) or not spec["columns"]:
        raise ExcelAuditError("columns must be a non-empty list")
    range_boundaries(spec["range"])
    return spec


def json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def selected_values(sheet: Any, cell_range: str) -> list[list[Any]]:
    min_col, min_row, max_col, max_row = range_boundaries(cell_range)
    return [
        [sheet.cell(row=row, column=column).value for column in range(min_col, max_col + 1)]
        for row in range(min_row, max_row + 1)
    ]


def inspect_with_pandas(path: Path, spec: dict[str, Any]) -> dict[str, Any]:
    min_col, _, max_col, _ = range_boundaries(spec["range"])
    usecols = f"{get_column_letter(min_col)}:{get_column_letter(max_col)}"
    try:
        frame = pd.read_excel(
            path,
            sheet_name=spec["sheet"],
            header=spec["header_row"] - 1,
            usecols=usecols,
            nrows=spec["expected_rows"],
            dtype=object,
            engine="openpyxl",
            keep_default_na=False,
        )
    except (OSError, ValueError) as error:
        return {"loaded": False, "error": str(error), "valid": False}
    columns = [str(column) for column in frame.columns]
    return {
        "loaded": True,
        "rows": len(frame),
        "columns": columns,
        "dtypes": {str(name): str(dtype) for name, dtype in frame.dtypes.items()},
        "preview": [
            {str(key): json_value(value) for key, value in row.items()}
            for row in frame.head(2).to_dict(orient="records")
        ],
        "valid": columns == spec["columns"] and len(frame) == spec["expected_rows"],
    }


def audit_workbook(input_path: str | Path, spec_path: str | Path) -> dict[str, Any]:
    path = Path(input_path)
    if not path.is_file():
        raise ExcelAuditError(f"workbook does not exist: {path}")
    spec = load_spec(spec_path)
    workbook = load_workbook(path, read_only=False, data_only=False)
    sheet_names = workbook.sheetnames
    if spec["sheet"] not in sheet_names:
        return {
            "file": {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()},
            "workbook": {"sheet_names": sheet_names},
            "selection": {"valid": False, "error": f"missing sheet: {spec['sheet']}"},
            "pandas": {"loaded": False, "valid": False},
            "summary": {"valid": False, "failed_checks": 1},
        }

    sheet = workbook[spec["sheet"]]
    min_col, min_row, max_col, max_row = range_boundaries(spec["range"])
    values = selected_values(sheet, spec["range"])
    header_index = spec["header_row"] - min_row
    header = values[header_index] if 0 <= header_index < len(values) else []
    data_rows = values[header_index + 1 :] if header else []
    blank_rows = [
        min_row + header_index + offset
        for offset, row in enumerate(data_rows, start=1)
        if all(value is None for value in row)
    ]
    formulas_in_range = []
    for row in range(min_row, max_row + 1):
        for column in range(min_col, max_col + 1):
            value = sheet.cell(row=row, column=column).value
            if isinstance(value, str) and value.startswith("="):
                formulas_in_range.append(sheet.cell(row=row, column=column).coordinate)
    formulas_all = [
        cell.coordinate
        for row in sheet.iter_rows()
        for cell in row
        if isinstance(cell.value, str) and cell.value.startswith("=")
    ]
    header_matches = header == spec["columns"]
    row_count_matches = len(data_rows) == spec["expected_rows"]
    formula_valid = spec["formula_policy"] == "allow" or not formulas_in_range
    blanks_valid = spec["allow_blank_rows"] or not blank_rows
    pandas_report = inspect_with_pandas(path, spec)
    checks = [
        header_matches,
        row_count_matches,
        formula_valid,
        blanks_valid,
        pandas_report["valid"],
    ]
    selection = {
        "sheet": spec["sheet"],
        "range": spec["range"],
        "header": header,
        "expected_header": spec["columns"],
        "header_matches": header_matches,
        "data_rows": len(data_rows),
        "expected_rows": spec["expected_rows"],
        "row_count_matches": row_count_matches,
        "blank_rows": blank_rows,
        "formulas_in_range": formulas_in_range,
        "valid": all(checks[:-1]),
    }
    return {
        "file": {
            "path": str(path),
            "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        },
        "workbook": {
            "sheet_names": sheet_names,
            "active_sheet": workbook.active.title,
            "merged_ranges": [str(value) for value in sheet.merged_cells.ranges],
            "hidden_columns": [
                name for name, dimension in sheet.column_dimensions.items() if dimension.hidden
            ],
            "formulas": formulas_all,
        },
        "selection": selection,
        "pandas": pandas_report,
        "summary": {
            "valid": all(checks),
            "failed_checks": sum(not check for check in checks),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit an Excel extraction range")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--spec", required=True, type=Path)
    parser.add_argument("--allow-failures", action="store_true")
    args = parser.parse_args()
    try:
        report = audit_workbook(args.input, args.spec)
    except ExcelAuditError as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False))
        raise SystemExit(2) from error
    json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    if not report["summary"]["valid"] and not args.allow_failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
