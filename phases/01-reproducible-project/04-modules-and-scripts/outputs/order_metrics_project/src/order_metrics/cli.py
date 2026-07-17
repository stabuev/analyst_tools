from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Sequence

from .core import DataContractError, load_orders, summarize_orders


def json_value(value: int | Decimal) -> int | str:
    return format(value, "f") if isinstance(value, Decimal) else value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="order-metrics",
        description="Validate an order CSV and calculate revenue metrics",
    )
    parser.add_argument("input", type=Path, help="UTF-8 CSV with order_id and amount")
    parser.add_argument("--output", type=Path, help="Write JSON to this path")
    return parser


def run(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        summary = summarize_orders(load_orders(args.input))
        rendered = json.dumps(
            {name: json_value(value) for name, value in summary.items()},
            ensure_ascii=False,
            indent=2,
        ) + "\n"
        if args.output:
            args.output.write_text(rendered, encoding="utf-8")
        else:
            print(rendered, end="")
        return 0
    except (DataContractError, OSError) as error:
        print(f"order-metrics: {error}", file=sys.stderr)
        return 2


def main() -> None:
    raise SystemExit(run())
