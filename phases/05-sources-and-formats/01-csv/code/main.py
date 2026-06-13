from __future__ import annotations

import csv
import io
import json
from decimal import Decimal
from pathlib import Path

import pandas as pd

LESSON_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = LESSON_ROOT.parent / "data"
INPUT = DATA_ROOT / "tiny" / "orders_semicolon_cp1251.csv"
CONTRACT = DATA_ROOT / "contract.json"


def normalize_decimal(value: str, decimal_mark: str, thousands: str) -> Decimal:
    normalized = value.replace(thousands, "").replace(decimal_mark, ".")
    return Decimal(normalized)


def main() -> None:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    text = INPUT.read_bytes().decode(contract["encoding"], errors="strict")
    dialect = contract["dialect"]

    naive_header = next(csv.reader(io.StringIO(text)))
    explicit_rows = list(
        csv.DictReader(
            io.StringIO(text),
            delimiter=dialect["delimiter"],
            quotechar=dialect["quotechar"],
        )
    )
    number_format = contract["number_format"]
    manual_total = sum(
        (
            normalize_decimal(
                row["amount"],
                number_format["decimal"],
                number_format["thousands"],
            )
            for row in explicit_rows
        ),
        start=Decimal("0"),
    )

    frame = pd.read_csv(
        INPUT,
        encoding=contract["encoding"],
        sep=dialect["delimiter"],
        quotechar=dialect["quotechar"],
        dtype="string",
        keep_default_na=False,
        na_filter=False,
        on_bad_lines="error",
    )
    print(
        json.dumps(
            {
                "naive_header_fields": len(naive_header),
                "explicit_header_fields": len(frame.columns),
                "rows": len(frame),
                "manual_amount_total": str(manual_total),
                "quoted_delimiter_comment": frame.loc[1, "comment"],
                "raw_missing_tokens": frame["comment"].iloc[2:4].tolist(),
                "pandas_dtypes": {name: str(dtype) for name, dtype in frame.dtypes.items()},
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
