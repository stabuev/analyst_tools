from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import random
import statistics
import sys
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any


class BenchmarkError(ValueError):
    """Raised when a benchmark scenario cannot produce trustworthy evidence."""


OrderLine = dict[str, Any]
PipelineResult = list[dict[str, Any]]
Pipeline = Callable[[list[OrderLine]], PipelineResult]


REQUIRED_SCENARIO_FIELDS = {
    "scenario_id",
    "business_question",
    "pipeline_name",
    "pipeline_version",
    "dataset_profile",
    "scale_rows",
    "engines",
    "cache_policy",
    "warmup_runs",
    "measured_runs",
    "timer",
    "timing_scope",
    "equivalence_checks",
    "selection_rule",
}


def generate_order_lines(rows: int, seed: int) -> list[OrderLine]:
    if rows <= 0:
        raise BenchmarkError("rows must be positive")

    rng = random.Random(seed)
    statuses = ("paid", "paid", "paid", "refunded", "pending")
    platforms = ("web", "ios", "android")
    lines: list[OrderLine] = []
    for index in range(rows):
        unit_price_cents = rng.randrange(199, 12_500)
        quantity = rng.randrange(1, 5)
        week_number = 1 + index % 4
        status = statuses[rng.randrange(len(statuses))]
        lines.append(
            {
                "order_id": f"O{index // 3:06d}",
                "line_number": index % 3 + 1,
                "user_id": f"U{rng.randrange(1, max(2, rows // 7)):05d}",
                "week_start": f"2026-W{week_number:02d}",
                "platform": platforms[index % len(platforms)],
                "status": status,
                "unit_price_cents": unit_price_cents,
                "quantity": quantity,
            }
        )
    return lines


def reference_weekly_revenue(lines: list[OrderLine]) -> PipelineResult:
    by_week: dict[str, dict[str, int]] = {}
    seen_keys: set[tuple[str, int]] = set()

    for row in lines:
        key = (str(row["order_id"]), int(row["line_number"]))
        if key in seen_keys:
            raise BenchmarkError(f"duplicate order line grain: {key}")
        seen_keys.add(key)

        week = str(row["week_start"])
        bucket = by_week.setdefault(
            week,
            {
                "line_count": 0,
                "paid_line_count": 0,
                "gross_revenue_cents": 0,
                "net_revenue_cents": 0,
            },
        )
        bucket["line_count"] += 1

        status = str(row["status"])
        line_total = int(row["unit_price_cents"]) * int(row["quantity"])
        if status == "paid":
            bucket["paid_line_count"] += 1
            bucket["gross_revenue_cents"] += line_total
            bucket["net_revenue_cents"] += line_total
        elif status == "refunded":
            bucket["net_revenue_cents"] -= line_total

    return [{"week_start": week, **values} for week, values in sorted(by_week.items())]


def candidate_weekly_revenue(lines: list[OrderLine]) -> PipelineResult:
    weeks = sorted({str(row["week_start"]) for row in lines})
    result: PipelineResult = []
    for week in weeks:
        week_rows = [row for row in lines if row["week_start"] == week]
        paid_rows = [row for row in week_rows if row["status"] == "paid"]
        refunded_rows = [row for row in week_rows if row["status"] == "refunded"]
        gross = sum(int(row["unit_price_cents"]) * int(row["quantity"]) for row in paid_rows)
        refunds = sum(
            int(row["unit_price_cents"]) * int(row["quantity"]) for row in refunded_rows
        )
        result.append(
            {
                "week_start": week,
                "line_count": len(week_rows),
                "paid_line_count": len(paid_rows),
                "gross_revenue_cents": gross,
                "net_revenue_cents": gross - refunds,
            }
        )
    return result


