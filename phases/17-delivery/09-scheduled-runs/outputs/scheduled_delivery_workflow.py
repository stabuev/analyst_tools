from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


WORKFLOW_VERSION = "1.0.0"
DEFAULT_RUN_ID = "scheduled-2026-01-05T06-17-00Z"
DEFAULT_SCHEDULED_FOR_UTC = "2026-01-05T06:17:00Z"
DEFAULT_STARTED_AT_UTC = "2026-01-05T06:18:10Z"
DEFAULT_FINISHED_AT_UTC = "2026-01-05T06:18:40Z"
SCHEDULE_EXIT_CODE_POLICY = {
    "success": 0,
    "schedule_contract_block": 2,
    "data_quality_block": 10,
    "freshness_warning": 20,
    "system_error": 30,
}
REQUIRED_WORKFLOW_MARKERS = [
    "on:",
    "schedule:",
    "cron:",
    "workflow_dispatch:",
    "uv run --locked python",
    "delivery_cli_runner.py",
    "--app-dir",
    "--output-dir",
    "--report",
]
HISTORY_FIELDS = [
    "run_id",
    "scheduled_for_utc",
    "started_at_utc",
    "finished_at_utc",
    "status",
    "exit_code",
    "published",
    "freshness_state",
    "notification_sent",
    "last_success_utc",
    "cli_report_path",
    "cli_manifest_path",
]


@dataclass(frozen=True)
class ScheduledRunResult:
    status: str
    exit_code: int
    output_dir: Path
    published_delivery_dir: Path
    run_report_path: Path
    freshness_report_path: Path
    history_path: Path
    last_success_marker_path: Path | None
    notification_path: Path
    manifest_path: Path
    report: dict[str, Any]


class ScheduledWorkflowError(RuntimeError):
    def __init__(self, code: str, message: str, *, status: str = "system_error") -> None:
        super().__init__(message)
        self.code = code
        self.status = status


