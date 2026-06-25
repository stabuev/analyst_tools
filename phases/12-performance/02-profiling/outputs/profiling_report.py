from __future__ import annotations

import argparse
import cProfile
import json
import platform
import pstats
import random
import sys
import time
import tracemalloc
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Any


class ProfilingError(ValueError):
    """Raised when a profiling run cannot produce trustworthy evidence."""


OrderLine = dict[str, Any]
PipelineResult = list[dict[str, Any]]
Pipeline = Callable[[list[OrderLine]], PipelineResult]


def generate_order_lines(rows: int, seed: int) -> list[OrderLine]:
    if rows <= 0:
        raise ProfilingError("rows must be positive")

    rng = random.Random(seed)
    statuses = ("paid", "paid", "paid", "paid", "pending", "refunded")
    platforms = ("web", "ios", "android")
    lines: list[OrderLine] = []
    for index in range(rows):
        unit_price_cents = rng.randrange(199, 25_000)
        quantity = rng.randrange(1, 5)
        discount_bps = rng.choice((0, 0, 0, 250, 500, 1000))
        status = statuses[rng.randrange(len(statuses))]
        lines.append(
            {
                "order_id": f"O{index // 3:07d}",
                "line_number": index % 3 + 1,
                "user_id": f"U{rng.randrange(1, max(2, rows // 9)):06d}",
                "week_start": f"2026-W{1 + index % 8:02d}",
                "platform": platforms[index % len(platforms)],
                "status": status,
                "unit_price_cents": unit_price_cents,
                "quantity": quantity,
                "discount_bps": discount_bps,
            }
        )
    return lines


def parse_money_cents(value: Any) -> int:
    cents = int(value)
    if cents < 0:
        raise ProfilingError("money amount must be non-negative")
    return cents


def discounted_line_total_cents(row: OrderLine) -> int:
    gross = parse_money_cents(row["unit_price_cents"]) * int(row["quantity"])
    discount_bps = int(row["discount_bps"])
    if not 0 <= discount_bps <= 10_000:
        raise ProfilingError("discount_bps must be between 0 and 10000")
    return round(gross * (10_000 - discount_bps) / 10_000)


def normalize_platform(value: Any) -> str:
    platform_name = str(value).strip().lower()
    if platform_name not in {"web", "ios", "android"}:
        raise ProfilingError(f"unknown platform: {value!r}")
    return platform_name


def profiled_pipeline(lines: list[OrderLine]) -> PipelineResult:
    seen_keys: set[tuple[str, int]] = set()
    buckets: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {
            "line_count": 0,
            "paid_line_count": 0,
            "gross_revenue_cents": 0,
            "net_revenue_cents": 0,
            "user_ids": set(),
        }
    )

    for row in lines:
        key = (str(row["order_id"]), int(row["line_number"]))
        if key in seen_keys:
            raise ProfilingError(f"duplicate order line grain: {key}")
        seen_keys.add(key)

        week = str(row["week_start"])
        platform_name = normalize_platform(row["platform"])
        bucket = buckets[(week, platform_name)]
        bucket["line_count"] += 1
        bucket["user_ids"].add(str(row["user_id"]))

        line_total = discounted_line_total_cents(row)
        status = str(row["status"])
        if status == "paid":
            bucket["paid_line_count"] += 1
            bucket["gross_revenue_cents"] += line_total
            bucket["net_revenue_cents"] += line_total
        elif status == "refunded":
            bucket["net_revenue_cents"] -= line_total
        elif status != "pending":
            raise ProfilingError(f"unknown status: {status!r}")

    result: PipelineResult = []
    for (week, platform_name), values in sorted(buckets.items()):
        active_users = len(values["user_ids"])
        result.append(
            {
                "week_start": week,
                "platform": platform_name,
                "line_count": values["line_count"],
                "paid_line_count": values["paid_line_count"],
                "active_users": active_users,
                "gross_revenue_cents": values["gross_revenue_cents"],
                "net_revenue_cents": values["net_revenue_cents"],
                "revenue_per_active_user_cents": (
                    values["net_revenue_cents"] / active_users if active_users else None
                ),
            }
        )
    return result


