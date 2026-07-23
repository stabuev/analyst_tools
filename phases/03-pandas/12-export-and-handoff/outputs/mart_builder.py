from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

import pandas as pd

if __package__:
    from .mart_contracts import (
        OUTPUT_COLUMNS,
        PLAN_CATEGORIES,
        SOURCE_NAMES,
        STATUS_CATEGORIES,
        MartContractError,
    )
    from .mart_delivery import export_delivery, sha256, verify_delivery
    from .mart_pipeline import (
        build_order_mart,
        prepare_item_totals,
        prepare_orders,
        prepare_users,
    )
else:
    from mart_contracts import (
        OUTPUT_COLUMNS,
        PLAN_CATEGORIES,
        SOURCE_NAMES,
        STATUS_CATEGORIES,
        MartContractError,
    )
    from mart_delivery import export_delivery, sha256, verify_delivery
    from mart_pipeline import (
        build_order_mart,
        prepare_item_totals,
        prepare_orders,
        prepare_users,
    )

__all__ = [
    "MartContractError",
    "OUTPUT_COLUMNS",
    "PLAN_CATEGORIES",
    "SOURCE_NAMES",
    "STATUS_CATEGORIES",
    "build_order_mart",
    "export_delivery",
    "prepare_item_totals",
    "prepare_orders",
    "prepare_users",
    "sha256",
    "verify_delivery",
]


def _read_raw_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(
        path,
        dtype="string",
        keep_default_na=False,
        encoding="utf-8",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build or independently verify a checked order-mart delivery"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    build = commands.add_parser("build", help="build and export the delivery")
    build.add_argument("--users", type=Path, required=True)
    build.add_argument("--orders", type=Path, required=True)
    build.add_argument("--items", type=Path, required=True)
    build.add_argument("--output-dir", type=Path, required=True)
    build.add_argument("--business-timezone", required=True)

    verify = commands.add_parser("verify", help="verify an existing delivery")
    verify.add_argument("--output-dir", type=Path, required=True)
    return parser


def run_cli(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "verify":
            report = verify_delivery(args.output_dir)
        else:
            source_paths = {
                "users": args.users,
                "orders": args.orders,
                "order_items": args.items,
            }
            mart, quality = build_order_mart(
                _read_raw_csv(args.users),
                _read_raw_csv(args.orders),
                _read_raw_csv(args.items),
                business_timezone=args.business_timezone,
            )
            manifest = export_delivery(
                mart,
                quality,
                args.output_dir,
                source_paths,
                business_timezone=args.business_timezone,
            )
            report = {
                "valid": True,
                "publish_status": manifest["publish_status"],
                "rows": manifest["dataset"]["rows"],
                "output_dir": str(args.output_dir),
                "artifact_sha256": manifest["artifact"]["sha256"],
            }
    except (OSError, MartContractError) as error:
        parser.error(str(error))
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def main() -> None:
    raise SystemExit(run_cli())


if __name__ == "__main__":
    main()