def normalized_result(result: PipelineResult) -> PipelineResult:
    required = {
        "week_start",
        "line_count",
        "paid_line_count",
        "gross_revenue_cents",
        "net_revenue_cents",
    }
    normalized: PipelineResult = []
    for row in result:
        missing = required - set(row)
        if missing:
            raise BenchmarkError(f"pipeline result misses columns: {sorted(missing)}")
        normalized.append(
            {
                "week_start": str(row["week_start"]),
                "line_count": int(row["line_count"]),
                "paid_line_count": int(row["paid_line_count"]),
                "gross_revenue_cents": int(row["gross_revenue_cents"]),
                "net_revenue_cents": int(row["net_revenue_cents"]),
            }
        )
    return sorted(normalized, key=lambda row: row["week_start"])


def stable_json_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compare_outputs(reference: PipelineResult, candidate: PipelineResult) -> dict[str, Any]:
    left = normalized_result(reference)
    right = normalized_result(candidate)
    mismatches: list[dict[str, Any]] = []
    for index, (left_row, right_row) in enumerate(zip(left, right, strict=False)):
        if left_row != right_row:
            mismatches.append(
                {"row_index": index, "reference": left_row, "candidate": right_row}
            )
    if len(left) != len(right):
        mismatches.append({"row_count": {"reference": len(left), "candidate": len(right)}})

    return {
        "passed": not mismatches,
        "row_count": len(left),
        "reference_checksum": stable_json_hash(left),
        "candidate_checksum": stable_json_hash(right),
        "mismatches": mismatches[:5],
    }


def default_scenario(rows: int, repeat: int) -> dict[str, Any]:
    return {
        "scenario_id": "weekly-revenue-benchmark",
        "business_question": (
            "Can a candidate weekly revenue pipeline replace the transparent reference "
            "without changing the customer revenue health metric?"
        ),
        "pipeline_name": "weekly_revenue_by_week",
        "pipeline_version": "1.0",
        "dataset_profile": "tiny" if rows <= 10_000 else "sample",
        "scale_rows": rows,
        "engines": ["python_reference", "python_candidate"],
        "cache_policy": "Generate input once outside timed section; run warm-up before measurements.",
        "warmup_runs": 1,
        "measured_runs": repeat,
        "timer": "time.perf_counter",
        "timing_scope": "Prepared in-memory order lines only; data generation and validation excluded.",
        "equivalence_checks": ["equivalence: normalized exact output equality before timing"],
        "selection_rule": "Prefer the simpler implementation unless median speedup is material and outputs match.",
    }


def validate_scenario(scenario: dict[str, Any]) -> None:
    missing = REQUIRED_SCENARIO_FIELDS - set(scenario)
    if missing:
        raise BenchmarkError(f"scenario misses required fields: {sorted(missing)}")
    if int(scenario["measured_runs"]) < 3:
        raise BenchmarkError("measured_runs must be at least 3")
    if int(scenario["warmup_runs"]) < 1:
        raise BenchmarkError("warmup_runs must be at least 1")
    engines = scenario["engines"]
    if not isinstance(engines, list) or len(engines) < 2:
        raise BenchmarkError("scenario must compare at least two engines or implementations")
    if "equivalence" not in " ".join(scenario["equivalence_checks"]).lower():
        raise BenchmarkError("scenario must declare an equivalence check")


def environment_report() -> dict[str, str]:
    return {
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or "unknown",
    }


def measure_seconds(
    function: Callable[[], PipelineResult],
    *,
    implementation: str,
    repeat: int,
    warmup: int = 1,
) -> list[dict[str, Any]]:
    if repeat < 3:
        raise BenchmarkError("repeat must be at least 3")
    for _ in range(warmup):
        function()

    runs: list[dict[str, Any]] = []
    for run_id in range(1, repeat + 1):
        started = time.perf_counter()
        function()
        duration = time.perf_counter() - started
        runs.append(
            {
                "implementation": implementation,
                "run_id": run_id,
                "seconds": duration,
            }
        )
    return runs


