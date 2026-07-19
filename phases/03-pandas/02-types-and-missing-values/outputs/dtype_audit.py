from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import pandas as pd


class DtypeContractError(ValueError):
    """Raised when the schema or CLI invocation is invalid."""


SUPPORTED_DTYPES = {"string", "Int64", "Float64", "boolean"}
BOOLEAN_VALUES = {
    "true": True,
    "false": False,
    "1": True,
    "0": False,
    "yes": True,
    "no": False,
}
INT64_MIN = -(2**63)
INT64_MAX = 2**63 - 1


def validate_schema(schema: object) -> dict[str, dict[str, Any]]:
    if not isinstance(schema, Mapping) or not schema:
        raise DtypeContractError("schema must be a non-empty JSON object")

    normalized: dict[str, dict[str, Any]] = {}
    for column, raw_spec in schema.items():
        if not isinstance(column, str) or not column:
            raise DtypeContractError("schema column names must be non-empty strings")
        if not isinstance(raw_spec, Mapping):
            raise DtypeContractError(
                f"schema for {column!r} must contain dtype and nullable"
            )
        unknown = set(raw_spec) - {"dtype", "nullable"}
        if unknown:
            raise DtypeContractError(
                f"schema for {column!r} has unknown fields: {sorted(unknown)}"
            )
        target = raw_spec.get("dtype")
        nullable = raw_spec.get("nullable")
        if target not in SUPPORTED_DTYPES:
            raise DtypeContractError(
                f"unsupported dtype for {column!r}: {target!r}; "
                f"expected one of {sorted(SUPPORTED_DTYPES)}"
            )
        if not isinstance(nullable, bool):
            raise DtypeContractError(
                f"nullable for {column!r} must be true or false"
            )
        normalized[column] = {"dtype": target, "nullable": nullable}
    return normalized


def _as_nullable_text(series: pd.Series) -> pd.Series:
    return series.astype("string")


def _missing_mask(series: pd.Series) -> pd.Series:
    text = _as_nullable_text(series)
    blank = text.str.strip().eq("").fillna(False)
    return (series.isna() | blank).astype(bool)


def _examples(series: pd.Series, mask: pd.Series) -> list[dict[str, str]]:
    examples: list[dict[str, str]] = []
    rows = zip(series.index.tolist(), series.tolist(), mask.tolist(), strict=True)
    for label, value, selected in rows:
        if not selected:
            continue
        examples.append({"row": str(label), "value": str(value)})
        if len(examples) == 5:
            break
    return examples


def _convert_int64(clean: pd.Series) -> tuple[pd.Series, pd.Series]:
    values: list[Any] = []
    invalid_values: list[bool] = []

    for value in clean.tolist():
        if pd.isna(value):
            values.append(pd.NA)
            invalid_values.append(False)
            continue

        try:
            parsed = Decimal(str(value).strip())
        except InvalidOperation:
            values.append(pd.NA)
            invalid_values.append(True)
            continue

        is_valid = (
            parsed.is_finite()
            and parsed == parsed.to_integral_value()
            and INT64_MIN <= parsed <= INT64_MAX
        )
        values.append(int(parsed) if is_valid else pd.NA)
        invalid_values.append(not is_valid)

    converted = pd.Series(
        pd.array(values, dtype="Int64"),
        index=clean.index,
        name=clean.name,
    )
    invalid = pd.Series(invalid_values, index=clean.index, dtype=bool)
    return converted, invalid


def convert_series(
    series: pd.Series,
    *,
    target: str,
    nullable: bool,
) -> tuple[pd.Series, dict[str, Any]]:
    if target not in SUPPORTED_DTYPES:
        raise DtypeContractError(f"unsupported target dtype: {target}")

    source = series.copy()
    text = _as_nullable_text(source)
    missing = _missing_mask(source)
    clean = text.mask(missing, pd.NA)
    invalid = pd.Series(False, index=source.index, dtype=bool)

    if target == "string":
        converted = clean.astype("string")
    elif target == "Int64":
        converted, invalid = _convert_int64(clean)
    elif target == "Float64":
        parsed = pd.to_numeric(clean, errors="coerce")
        invalid = ((~missing) & parsed.isna()).astype(bool)
        non_finite = parsed.isin([float("inf"), float("-inf")])
        invalid = (invalid | non_finite).astype(bool)
        converted = parsed.mask(invalid, pd.NA).astype("Float64")
    elif target == "boolean":
        normalized = clean.str.strip().str.lower()
        parsed = normalized.map(BOOLEAN_VALUES)
        invalid = ((~missing) & parsed.isna()).astype(bool)
        converted = parsed.mask(invalid, pd.NA).astype("boolean")
    else:  # pragma: no cover - guarded by SUPPORTED_DTYPES
        raise DtypeContractError(f"unsupported target dtype: {target}")

    missing_rows = int(missing.sum())
    invalid_rows = int(invalid.sum())
    violations: list[str] = []
    if missing_rows and not nullable:
        violations.append("missing_not_allowed")
    if invalid_rows:
        violations.append("invalid_values")

    report = {
        "source_dtype": str(source.dtype),
        "target_dtype": target,
        "result_dtype": str(converted.dtype),
        "nullable": nullable,
        "missing_rows": missing_rows,
        "missing_examples": _examples(source, missing),
        "invalid_rows": invalid_rows,
        "invalid_examples": _examples(source, invalid),
        "violations": violations,
        "valid": not violations,
    }
    return converted, report


def audit_and_convert(
    frame: pd.DataFrame,
    schema: Mapping[str, Mapping[str, Any]],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    normalized_schema = validate_schema(schema)
    result = frame.copy()
    missing_columns = sorted(set(normalized_schema) - set(frame.columns))
    columns: dict[str, Any] = {}

    for column, spec in normalized_schema.items():
        if column in missing_columns:
            continue
        converted, column_report = convert_series(
            result[column],
            target=spec["dtype"],
            nullable=spec["nullable"],
        )
        result[column] = converted
        columns[column] = column_report

    valid = not missing_columns and all(
        column_report["valid"] for column_report in columns.values()
    )
    report = {
        "valid": valid,
        "rows": len(result),
        "missing_columns": missing_columns,
        "columns": columns,
    }
    return result, report


def _parse_schema(raw_schema: str) -> dict[str, dict[str, Any]]:
    try:
        parsed = json.loads(raw_schema)
    except json.JSONDecodeError as error:
        raise DtypeContractError(f"schema is not valid JSON: {error.msg}") from error
    return validate_schema(parsed)


def run_cli(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit pandas dtypes and per-column missing-value policies"
    )
    parser.add_argument("input", type=Path)
    parser.add_argument(
        "--schema",
        required=True,
        help='JSON object: column -> {"dtype": ..., "nullable": ...}',
    )
    args = parser.parse_args(argv)

    try:
        schema = _parse_schema(args.schema)
        frame = pd.read_csv(
            args.input,
            dtype="string",
            keep_default_na=False,
        )
    except (DtypeContractError, OSError) as error:
        parser.error(str(error))

    _, report = audit_and_convert(frame, schema)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["valid"] else 1


def main() -> None:
    raise SystemExit(run_cli())


if __name__ == "__main__":
    main()
