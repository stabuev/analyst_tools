from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Any

PHASE_ROOT = Path(__file__).resolve().parents[2]


def load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


INVARIANTS = load_module(
    "phase07_invariants", PHASE_ROOT / "01-invariants" / "outputs" / "invariant_gate.py"
)
STAGES = load_module(
    "phase07_stages",
    PHASE_ROOT / "02-unit-tests" / "outputs" / "order_stage_contracts.py",
)
SCHEMAS = load_module(
    "phase07_schemas", PHASE_ROOT / "05-pandera" / "outputs" / "dataframe_contract.py"
)
CONFIG = load_module(
    "phase07_config", PHASE_ROOT / "06-pydantic" / "outputs" / "pipeline_config.py"
)
SQL = load_module("phase07_sql", PHASE_ROOT / "07-sql-checks" / "outputs" / "sql_quality_checks.py")
GOLDEN = load_module(
    "phase07_golden", PHASE_ROOT / "08-golden-datasets" / "outputs" / "golden_regression.py"
)
MONITOR = load_module(
    "phase07_monitor", PHASE_ROOT / "09-observability" / "outputs" / "quality_monitor.py"
)
DEFAULT_GOLDEN = PHASE_ROOT / "08-golden-datasets" / "outputs" / "orders_golden.json"


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resolve_path(value: str, config_path: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (config_path.parent / path).resolve()


def invariant_report(data_dir: Path) -> dict[str, Any]:
    with (data_dir / "orders.csv").open(encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        return INVARIANTS.evaluate_orders(list(reader), list(reader.fieldnames or []))


def event(log_path: Path, event_id: str, **details: Any) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"event": event_id, **details}
    with log_path.open("a", encoding="utf-8") as output:
        output.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str) + "\n")


def manifest_for(root: Path, run_id: str, row_counts: dict[str, int]) -> dict[str, Any]:
    files = {
        path.relative_to(root).as_posix(): {
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
        }
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name != "manifest.json"
    }
    return {
        "run_id": run_id,
        "pipeline_version": "1.0.0",
        "contracts": {
            "config": CONFIG.CONFIG_VERSION,
            "schema": SCHEMAS.CONTRACT_VERSION,
            "golden": GOLDEN.GOLDEN_VERSION,
            "monitor": MONITOR.MONITOR_VERSION,
        },
        "row_counts": row_counts,
        "files": files,
    }


def finish_failed_run(
    staging: Path,
    delivery_root: Path,
    run_id: str,
    report: dict[str, Any],
) -> dict[str, Any]:
    write_json(staging / "run-report.json", report)
    failed = delivery_root / "failed" / run_id
    failed.parent.mkdir(parents=True, exist_ok=True)
    staging.replace(failed)
    report["delivery_path"] = str(failed)
    return report