def summarize_runs(runs: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[float]] = {}
    for run in runs:
        grouped.setdefault(str(run["implementation"]), []).append(float(run["seconds"]))

    summary: list[dict[str, Any]] = []
    for implementation, durations in sorted(grouped.items()):
        summary.append(
            {
                "implementation": implementation,
                "runs": len(durations),
                "min_seconds": min(durations),
                "median_seconds": statistics.median(durations),
                "max_seconds": max(durations),
                "mean_seconds": statistics.fmean(durations),
            }
        )
    return summary


def run_benchmark(
    *,
    rows: int,
    repeat: int,
    seed: int,
    reference: Pipeline = reference_weekly_revenue,
    candidate: Pipeline = candidate_weekly_revenue,
    scenario: dict[str, Any] | None = None,
) -> dict[str, Any]:
    scenario = scenario or default_scenario(rows, repeat)
    validate_scenario(scenario)
    if int(scenario["scale_rows"]) != rows:
        raise BenchmarkError("scenario scale_rows must match rows")
    if int(scenario["measured_runs"]) != repeat:
        raise BenchmarkError("scenario measured_runs must match repeat")

    lines = generate_order_lines(rows, seed)
    input_digest = stable_json_hash(lines)
    reference_result = reference(lines)
    candidate_result = candidate(lines)
    equivalence = compare_outputs(reference_result, candidate_result)
    if not equivalence["passed"]:
        raise BenchmarkError("equivalence gate failed before timing")

    raw_runs = [
        *measure_seconds(
            lambda: reference(lines),
            implementation="python_reference",
            repeat=repeat,
            warmup=int(scenario["warmup_runs"]),
        ),
        *measure_seconds(
            lambda: candidate(lines),
            implementation="python_candidate",
            repeat=repeat,
            warmup=int(scenario["warmup_runs"]),
        ),
    ]
    summary = summarize_runs(raw_runs)
    summary_by_name = {row["implementation"]: row for row in summary}
    reference_median = summary_by_name["python_reference"]["median_seconds"]
    candidate_median = summary_by_name["python_candidate"]["median_seconds"]
    speedup = reference_median / candidate_median if candidate_median > 0 else None

    return {
        "scenario": scenario,
        "environment": environment_report(),
        "input": {
            "rows": rows,
            "seed": seed,
            "checksum": input_digest,
            "generation_excluded_from_timing": True,
        },
        "equivalence": equivalence,
        "measurements": {
            "raw_runs": raw_runs,
            "summary": summary,
        },
        "decision": {
            "speedup_reference_over_candidate": speedup,
            "candidate_is_materially_faster": bool(speedup is not None and speedup >= 1.2),
            "usable_for_engine_decision": equivalence["passed"] and repeat >= 3,
        },
    }


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise BenchmarkError(f"cannot write empty CSV: {path}")
    with path.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_package(report: dict[str, Any], output_dir: Path) -> None:
    write_json(output_dir / "benchmark-plan.json", report["scenario"])
    write_json(output_dir / "measurements" / "environment.json", report["environment"])
    write_csv(output_dir / "measurements" / "raw-runs.csv", report["measurements"]["raw_runs"])
    write_csv(output_dir / "measurements" / "summary.csv", report["measurements"]["summary"])
    write_json(output_dir / "equivalence" / "output-checks.json", report["equivalence"])
    write_json(output_dir / "report.json", report)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a reproducible benchmark scenario.")
    parser.add_argument("--rows", type=int, default=5_000, help="number of order lines")
    parser.add_argument("--repeat", type=int, default=5, help="measured runs per implementation")
    parser.add_argument("--seed", type=int, default=42, help="deterministic input seed")
    parser.add_argument("--output-dir", type=Path, help="optional directory for benchmark package")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = run_benchmark(rows=args.rows, repeat=args.repeat, seed=args.seed)
        if args.output_dir is not None:
            write_package(report, args.output_dir)
    except BenchmarkError as error:
        print(f"benchmark error: {error}", file=sys.stderr)
        return 2

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