def read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: str | Path, payload: Any) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_text(path: str | Path, text: str) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(text, encoding="utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def format_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def relpath(path: str | Path, *, start: str | Path) -> str:
    return Path(os.path.relpath(Path(path), Path(start))).as_posix()


def manifest_entry(path: Path, *, start: Path) -> dict[str, Any]:
    return {
        "path": relpath(path, start=start),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
    }


def optional_manifest_entry(path: Path | None, *, start: Path) -> dict[str, Any]:
    if path is not None and path.is_file():
        return manifest_entry(path, start=start)
    if path is not None:
        return {"path": relpath(path, start=start), "sha256": "", "bytes": 0, "missing": True}
    return {"path": "", "sha256": "", "bytes": 0, "missing": True}


def hash_tree(root: Path) -> dict[str, str]:
    if not root.exists():
        return {}
    return {
        relpath(path, start=root): sha256_file(path)
        for path in sorted(item for item in root.rglob("*") if item.is_file())
    }


def check(
    check_id: str,
    valid: bool,
    *,
    severity: str = "block",
    observed: Any = None,
    expected: Any = None,
    message: str = "",
) -> dict[str, Any]:
    return {
        "id": check_id,
        "valid": bool(valid),
        "severity": severity,
        "observed": observed,
        "expected": expected,
        "message": message,
    }


def load_delivery_cli_runner():
    current = Path(__file__).resolve()
    runner_path = current.parents[2] / "08-cli" / "outputs" / "delivery_cli_runner.py"
    spec = importlib.util.spec_from_file_location("delivery_cli_runner_for_schedule", runner_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load delivery CLI runner: {runner_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def default_schedule_contract() -> dict[str, Any]:
    return {
        "schedule_id": "trial-onboarding-weekly-delivery-refresh",
        "source_cli_id": "trial-onboarding-delivery-cli",
        "owner": {
            "primary": "support_lead",
            "backup": "product_analytics",
            "notification_channel": "tracker_comment_mock",
        },
        "cron": "17 6 * * 1",
        "timezone": "UTC",
        "local_timezone_note": "Europe/Moscow stakeholders see the package on Monday morning, but the scheduler runs in UTC.",
        "expected_cadence_minutes": 10080,
        "last_success_max_age_minutes": 10140,
        "github_actions_constraints": {
            "schedule_uses_utc": True,
            "default_branch_required": True,
            "minimum_interval_minutes": 5,
            "high_load_delay_visible": True,
            "workflow_dispatch_enabled": True,
            "avoid_top_of_hour": True,
        },
        "run_policy": {
            "write_run_history": True,
            "write_freshness_report": True,
            "write_last_success_marker": True,
            "write_failure_notification_mock": True,
            "no_source_mutation": True,
            "no_partial_publish_on_failure": True,
            "replace_previous_delivery_only_after_success": True,
        },
        "required_cli_arguments": [
            "--app-dir",
            "--cache-state-contract",
            "--freshness-policy",
            "--cli-contract",
            "--output-dir",
            "--report",
        ],
        "freshness_policy": {
            "fresh_success_updates_last_success": True,
            "freshness_warning_does_not_update_last_success": True,
            "history_required_for_every_attempt": True,
        },
        "failure_visibility": {
            "notify_on_statuses": ["schedule_contract_block", "data_quality_block", "freshness_warning", "system_error"],
            "include_run_report_path": True,
            "include_owner": True,
            "include_next_manual_action": True,
        },
    }


def normalize_schedule_contract(contract: dict[str, Any] | None) -> dict[str, Any]:
    normalized = default_schedule_contract()
    if contract:
        normalized.update(contract)
    return normalized


def _parse_cron_field(field: str, minimum: int, maximum: int) -> list[int]:
    values: set[int] = set()
    for part in field.split(","):
        part = part.strip()
        if part == "*":
            values.update(range(minimum, maximum + 1))
        elif part.startswith("*/"):
            step = int(part[2:])
            values.update(range(minimum, maximum + 1, step))
        elif "-" in part:
            start_text, end_text = part.split("-", 1)
            start = int(start_text)
            end = int(end_text)
            values.update(range(start, end + 1))
        else:
            values.add(int(part))
    if any(value < minimum or value > maximum for value in values):
        raise ValueError(f"cron field out of range: {field}")
    return sorted(values)


def cron_minimum_interval_minutes(cron: str) -> int:
    fields = cron.split()
    if len(fields) != 5:
        raise ValueError("cron must have five fields")
    minutes = _parse_cron_field(fields[0], 0, 59)
    hours = _parse_cron_field(fields[1], 0, 23)
    weekdays = _parse_cron_field(fields[4], 0, 6) if fields[4] != "*" else list(range(7))
    offsets = sorted((day * 24 * 60) + (hour * 60) + minute for day in weekdays for hour in hours for minute in minutes)
    if len(offsets) < 2:
        return 7 * 24 * 60
    week_minutes = 7 * 24 * 60
    gaps = [next_value - value for value, next_value in zip(offsets, offsets[1:])]
    gaps.append(offsets[0] + week_minutes - offsets[-1])
    return min(gaps)


def schedule_contract_errors(contract: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    owner = contract.get("owner", {})
    cron = str(contract.get("cron", ""))
    constraints = contract.get("github_actions_constraints", {})
    run_policy = contract.get("run_policy", {})
    required_cli_args = set(contract.get("required_cli_arguments", []))
    if not owner.get("primary") or not owner.get("backup"):
        errors.append("owner_primary_and_backup_are_required")
    if contract.get("timezone") != "UTC":
        errors.append("schedule_timezone_must_be_utc")
    try:
        minimum_interval = cron_minimum_interval_minutes(cron)
        minute_values = _parse_cron_field(cron.split()[0], 0, 59)
    except Exception:
        errors.append("cron_expression_must_be_valid_five_field_cron")
        minimum_interval = 0
        minute_values = []
    if minimum_interval < constraints.get("minimum_interval_minutes", 5):
        errors.append("cron_minimum_interval_must_be_at_least_five_minutes")
    if constraints.get("avoid_top_of_hour") is True and 0 in minute_values:
        errors.append("cron_should_avoid_top_of_hour")
    for field, error_id in [
        ("schedule_uses_utc", "github_actions_schedule_utc_constraint_required"),
        ("default_branch_required", "github_actions_default_branch_constraint_required"),
        ("high_load_delay_visible", "github_actions_delay_or_drop_warning_required"),
        ("workflow_dispatch_enabled", "manual_dispatch_required_for_recovery"),
    ]:
        if constraints.get(field) is not True:
            errors.append(error_id)
    for field, error_id in [
        ("write_run_history", "run_history_required"),
        ("write_freshness_report", "schedule_freshness_report_required"),
        ("write_last_success_marker", "last_success_marker_required"),
        ("write_failure_notification_mock", "failure_notification_mock_required"),
        ("no_source_mutation", "schedule_must_not_mutate_source_truth"),
        ("no_partial_publish_on_failure", "no_partial_publish_on_failed_runs_required"),
    ]:
        if run_policy.get(field) is not True:
            errors.append(error_id)
    required = {"--app-dir", "--output-dir", "--report"}
    if not required.issubset(required_cli_args):
        errors.append("schedule_must_call_cli_with_explicit_paths_and_report")
    return sorted(errors)


def build_github_actions_workflow(contract: dict[str, Any]) -> str:
    cron = contract["cron"]
    return f"""name: Scheduled delivery refresh
on:
  schedule:
    - cron: "{cron}"
  workflow_dispatch:

permissions:
  contents: read

concurrency:
  group: scheduled-delivery-refresh
  cancel-in-progress: false

jobs:
  refresh:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - name: Run delivery CLI
        run: >
          uv run --locked python phases/17-delivery/08-cli/outputs/delivery_cli_runner.py
          --app-dir "${{{{ vars.DELIVERY_APP_DIR }}}}"
          --cache-state-contract "${{{{ vars.DELIVERY_CACHE_STATE_CONTRACT }}}}"
          --freshness-policy "${{{{ vars.DELIVERY_FRESHNESS_POLICY }}}}"
          --cli-contract "${{{{ vars.DELIVERY_CLI_CONTRACT }}}}"
          --output-dir "published-delivery"
          --report "automation/latest-cli-run-report.json"
          --overwrite
      - name: Upload run reports
        uses: actions/upload-artifact@v4
        with:
          name: scheduled-delivery-run
          path: |
            automation/latest-cli-run-report.json
            published-delivery/cli_publish_manifest.json
"""


def workflow_marker_errors(workflow_text: str) -> list[str]:
    return [marker for marker in REQUIRED_WORKFLOW_MARKERS if marker not in workflow_text]


def write_sample_schedule_inputs(root: str | Path) -> dict[str, Path]:
    root_path = Path(root).resolve()
    root_path.mkdir(parents=True, exist_ok=True)
    runner = load_delivery_cli_runner()
    sample = runner.write_sample_cli_inputs(root_path / "cli-inputs")
    schedule_contract_path = root_path / "schedule_contract.json"
    write_json(schedule_contract_path, default_schedule_contract())
    return {
        "app_dir": sample["app_dir"],
        "cache_state_contract_path": sample["cache_state_contract_path"],
        "freshness_policy_path": sample["freshness_policy_path"],
        "cli_contract_path": sample["cli_contract_path"],
        "schedule_contract_path": schedule_contract_path,
    }


def append_history_row(history_path: Path, row: dict[str, Any]) -> None:
    history_path.parent.mkdir(parents=True, exist_ok=True)
    exists = history_path.is_file()
    with history_path.open("a", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=HISTORY_FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerow({field: row.get(field, "") for field in HISTORY_FIELDS})


def read_history_rows(history_path: Path) -> list[dict[str, str]]:
    if not history_path.is_file():
        return []
    with history_path.open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def determine_freshness_state(
    published_delivery_dir: Path,
    status: str,
    *,
    delivery_published_this_run: bool,
) -> tuple[str, dict[str, Any] | None]:
    freshness_path = published_delivery_dir / "freshness_report.json"
    if delivery_published_this_run and freshness_path.is_file():
        freshness = read_json(freshness_path)
        return ("stale" if freshness.get("stale") else "fresh"), freshness
    if status == "freshness_warning":
        return "stale", None
    return "unknown", None


def build_last_success_marker(
    *,
    contract: dict[str, Any],
    run_id: str,
    scheduled_for_utc: str,
    finished_at_utc: str,
    published_delivery_dir: Path,
    delivery_manifest_path: Path | None,
) -> dict[str, Any]:
    return {
        "schedule_id": contract["schedule_id"],
        "run_id": run_id,
        "last_success_utc": finished_at_utc,
        "scheduled_for_utc": scheduled_for_utc,
        "published_delivery_dir": str(published_delivery_dir),
        "delivery_manifest_path": str(delivery_manifest_path) if delivery_manifest_path else "",
        "delivery_manifest_sha256": sha256_file(delivery_manifest_path) if delivery_manifest_path and delivery_manifest_path.is_file() else "",
    }


def build_schedule_freshness_report(
    *,
    contract: dict[str, Any],
    run_id: str,
    status: str,
    scheduled_for_utc: str,
    finished_at_utc: str,
    last_success_marker: dict[str, Any] | None,
    delivery_freshness: dict[str, Any] | None,
    freshness_state: str,
) -> dict[str, Any]:
    finished_at = parse_utc(finished_at_utc)
    next_expected = parse_utc(scheduled_for_utc) + timedelta(minutes=int(contract["expected_cadence_minutes"]))
    last_success_utc = last_success_marker.get("last_success_utc") if last_success_marker else ""
    if last_success_utc:
        last_success_age_seconds = int((finished_at - parse_utc(last_success_utc)).total_seconds())
    else:
        last_success_age_seconds = None
    max_age_seconds = int(contract["last_success_max_age_minutes"]) * 60
    last_success_overdue = last_success_age_seconds is None or last_success_age_seconds > max_age_seconds
    return {
        "version": WORKFLOW_VERSION,
        "schedule_id": contract["schedule_id"],
        "run_id": run_id,
        "status": status,
        "freshness_state": freshness_state,
        "scheduled_for_utc": scheduled_for_utc,
        "finished_at_utc": finished_at_utc,
        "next_expected_run_utc": format_utc(next_expected),
        "last_success_marker_present": bool(last_success_marker),
        "last_success_utc": last_success_utc,
        "last_success_age_seconds": last_success_age_seconds,
        "last_success_max_age_seconds": max_age_seconds,
        "last_success_overdue": last_success_overdue,
        "delivery_freshness": delivery_freshness or {},
        "github_actions_schedule_caveats": {
            "timezone": "UTC",
            "default_branch_only": True,
            "minimum_interval_minutes": 5,
            "may_be_delayed_or_dropped_under_high_load": True,
        },
    }


def build_failure_notification(
    *,
    contract: dict[str, Any],
    run_id: str,
    status: str,
    exit_code: int,
    run_report_path: Path,
    blocking_errors: list[str],
    freshness_state: str,
) -> dict[str, Any]:
    should_notify = status != "success"
    severity = "warning" if status == "freshness_warning" else "critical"
    return {
        "version": WORKFLOW_VERSION,
        "schedule_id": contract.get("schedule_id"),
        "run_id": run_id,
        "should_notify": should_notify,
        "severity": severity if should_notify else "none",
        "status": status,
        "exit_code": exit_code,
        "owner": contract.get("owner", {}),
        "recipient": contract.get("owner", {}).get("primary", ""),
        "channel": contract.get("owner", {}).get("notification_channel", "notification_mock"),
        "reason_codes": blocking_errors,
        "freshness_state": freshness_state,
        "run_report_path": str(run_report_path),
        "message": (
            f"Scheduled delivery run {run_id} ended with {status}; inspect {run_report_path}."
            if should_notify
            else f"Scheduled delivery run {run_id} completed successfully."
        ),
        "next_manual_action": "rerun workflow_dispatch after fixing inputs or schedule contract" if should_notify else "",
    }


def collect_output_entries(root: Path) -> dict[str, dict[str, Any]]:
    entries: dict[str, dict[str, Any]] = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = relpath(path, start=root)
        if relative == "scheduled_publish_manifest.json":
            continue
        key = relative.replace("/", "_").replace(".", "_").replace("-", "_")
        entries[key] = manifest_entry(path, start=root)
    return entries


def build_scheduled_manifest(
    *,
    output_dir: Path,
    contract: dict[str, Any],
    input_paths: dict[str, Path | None],
    status: str,
    exit_code: int,
    run_id: str,
    scheduled_for_utc: str,
) -> dict[str, Any]:
    return {
        "version": WORKFLOW_VERSION,
        "schedule_id": contract.get("schedule_id"),
        "hash_algorithm": "sha256",
        "renderer_used": "scheduled_delivery_workflow",
        "status": status,
        "exit_code": exit_code,
        "run_id": run_id,
        "scheduled_for_utc": scheduled_for_utc,
        "inputs": {name: optional_manifest_entry(path, start=output_dir) for name, path in input_paths.items()},
        "outputs": collect_output_entries(output_dir),
    }


def build_schedule_run_report(
    *,
    contract: dict[str, Any],
    contract_errors: list[str],
    workflow_text: str,
    run_id: str,
    status: str,
    exit_code: int,
    scheduled_for_utc: str,
    started_at_utc: str,
    finished_at_utc: str,
    delivery_report: dict[str, Any] | None,
    delivery_published: bool,
    delivery_manifest_path: Path | None,
    source_tree_before: dict[str, str],
    source_tree_after: dict[str, str],
    history_path: Path,
    freshness_report_path: Path,
    last_success_marker_path: Path | None,
    notification_path: Path,
) -> dict[str, Any]:
    marker_errors = workflow_marker_errors(workflow_text)
    blocking_errors = []
    if contract_errors:
        blocking_errors.extend(contract_errors)
    delivery_blockers = []
    if delivery_report:
        delivery_blockers = list(delivery_report.get("summary", {}).get("blocking_errors", []))
        delivery_blockers.extend(delivery_report.get("cache_state_audit", {}).get("blocking_errors", []))
    checks = [
        check(
            "schedule_contract_declares_owner_cron_utc_history_marker_and_notifications",
            not contract_errors,
            observed=contract_errors,
            expected="owner, UTC cron, GitHub Actions caveats, history, freshness, last-success and notification policy",
            message="A schedule is operational metadata, not just a cron string.",
        ),
        check(
            "workflow_declares_schedule_manual_dispatch_and_explicit_cli_arguments",
            not marker_errors,
            observed=marker_errors,
            expected=REQUIRED_WORKFLOW_MARKERS,
            message="The generated workflow should expose both scheduled and manual recovery paths.",
        ),
        check(
            "run_history_and_freshness_report_are_written_for_every_attempt",
            history_path.is_file() and freshness_report_path.is_file(),
            observed={"history": str(history_path), "freshness_report": str(freshness_report_path)},
            expected="run_history.csv and schedule_freshness_report.json",
            message="A failed scheduled run still needs a visible operational trace.",
        ),
        check(
            "last_success_marker_updates_only_on_fresh_success",
            status != "success"
            or not delivery_published
            or (last_success_marker_path is not None and last_success_marker_path.is_file()),
            observed={"status": status, "last_success_marker": str(last_success_marker_path) if last_success_marker_path else ""},
            expected="fresh success writes last_success_marker.json",
            message="Stale or failed runs should not pretend to be the last fresh successful run.",
        ),
        check(
            "failure_notification_is_visible_to_owner",
            status == "success" or notification_path.is_file(),
            observed={"status": status, "notification": str(notification_path)},
            expected="failure_notification_mock.json for non-success statuses",
            message="Schedulers fail quietly unless the package records who should see the failure.",
        ),
        check(
            "source_truth_was_not_mutated",
            source_tree_before == source_tree_after,
            observed={"before_hash": sha256_bytes(json.dumps(source_tree_before, sort_keys=True).encode()), "after_hash": sha256_bytes(json.dumps(source_tree_after, sort_keys=True).encode())},
            expected="input source tree hashes unchanged",
            message="A scheduled refresh should publish outputs, not rewrite source artifacts.",
        ),
        check(
            "delivery_cli_report_is_reused",
            status == "schedule_contract_block" or delivery_report is not None,
            observed=delivery_report.get("status") if delivery_report else None,
            expected="delivery CLI run report",
            message="Schedule automation should compose the CLI contract instead of duplicating delivery logic.",
        ),
        check(
            "failed_runs_do_not_publish_partial_delivery_output",
            status == "success" or not delivery_published,
            observed={"status": status, "delivery_published": delivery_published, "delivery_manifest": str(delivery_manifest_path) if delivery_manifest_path else ""},
            expected="only success publishes fresh delivery output",
            message="A scheduled failure may write diagnostics, but it must not publish a half-ready delivery package.",
        ),
    ]
    report_blockers = [item["id"] for item in checks if not item["valid"] and item["severity"] == "block"]
    return {
        "version": WORKFLOW_VERSION,
        "schedule_id": contract.get("schedule_id"),
        "run_id": run_id,
        "status": status,
        "exit_code": exit_code,
        "scheduled_for_utc": scheduled_for_utc,
        "started_at_utc": started_at_utc,
        "finished_at_utc": finished_at_utc,
        "delivery_cli": {
            "status": delivery_report.get("status") if delivery_report else "",
            "exit_code": delivery_report.get("exit_code") if delivery_report else "",
            "published": delivery_published,
            "blocking_errors": delivery_blockers,
        },
        "checks": checks,
        "summary": {
            "blocking_errors": report_blockers,
            "schedule_contract_errors": contract_errors,
            "delivery_blocking_errors": delivery_blockers,
            "check_count": len(checks),
        },
    }


def run_scheduled_delivery(
    *,
    app_dir: str | Path,
    output_dir: str | Path,
    cache_state_contract_path: str | Path | None = None,
    freshness_policy_path: str | Path | None = None,
    cli_contract_path: str | Path | None = None,
    schedule_contract_path: str | Path | None = None,
    source_snapshot_utc: str | None = None,
    checked_at_utc: str | None = None,
    run_id: str = DEFAULT_RUN_ID,
    scheduled_for_utc: str = DEFAULT_SCHEDULED_FOR_UTC,
    started_at_utc: str = DEFAULT_STARTED_AT_UTC,
    finished_at_utc: str = DEFAULT_FINISHED_AT_UTC,
    check_mode: bool = False,
    allow_freshness_warning: bool = False,
    overwrite: bool = True,
    argv: list[str] | None = None,
) -> ScheduledRunResult:
    output_path = Path(output_dir).resolve()
    output_path.mkdir(parents=True, exist_ok=True)
    app_path = Path(app_dir).resolve()
    cache_contract_path = Path(cache_state_contract_path).resolve() if cache_state_contract_path else None
    freshness_path = Path(freshness_policy_path).resolve() if freshness_policy_path else None
    cli_path = Path(cli_contract_path).resolve() if cli_contract_path else None
    schedule_path = Path(schedule_contract_path).resolve() if schedule_contract_path else None
    contract = normalize_schedule_contract(read_json(schedule_path) if schedule_path else None)
    contract_errors = schedule_contract_errors(contract)
    workflow_text = build_github_actions_workflow(contract)

    contract_output_path = output_path / "schedule_contract.json"
    workflow_path = output_path / "schedule_workflow.yml"
    history_path = output_path / "run_history.csv"
    freshness_report_path = output_path / "schedule_freshness_report.json"
    run_report_path = output_path / "schedule_run_report.json"
    notification_path = output_path / "failure_notification_mock.json"
    manifest_path = output_path / "scheduled_publish_manifest.json"
    last_success_path = output_path / "last_success_marker.json"
    published_delivery_dir = output_path / "published-delivery"
    cli_report_path = output_path / "reports" / "latest_cli_run_report.json"

    write_json(contract_output_path, contract)
    write_text(workflow_path, workflow_text)
    previous_marker = read_json(last_success_path) if last_success_path.is_file() else None
    source_tree_before = hash_tree(app_path)
    delivery_report: dict[str, Any] | None = None
    delivery_result = None

    if contract_errors:
        status = "schedule_contract_block"
        exit_code = SCHEDULE_EXIT_CODE_POLICY[status]
        delivery_published = False
        delivery_manifest_path = None
    else:
        runner = load_delivery_cli_runner()
        delivery_result = runner.run_delivery_cli(
            app_dir=app_path,
            cache_state_contract_path=cache_contract_path,
            freshness_policy_path=freshness_path,
            cli_contract_path=cli_path,
            output_dir=published_delivery_dir,
            source_snapshot_utc=source_snapshot_utc,
            checked_at_utc=checked_at_utc,
            run_started_at_utc=started_at_utc,
            check_mode=check_mode,
            allow_freshness_warning=allow_freshness_warning,
            overwrite=overwrite,
            report_path=cli_report_path,
            argv=argv or [],
        )
        status = delivery_result.status
        exit_code = SCHEDULE_EXIT_CODE_POLICY.get(status, SCHEDULE_EXIT_CODE_POLICY["system_error"])
        delivery_published = bool(delivery_result.published)
        delivery_manifest_path = delivery_result.manifest_path
        delivery_report = delivery_result.report

    source_tree_after = hash_tree(app_path)
    freshness_state, delivery_freshness = determine_freshness_state(
        published_delivery_dir,
        status,
        delivery_published_this_run=delivery_published,
    )
    marker_payload = previous_marker
    if status == "success" and delivery_published:
        marker_payload = build_last_success_marker(
            contract=contract,
            run_id=run_id,
            scheduled_for_utc=scheduled_for_utc,
            finished_at_utc=finished_at_utc,
            published_delivery_dir=published_delivery_dir,
            delivery_manifest_path=delivery_manifest_path,
        )
        write_json(last_success_path, marker_payload)
    last_success_marker_path = last_success_path if last_success_path.is_file() else None

    schedule_freshness = build_schedule_freshness_report(
        contract=contract,
        run_id=run_id,
        status=status,
        scheduled_for_utc=scheduled_for_utc,
        finished_at_utc=finished_at_utc,
        last_success_marker=marker_payload,
        delivery_freshness=delivery_freshness,
        freshness_state=freshness_state,
    )
    write_json(freshness_report_path, schedule_freshness)

    delivery_blockers: list[str] = []
    if delivery_report:
        delivery_blockers.extend(delivery_report.get("summary", {}).get("blocking_errors", []))
        delivery_blockers.extend(delivery_report.get("cache_state_audit", {}).get("blocking_errors", []))
    blocking_errors = contract_errors or delivery_blockers
    notification = build_failure_notification(
        contract=contract,
        run_id=run_id,
        status=status,
        exit_code=exit_code,
        run_report_path=run_report_path,
        blocking_errors=blocking_errors,
        freshness_state=freshness_state,
    )
    write_json(notification_path, notification)

    history_row = {
        "run_id": run_id,
        "scheduled_for_utc": scheduled_for_utc,
        "started_at_utc": started_at_utc,
        "finished_at_utc": finished_at_utc,
        "status": status,
        "exit_code": exit_code,
        "published": str(delivery_published).lower(),
        "freshness_state": freshness_state,
        "notification_sent": str(notification["should_notify"]).lower(),
        "last_success_utc": marker_payload.get("last_success_utc", "") if marker_payload else "",
        "cli_report_path": str(delivery_result.report_path) if delivery_result and delivery_result.report_path else "",
        "cli_manifest_path": str(delivery_manifest_path) if delivery_manifest_path else "",
    }
    append_history_row(history_path, history_row)

    report = build_schedule_run_report(
        contract=contract,
        contract_errors=contract_errors,
        workflow_text=workflow_text,
        run_id=run_id,
        status=status,
        exit_code=exit_code,
        scheduled_for_utc=scheduled_for_utc,
        started_at_utc=started_at_utc,
        finished_at_utc=finished_at_utc,
        delivery_report=delivery_report,
        delivery_published=delivery_published,
        delivery_manifest_path=delivery_manifest_path,
        source_tree_before=source_tree_before,
        source_tree_after=source_tree_after,
        history_path=history_path,
        freshness_report_path=freshness_report_path,
        last_success_marker_path=last_success_marker_path,
        notification_path=notification_path,
    )
    write_json(run_report_path, report)

    manifest = build_scheduled_manifest(
        output_dir=output_path,
        contract=contract,
        input_paths={
            "schedule_contract": schedule_path,
            "app_manifest": app_path / "app_manifest.json",
            "app_audit": app_path / "app_audit.json",
            "cache_state_contract": cache_contract_path,
            "freshness_policy": freshness_path,
            "delivery_cli_contract": cli_path,
        },
        status=status,
        exit_code=exit_code,
        run_id=run_id,
        scheduled_for_utc=scheduled_for_utc,
    )
    write_json(manifest_path, manifest)

    return ScheduledRunResult(
        status=status,
        exit_code=exit_code,
        output_dir=output_path,
        published_delivery_dir=published_delivery_dir,
        run_report_path=run_report_path,
        freshness_report_path=freshness_report_path,
        history_path=history_path,
        last_success_marker_path=last_success_marker_path,
        notification_path=notification_path,
        manifest_path=manifest_path,
        report=report,
    )


def system_error_report(
    *,
    message: str,
    code: str,
    output_dir: Path,
    argv: list[str],
) -> dict[str, Any]:
    return {
        "version": WORKFLOW_VERSION,
        "schedule_id": default_schedule_contract()["schedule_id"],
        "status": "system_error",
        "exit_code": SCHEDULE_EXIT_CODE_POLICY["system_error"],
        "output_dir": str(output_dir),
        "command": {"program": "scheduled_delivery_workflow.py", "arguments": argv},
        "error": {"code": code, "message": message},
        "summary": {"blocking_errors": [code], "warnings": [], "check_count": 0},
        "checks": [],
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a scheduled delivery workflow package around the phase 17 delivery CLI.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--app-dir", type=Path, help="Input cache/state-ready app directory for the delivery CLI.")
    parser.add_argument("--cache-state-contract", type=Path, help="Optional cache_state_contract.json path.")
    parser.add_argument("--freshness-policy", type=Path, help="Optional freshness_policy.json path.")
    parser.add_argument("--cli-contract", type=Path, help="Optional delivery_cli_contract.json path.")
    parser.add_argument("--schedule-contract", type=Path, help="Optional schedule_contract.json path.")
    parser.add_argument("--output-dir", type=Path, required=True, help="Scheduled workflow package output directory.")
    parser.add_argument("--write-example", type=Path, help="Write sample CLI and schedule inputs before running.")
    parser.add_argument("--source-snapshot-at", help="Override source snapshot UTC timestamp passed to the delivery CLI.")
    parser.add_argument("--checked-at", help="Override freshness check UTC timestamp passed to the delivery CLI.")
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID, help="Stable scheduled run identifier.")
    parser.add_argument("--scheduled-for", default=DEFAULT_SCHEDULED_FOR_UTC, help="Scheduled UTC timestamp.")
    parser.add_argument("--started-at", default=DEFAULT_STARTED_AT_UTC, help="Actual run start UTC timestamp.")
    parser.add_argument("--finished-at", default=DEFAULT_FINISHED_AT_UTC, help="Actual run finish UTC timestamp.")
    parser.add_argument("--check", action="store_true", help="Call the delivery CLI in check mode without publishing.")
    parser.add_argument("--allow-freshness-warning", action="store_true", help="Allow stale-only delivery CLI output to publish with warning status.")
    parser.add_argument("--no-overwrite", action="store_true", help="Do not replace an existing published-delivery directory.")
    parser.add_argument("--report", type=Path, help="Optional copy of schedule_run_report.json.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    parsed = parse_args(argv)
    app_dir = parsed.app_dir
    cache_contract = parsed.cache_state_contract
    freshness_policy = parsed.freshness_policy
    cli_contract = parsed.cli_contract
    schedule_contract = parsed.schedule_contract
    if parsed.write_example:
        sample = write_sample_schedule_inputs(parsed.write_example)
        app_dir = app_dir or sample["app_dir"]
        cache_contract = cache_contract or sample["cache_state_contract_path"]
        freshness_policy = freshness_policy or sample["freshness_policy_path"]
        cli_contract = cli_contract or sample["cli_contract_path"]
        schedule_contract = schedule_contract or sample["schedule_contract_path"]
    if app_dir is None:
        report = system_error_report(
            message="missing required argument: --app-dir or --write-example",
            code="missing_app_dir",
            output_dir=parsed.output_dir.resolve(),
            argv=argv or sys.argv[1:],
        )
        if parsed.report:
            write_json(parsed.report, report)
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return SCHEDULE_EXIT_CODE_POLICY["system_error"]
    try:
        result = run_scheduled_delivery(
            app_dir=app_dir,
            output_dir=parsed.output_dir,
            cache_state_contract_path=cache_contract,
            freshness_policy_path=freshness_policy,
            cli_contract_path=cli_contract,
            schedule_contract_path=schedule_contract,
            source_snapshot_utc=parsed.source_snapshot_at,
            checked_at_utc=parsed.checked_at,
            run_id=parsed.run_id,
            scheduled_for_utc=parsed.scheduled_for,
            started_at_utc=parsed.started_at,
            finished_at_utc=parsed.finished_at,
            check_mode=parsed.check,
            allow_freshness_warning=parsed.allow_freshness_warning,
            overwrite=not parsed.no_overwrite,
            argv=argv or sys.argv[1:],
        )
    except Exception as error:
        report = system_error_report(
            message=str(error),
            code="unexpected_system_error",
            output_dir=parsed.output_dir.resolve(),
            argv=argv or sys.argv[1:],
        )
        if parsed.report:
            write_json(parsed.report, report)
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return SCHEDULE_EXIT_CODE_POLICY["system_error"]
    if parsed.report:
        write_json(parsed.report, result.report)
    response = {
        "status": result.status,
        "exit_code": result.exit_code,
        "output_dir": str(result.output_dir),
        "published_delivery_dir": str(result.published_delivery_dir) if result.published_delivery_dir.exists() else "",
        "run_report": str(result.run_report_path),
        "freshness_report": str(result.freshness_report_path),
        "history": str(result.history_path),
        "last_success_marker": str(result.last_success_marker_path) if result.last_success_marker_path else "",
        "notification": str(result.notification_path),
        "manifest": str(result.manifest_path),
    }
    print(json.dumps(response, ensure_ascii=False, indent=2, sort_keys=True))
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