def validate_result(result: PipelineResult) -> None:
    required = {
        "week_start",
        "platform",
        "line_count",
        "paid_line_count",
        "active_users",
        "gross_revenue_cents",
        "net_revenue_cents",
        "revenue_per_active_user_cents",
    }
    seen_grain: set[tuple[str, str]] = set()
    for row in result:
        missing = required - set(row)
        if missing:
            raise ProfilingError(f"result misses columns: {sorted(missing)}")
        grain = (str(row["week_start"]), str(row["platform"]))
        if grain in seen_grain:
            raise ProfilingError(f"duplicate output grain: {grain}")
        seen_grain.add(grain)
        if int(row["line_count"]) < int(row["paid_line_count"]):
            raise ProfilingError("paid_line_count cannot exceed line_count")
        if int(row["active_users"]) <= 0:
            raise ProfilingError("active_users must be positive")


def run_once(function: Pipeline, lines: list[OrderLine]) -> tuple[PipelineResult, dict[str, float]]:
    wall_start = time.perf_counter()
    process_start = time.process_time()
    result = function(lines)
    timings = {
        "wall_seconds": time.perf_counter() - wall_start,
        "process_seconds": time.process_time() - process_start,
    }
    validate_result(result)
    return result, timings


def summarize_cpu_profile(
    profiler: cProfile.Profile,
    *,
    top_n: int,
) -> dict[str, Any]:
    profiler.create_stats()
    stats = pstats.Stats(profiler)
    total_calls = 0
    primitive_calls = 0
    total_internal_seconds = 0.0
    rows: list[dict[str, Any]] = []

    for (filename, line_number, function_name), values in stats.stats.items():
        primitive, calls, internal, cumulative, _callers = values
        primitive_calls += primitive
        total_calls += calls
        total_internal_seconds += internal
        rows.append(
            {
                "function": function_name,
                "filename": filename,
                "line_number": line_number,
                "primitive_calls": primitive,
                "total_calls": calls,
                "internal_seconds": internal,
                "cumulative_seconds": cumulative,
            }
        )

    rows.sort(key=lambda row: row["cumulative_seconds"], reverse=True)
    top_functions = rows[:top_n]
    if top_functions and total_internal_seconds > 0:
        for row in top_functions:
            row["internal_fraction"] = row["internal_seconds"] / total_internal_seconds
    else:
        for row in top_functions:
            row["internal_fraction"] = 0.0

    return {
        "profiler": "cProfile",
        "sort": "cumulative_seconds",
        "total_calls": total_calls,
        "primitive_calls": primitive_calls,
        "total_internal_seconds": total_internal_seconds,
        "top_functions": top_functions,
        "limitations": [
            "cProfile records deterministic Python call statistics and adds overhead.",
            "cProfile does not attribute native vectorized work with the same detail as Python frames.",
        ],
    }