def run_pipeline(
    config_path: str | Path,
    observed_at: datetime,
    *,
    simulate_publish_failure: bool = False,
) -> dict[str, Any]:
    config_file = Path(config_path).resolve()
    try:
        raw_config = config_file.read_text(encoding="utf-8")
    except OSError as error:
        return {
            "status": "failed",
            "failure_class": "configuration_failure",
            "published": False,
            "error": str(error),
        }
    config_report = CONFIG.validate_json(raw_config)
    if not config_report["valid"]:
        return {
            "status": "failed",
            "failure_class": "configuration_failure",
            "published": False,
            "config_report": config_report,
        }

    config = config_report["config"]
    input_dir = resolve_path(config["input_dir"], config_file)
    delivery_root = resolve_path(config["output_dir"], config_file)
    run_id = f"{config['batch_date']}-{observed_at.strftime('%Y%m%dT%H%M%S%z')}"
    staging = delivery_root / f".staging-{run_id}"
    if staging.exists():
        return {
            "status": "failed",
            "failure_class": "system_failure",
            "published": False,
            "error": f"staging directory already exists: {staging}",
        }
    staging.mkdir(parents=True)
    log_path = staging / "logs" / "run.jsonl"
    event(log_path, "pipeline_started", run_id=run_id, observed_at=observed_at.isoformat())
    write_json(staging / "config.json", config)

    try:
        invariant = invariant_report(input_dir)
        schema = SCHEMAS.validate_frames(SCHEMAS.load_frames(input_dir))
        sql = SQL.run_checks(input_dir)
        regression = GOLDEN.compare_with_golden(input_dir, DEFAULT_GOLDEN)
        monitoring = MONITOR.monitor_batch(input_dir, config["thresholds"], observed_at)
    except (OSError, KeyError, TypeError, ValueError) as error:
        event(log_path, "pipeline_failed", failure_class="system_failure", error=str(error))
        return finish_failed_run(
            staging,
            delivery_root,
            run_id,
            {
                "run_id": run_id,
                "status": "failed",
                "failure_class": "system_failure",
                "published": False,
                "error": str(error),
            },
        )

    quality_reports = {
        "invariant-report.json": invariant,
        "schema-report.json": schema,
        "sql-checks.json": sql,
        "regression-report.json": regression,
        "monitoring-report.json": monitoring,
    }
    for filename, payload in quality_reports.items():
        write_json(staging / "quality" / filename, payload)
        event(
            log_path,
            "quality_gate_finished",
            gate=filename.removesuffix(".json"),
            valid=payload.get("valid", payload.get("status") == "success"),
        )

    gates = {
        "invariant": invariant["valid"],
        "schema": schema["valid"],
        "sql": sql["valid"],
        "regression": regression["valid"],
        "monitoring": monitoring["status"] == "success",
    }
    if not all(gates.values()):
        event(log_path, "pipeline_failed", failure_class="data_failure", gates=gates)
        return finish_failed_run(
            staging,
            delivery_root,
            run_id,
            {
                "run_id": run_id,
                "status": "failed",
                "failure_class": "data_failure",
                "published": False,
                "gates": gates,
            },
        )

    users, orders, items = STAGES.load_frames(input_dir)
    mart = STAGES.build_order_mart(users, orders, items)
    daily_metrics = STAGES.build_daily_metrics(mart)
    mart_dir = staging / "mart"
    mart_dir.mkdir(parents=True, exist_ok=True)
    mart.to_parquet(mart_dir / "orders.parquet", index=False)
    daily_metrics.to_csv(mart_dir / "daily_metrics.csv", index=False, lineterminator="\n")
    row_counts = {
        "users": len(users),
        "orders": len(orders),
        "order_items": len(items),
        "mart_orders": len(mart),
        "daily_metrics": len(daily_metrics),
    }
    run_report = {
        "run_id": run_id,
        "status": "success",
        "failure_class": None,
        "published": True,
        "observed_at": observed_at.isoformat(),
        "gates": gates,
        "row_counts": row_counts,
    }
    event(log_path, "artifacts_staged", row_counts=row_counts)
    write_json(staging / "run-report.json", run_report)
    manifest = manifest_for(staging, run_id, row_counts)
    write_json(staging / "manifest.json", manifest)

    if simulate_publish_failure:
        event(log_path, "pipeline_failed", failure_class="system_failure", stage="publish")
        run_report.update(
            {"status": "failed", "failure_class": "system_failure", "published": False}
        )
        return finish_failed_run(staging, delivery_root, run_id, run_report)

    version = delivery_root / "versions" / run_id
    version.parent.mkdir(parents=True, exist_ok=True)
    staging.replace(version)
    current = {
        "run_id": run_id,
        "version_path": version.relative_to(delivery_root).as_posix(),
        "manifest_sha256": sha256(version / "manifest.json"),
    }
    current_tmp = delivery_root / ".current.json.tmp"
    write_json(current_tmp, current)
    current_tmp.replace(delivery_root / "current.json")
    run_report["delivery_path"] = str(version)
    run_report["current"] = current
    return run_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish a quality-gated order mart")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--observed-at", required=True)
    parser.add_argument("--simulate-publish-failure", action="store_true")
    args = parser.parse_args()
    try:
        observed_at = datetime.fromisoformat(args.observed_at)
    except ValueError as error:
        parser.error(str(error))
    report = run_pipeline(
        args.config,
        observed_at,
        simulate_publish_failure=args.simulate_publish_failure,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if report["status"] == "success" else 1)


if __name__ == "__main__":
    main()