def summarize_memory_snapshot(
    snapshot: tracemalloc.Snapshot,
    *,
    current_bytes: int,
    peak_bytes: int,
    top_n: int,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for statistic in snapshot.statistics("lineno")[:top_n]:
        frame = statistic.traceback[0]
        rows.append(
            {
                "filename": frame.filename,
                "line_number": frame.lineno,
                "size_bytes": statistic.size,
                "allocation_count": statistic.count,
            }
        )

    return {
        "profiler": "tracemalloc",
        "current_bytes": current_bytes,
        "peak_bytes": peak_bytes,
        "top_allocations": rows,
        "limitations": [
            "tracemalloc tracks Python memory allocations traced by the interpreter.",
            "tracemalloc peak is not the same as full process RSS and may miss native allocations.",
        ],
    }


def classify_profile(
    *,
    cpu: dict[str, Any],
    memory: dict[str, Any],
    memory_budget_mb: float,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    top_functions = cpu["top_functions"]
    if top_functions:
        wrapper_functions = {"run_once", "profile_pipeline"}
        top = next(
            (
                row
                for row in top_functions
                if row["function"] not in wrapper_functions and not row["function"].startswith("<")
            ),
            top_functions[0],
        )
        findings.append(
            {
                "id": "top_cpu_function",
                "kind": "cpu",
                "severity": "review",
                "message": (
                    f"{top['function']} has the largest cumulative profile time "
                    f"({top['cumulative_seconds']:.6f}s)."
                ),
                "evidence": {
                    "function": top["function"],
                    "filename": top["filename"],
                    "line_number": top["line_number"],
                    "cumulative_seconds": top["cumulative_seconds"],
                    "total_calls": top["total_calls"],
                },
            }
        )

    budget_bytes = memory_budget_mb * 1024 * 1024
    peak_bytes = int(memory["peak_bytes"])
    if peak_bytes > budget_bytes:
        severity = "block"
        message = "Peak traced memory exceeds the declared memory budget."
    elif peak_bytes > budget_bytes * 0.7:
        severity = "watch"
        message = "Peak traced memory is close to the declared memory budget."
    else:
        severity = "info"
        message = "Peak traced memory is within the declared memory budget."
    findings.append(
        {
            "id": "memory_budget",
            "kind": "memory",
            "severity": severity,
            "message": message,
            "evidence": {
                "peak_bytes": peak_bytes,
                "memory_budget_mb": memory_budget_mb,
            },
        }
    )

    if memory["top_allocations"]:
        top_alloc = memory["top_allocations"][0]
        findings.append(
            {
                "id": "top_allocation_line",
                "kind": "memory",
                "severity": "review",
                "message": "Review the largest traced allocation line before optimizing blindly.",
                "evidence": top_alloc,
            }
        )
    return findings


def environment_report() -> dict[str, str]:
    return {
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or "unknown",
    }


def profile_pipeline(
    *,
    rows: int,
    seed: int,
    top_n: int,
    memory_budget_mb: float,
    pipeline: Pipeline = profiled_pipeline,
) -> dict[str, Any]:
    if top_n <= 0:
        raise ProfilingError("top_n must be positive")
    if memory_budget_mb <= 0:
        raise ProfilingError("memory_budget_mb must be positive")

    lines = generate_order_lines(rows, seed)

    profiler = cProfile.Profile()
    tracemalloc.start()
    try:
        profiler.enable()
        result, timings = run_once(pipeline, lines)
        profiler.disable()
        current_bytes, peak_bytes = tracemalloc.get_traced_memory()
        snapshot = tracemalloc.take_snapshot()
    finally:
        profiler.disable()
        tracemalloc.stop()

    cpu = summarize_cpu_profile(profiler, top_n=top_n)
    memory = summarize_memory_snapshot(
        snapshot,
        current_bytes=current_bytes,
        peak_bytes=peak_bytes,
        top_n=top_n,
    )
    findings = classify_profile(cpu=cpu, memory=memory, memory_budget_mb=memory_budget_mb)
    net_revenue = sum(int(row["net_revenue_cents"]) for row in result)
    paid_lines = sum(int(row["paid_line_count"]) for row in result)

    return {
        "scenario": {
            "scenario_id": "weekly-revenue-profile",
            "pipeline_name": "customer_revenue_health_weekly",
            "rows": rows,
            "seed": seed,
            "top_n": top_n,
            "memory_budget_mb": memory_budget_mb,
            "timing_scope": "single in-memory pipeline run; input generation excluded",
        },
        "environment": environment_report(),
        "result_contract": {
            "output_rows": len(result),
            "grain": "week_start, platform",
            "net_revenue_cents": net_revenue,
            "paid_line_count": paid_lines,
        },
        "timings": timings,
        "cpu_profile": cpu,
        "memory_profile": memory,
        "findings": findings,
        "interpretation": {
            "profile_is_benchmark": False,
            "notes": [
                "Use this report to locate hot spots, not to claim stable speedup.",
                "Compare performance decisions with repeated benchmark evidence from lesson 12/01.",
            ],
        },
    }


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Profile a deterministic analytical pipeline.")
    parser.add_argument("--rows", type=int, default=5_000, help="number of order lines")
    parser.add_argument("--seed", type=int, default=42, help="deterministic input seed")
    parser.add_argument("--top-n", type=int, default=8, help="number of profile entries")
    parser.add_argument(
        "--memory-budget-mb",
        type=float,
        default=16.0,
        help="traced memory budget used for report classification",
    )
    parser.add_argument("--output", type=Path, help="optional JSON report path")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = profile_pipeline(
            rows=args.rows,
            seed=args.seed,
            top_n=args.top_n,
            memory_budget_mb=args.memory_budget_mb,
        )
        if args.output is not None:
            write_json(args.output, report)
    except ProfilingError as error:
        print(f"profiling error: {error}", file=sys.stderr)
        return 2

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
