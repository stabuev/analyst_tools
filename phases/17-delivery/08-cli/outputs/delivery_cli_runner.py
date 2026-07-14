from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any


CLI_VERSION = "1.0.0"
DEFAULT_RUN_STARTED_AT_UTC = "2026-01-01T00:20:00Z"
EXIT_CODE_POLICY = {
    "success": 0,
    "data_quality_block": 10,
    "freshness_warning": 20,
    "system_error": 30,
    "usage_error": 2,
}
FRESHNESS_ONLY_BLOCKERS = {"freshness_report_is_not_stale"}
REQUIRED_CACHE_STATE_FILES = [
    "streamlit_app.py",
    "cache_state_contract.json",
    "freshness_policy.json",
    "freshness_report.json",
    "cache_state_audit.json",
    "cache_state_manifest.json",
    "cache_state_runbook.md",
    "app_contract.json",
    "app_data/metric_summary.csv",
    "app_data/claim_evidence_matrix.csv",
    "app_data/plotly_figure_spec.json",
    "downloads/stakeholder_app_bundle.zip",
]
REQUIRED_CLI_SOURCE_MARKERS = [
    "argparse.ArgumentParser",
    "\"--check\"",
    "EXIT_CODE_POLICY",
    "TemporaryDirectory",
    "publish_staged_directory",
    "os.replace",
]
FORBIDDEN_CLI_PATTERNS = [
    "input" + "(",
    "requests" + ".",
    "urllib" + ".",
    "st" + ".secrets",
    "os" + ".environ",
]


@dataclass(frozen=True)
class DeliveryCliResult:
    status: str
    exit_code: int
    published: bool
    output_dir: Path
    report_path: Path | None
    manifest_path: Path | None
    report: dict[str, Any]


class DeliveryCliError(RuntimeError):
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


def sha256_file(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def relpath(path: str | Path, *, start: str | Path) -> str:
    return Path(os.path.relpath(Path(path), Path(start))).as_posix()


def manifest_entry(path: Path, *, start: Path) -> dict[str, Any]:
    return {
        "path": relpath(path, start=start),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
    }


def optional_manifest_entry(path: Path, *, start: Path) -> dict[str, Any]:
    if path.is_file():
        return manifest_entry(path, start=start)
    return {"path": relpath(path, start=start), "sha256": "", "bytes": 0, "missing": True}


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


def default_cli_contract() -> dict[str, Any]:
    return {
        "cli_id": "trial-onboarding-delivery-cli",
        "source_cache_state_id": "trial-onboarding-cache-state-policy",
        "required_arguments": [
            "--app-dir",
            "--cache-state-contract",
            "--freshness-policy",
            "--output-dir",
        ],
        "supported_modes": ["check", "publish"],
        "path_policy": {
            "explicit_input_paths_required": True,
            "output_dir_required": True,
            "no_implicit_cwd_inputs": True,
            "write_example_is_training_only": True,
        },
        "publish_policy": {
            "build_in_staging_directory": True,
            "atomic_replace_required": True,
            "publish_manifest_required": True,
            "no_partial_publish_on_block": True,
            "overwrite_requires_flag": True,
        },
        "exit_code_policy": dict(EXIT_CODE_POLICY),
        "report_policy": {
            "json_stdout_required": True,
            "run_report_required": True,
            "include_command_arguments": True,
            "include_input_hashes": True,
            "include_output_hashes": True,
        },
    }


def normalize_cli_contract(contract: dict[str, Any] | None) -> dict[str, Any]:
    if contract is None:
        return default_cli_contract()
    normalized = default_cli_contract()
    normalized.update(contract)
    return normalized


def load_cache_state_builder():
    current = Path(__file__).resolve()
    builder_path = current.parents[2] / "07-caching-and-state" / "outputs" / "streamlit_cache_state_auditor.py"
    spec = importlib.util.spec_from_file_location("cache_state_builder_for_delivery_cli", builder_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load cache/state builder: {builder_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_sample_cli_inputs(root: str | Path) -> dict[str, Path]:
    root_path = Path(root).resolve()
    root_path.mkdir(parents=True, exist_ok=True)
    cache_builder = load_cache_state_builder()
    sample = cache_builder.write_sample_cache_state_inputs(root_path / "cache-state-inputs")
    cli_contract_path = root_path / "delivery_cli_contract.json"
    write_json(cli_contract_path, default_cli_contract())
    return {
        "app_dir": sample["app_dir"],
        "cache_state_contract_path": sample["cache_state_contract_path"],
        "freshness_policy_path": sample["freshness_policy_path"],
        "cli_contract_path": cli_contract_path,
    }


def cli_contract_errors(contract: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required_args = set(contract.get("required_arguments", []))
    if not {"--app-dir", "--output-dir"}.issubset(required_args):
        errors.append("required_arguments_must_include_app_dir_and_output_dir")
    modes = set(contract.get("supported_modes", []))
    if modes != {"check", "publish"}:
        errors.append("supported_modes_must_be_check_and_publish")
    path_policy = contract.get("path_policy", {})
    if path_policy.get("explicit_input_paths_required") is not True:
        errors.append("explicit_input_paths_required_must_be_true")
    if path_policy.get("no_implicit_cwd_inputs") is not True:
        errors.append("no_implicit_cwd_inputs_must_be_true")
    publish_policy = contract.get("publish_policy", {})
    if publish_policy.get("build_in_staging_directory") is not True:
        errors.append("build_in_staging_directory_must_be_true")
    if publish_policy.get("atomic_replace_required") is not True:
        errors.append("atomic_replace_required_must_be_true")
    if publish_policy.get("publish_manifest_required") is not True:
        errors.append("publish_manifest_required_must_be_true")
    if publish_policy.get("no_partial_publish_on_block") is not True:
        errors.append("no_partial_publish_on_block_must_be_true")
    exit_policy = contract.get("exit_code_policy", {})
    for key, value in EXIT_CODE_POLICY.items():
        if exit_policy.get(key) != value:
            errors.append(f"exit_code_{key}_must_equal_{value}")
    return sorted(errors)


def classify_cache_state_audit(audit: dict[str, Any]) -> tuple[str, int]:
    blockers = set(audit.get("summary", {}).get("blocking_errors", []))
    if not blockers:
        return "success", EXIT_CODE_POLICY["success"]
    if blockers <= FRESHNESS_ONLY_BLOCKERS:
        return "freshness_warning", EXIT_CODE_POLICY["freshness_warning"]
    return "data_quality_block", EXIT_CODE_POLICY["data_quality_block"]


def source_marker_errors() -> dict[str, list[str]]:
    source = Path(__file__).read_text(encoding="utf-8")
    missing_markers = [marker for marker in REQUIRED_CLI_SOURCE_MARKERS if marker not in source]
    forbidden_patterns = [pattern for pattern in FORBIDDEN_CLI_PATTERNS if pattern in source]
    return {"missing_markers": missing_markers, "forbidden_patterns": forbidden_patterns}


def validate_input_paths(
    *,
    app_dir: Path,
    cache_state_contract_path: Path | None,
    freshness_policy_path: Path | None,
    cli_contract_path: Path | None,
) -> list[dict[str, Any]]:
    checks = [
        {
            "path": str(app_dir),
            "exists": app_dir.is_dir(),
            "kind": "directory",
            "argument": "--app-dir",
        }
    ]
    for argument, path in [
        ("--cache-state-contract", cache_state_contract_path),
        ("--freshness-policy", freshness_policy_path),
        ("--cli-contract", cli_contract_path),
    ]:
        if path is not None:
            checks.append({"path": str(path), "exists": path.is_file(), "kind": "file", "argument": argument})
    return checks


def collect_output_entries(root: Path) -> dict[str, dict[str, Any]]:
    entries: dict[str, dict[str, Any]] = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = relpath(path, start=root)
        if relative == "cli_publish_manifest.json":
            continue
        key = relative.replace("/", "_").replace(".", "_").replace("-", "_")
        entries[key] = manifest_entry(path, start=root)
    return entries


def publish_staged_directory(staging_dir: Path, output_dir: Path, *, overwrite: bool) -> None:
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    if output_dir.exists():
        if not overwrite:
            raise DeliveryCliError(
                "output_dir_exists",
                f"output directory already exists: {output_dir}. Pass --overwrite to replace it.",
            )
        backup_dir = output_dir.with_name(f".{output_dir.name}.previous-{os.getpid()}")
        if backup_dir.exists():
            shutil.rmtree(backup_dir)
        os.replace(output_dir, backup_dir)
        try:
            os.replace(staging_dir, output_dir)
        except BaseException:
            if not output_dir.exists() and backup_dir.exists():
                os.replace(backup_dir, output_dir)
            raise
        else:
            shutil.rmtree(backup_dir)
    else:
        os.replace(staging_dir, output_dir)


def build_run_report(
    *,
    contract: dict[str, Any],
    input_path_checks: list[dict[str, Any]],
    cache_audit: dict[str, Any],
    status: str,
    exit_code: int,
    check_mode: bool,
    published: bool,
    allow_freshness_warning: bool,
    output_dir: Path,
    run_started_at_utc: str,
    argv: list[str],
) -> dict[str, Any]:
    contract_errors = cli_contract_errors(contract)
    source_errors = source_marker_errors()
    missing_inputs = [item for item in input_path_checks if not item["exists"]]
    cache_blockers = cache_audit.get("summary", {}).get("blocking_errors", [])
    expected_exit_code = EXIT_CODE_POLICY[status]
    checks = [
        check(
            "cli_contract_declares_explicit_paths_modes_publish_and_exit_codes",
            not contract_errors,
            observed=contract_errors,
            expected="explicit paths, check/publish modes, staging publish and exit code policy",
            message="The CLI contract must make operational behavior auditable before automation uses it.",
        ),
        check(
            "explicit_input_paths_exist",
            not missing_inputs,
            observed=missing_inputs,
            expected="all declared input paths exist",
            message="Delivery CLI should fail before building when an explicit input path is missing.",
        ),
        check(
            "cache_state_package_was_checked",
            "summary" in cache_audit and "blocking_errors" in cache_audit.get("summary", {}),
            observed=cache_audit.get("summary", {}),
            expected="cache_state_audit summary",
            message="CLI orchestration should reuse the cache/state audit instead of trusting file presence.",
        ),
        check(
            "exit_code_matches_status_policy",
            exit_code == expected_exit_code,
            observed={"status": status, "exit_code": exit_code},
            expected={status: expected_exit_code},
            message="Automation needs stable exit codes that do not require parsing human text.",
        ),
        check(
            "check_mode_does_not_publish",
            not check_mode or not published,
            observed={"check_mode": check_mode, "published": published},
            expected="check mode validates only",
            message="`--check` is a validation contract, not a hidden publish mode.",
        ),
        check(
            "blocked_runs_do_not_publish_partial_outputs",
            published or status in {"data_quality_block", "freshness_warning"} or check_mode,
            observed={"status": status, "published": published},
            expected="publish only ready packages or explicitly allowed freshness warnings",
            message="A data-quality blocker must not leave a half-published package.",
        ),
        check(
            "freshness_warning_publish_requires_flag",
            status != "freshness_warning" or allow_freshness_warning or not published,
            observed={"status": status, "allow_freshness_warning": allow_freshness_warning, "published": published},
            expected="stale publish is opt-in",
            message="Stale output should not be published as if it were a successful fresh run.",
        ),
        check(
            "cli_source_uses_argparse_check_mode_and_atomic_publish",
            not source_errors["missing_markers"] and not source_errors["forbidden_patterns"],
            observed=source_errors,
            expected=REQUIRED_CLI_SOURCE_MARKERS,
            message="The reusable artifact should expose a real CLI and staged publication boundary.",
        ),
    ]
    blockers = [item["id"] for item in checks if not item["valid"] and item["severity"] == "block"]
    warnings = [item["id"] for item in checks if not item["valid"] and item["severity"] == "warn"]
    return {
        "version": CLI_VERSION,
        "cli_id": contract.get("cli_id"),
        "status": status,
        "exit_code": exit_code,
        "published": published,
        "check_mode": check_mode,
        "allow_freshness_warning": allow_freshness_warning,
        "run_started_at_utc": run_started_at_utc,
        "output_dir": str(output_dir),
        "command": {
            "program": "delivery_cli_runner.py",
            "arguments": argv,
        },
        "cache_state_audit": {
            "valid": bool(cache_audit.get("valid")),
            "readiness_status": cache_audit.get("readiness_status"),
            "blocking_errors": cache_blockers,
        },
        "checks": checks,
        "summary": {
            "blocking_errors": blockers,
            "warnings": warnings,
            "check_count": len(checks),
        },
    }


def build_publish_manifest(
    *,
    staging_dir: Path,
    contract: dict[str, Any],
    input_paths: dict[str, Path | None],
    output_entries: dict[str, dict[str, Any]],
    status: str,
    exit_code: int,
    check_mode: bool,
    published: bool,
    run_started_at_utc: str,
) -> dict[str, Any]:
    return {
        "version": CLI_VERSION,
        "cli_id": contract.get("cli_id"),
        "hash_algorithm": "sha256",
        "renderer_used": "delivery_cli_runner",
        "status": status,
        "exit_code": exit_code,
        "check_mode": check_mode,
        "published": published,
        "run_started_at_utc": run_started_at_utc,
        "exit_code_policy": contract.get("exit_code_policy", {}),
        "atomic_publish": {
            "strategy": "stage_then_os_replace",
            "staging_directory_used": True,
            "overwrite_requires_flag": contract.get("publish_policy", {}).get("overwrite_requires_flag") is True,
            "publish_manifest_path": "cli_publish_manifest.json",
        },
        "inputs": {
            name: optional_manifest_entry(path, start=staging_dir) if path is not None else {"path": "", "missing": True}
            for name, path in input_paths.items()
        },
        "outputs": output_entries,
    }


def system_error_report(
    *,
    message: str,
    code: str,
    output_dir: Path,
    check_mode: bool,
    run_started_at_utc: str,
    argv: list[str],
) -> dict[str, Any]:
    return {
        "version": CLI_VERSION,
        "cli_id": default_cli_contract()["cli_id"],
        "status": "system_error",
        "exit_code": EXIT_CODE_POLICY["system_error"],
        "published": False,
        "check_mode": check_mode,
        "run_started_at_utc": run_started_at_utc,
        "output_dir": str(output_dir),
        "command": {"program": "delivery_cli_runner.py", "arguments": argv},
        "error": {"code": code, "message": message},
        "summary": {"blocking_errors": [code], "warnings": [], "check_count": 0},
        "checks": [],
    }


def run_delivery_cli(
    *,
    app_dir: str | Path,
    output_dir: str | Path,
    cache_state_contract_path: str | Path | None = None,
    freshness_policy_path: str | Path | None = None,
    cli_contract_path: str | Path | None = None,
    source_snapshot_utc: str | None = None,
    checked_at_utc: str | None = None,
    run_started_at_utc: str = DEFAULT_RUN_STARTED_AT_UTC,
    check_mode: bool = False,
    allow_freshness_warning: bool = False,
    overwrite: bool = False,
    report_path: str | Path | None = None,
    argv: list[str] | None = None,
) -> DeliveryCliResult:
    app_path = Path(app_dir).resolve()
    output_path = Path(output_dir).resolve()
    cache_contract_path = Path(cache_state_contract_path).resolve() if cache_state_contract_path else None
    freshness_path = Path(freshness_policy_path).resolve() if freshness_policy_path else None
    cli_path = Path(cli_contract_path).resolve() if cli_contract_path else None
    report_output_path = Path(report_path).resolve() if report_path else None
    cli_contract = normalize_cli_contract(read_json(cli_path) if cli_path else None)
    input_checks = validate_input_paths(
        app_dir=app_path,
        cache_state_contract_path=cache_contract_path,
        freshness_policy_path=freshness_path,
        cli_contract_path=cli_path,
    )
    missing_inputs = [item for item in input_checks if not item["exists"]]
    if missing_inputs:
        report = system_error_report(
            message="One or more explicit input paths do not exist.",
            code="missing_explicit_input_path",
            output_dir=output_path,
            check_mode=check_mode,
            run_started_at_utc=run_started_at_utc,
            argv=argv or [],
        )
        if report_output_path:
            write_json(report_output_path, report)
        return DeliveryCliResult(
            status="system_error",
            exit_code=EXIT_CODE_POLICY["system_error"],
            published=False,
            output_dir=output_path,
            report_path=report_output_path,
            manifest_path=None,
            report=report,
        )

    cache_builder = load_cache_state_builder()
    temp_parent = output_path.parent if not check_mode else None
    if temp_parent is not None:
        temp_parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".delivery-cli-stage-", dir=temp_parent) as temp_name:
        temp_root = Path(temp_name)
        staging_dir = temp_root / "package"
        cache_result = cache_builder.build_cache_state_package(
            app_dir=app_path,
            output_dir=staging_dir,
            cache_state_contract_path=cache_contract_path,
            freshness_policy_path=freshness_path,
            source_snapshot_utc=source_snapshot_utc,
            checked_at_utc=checked_at_utc,
        )
        status, exit_code = classify_cache_state_audit(cache_result.audit)
        should_publish = status == "success" or (status == "freshness_warning" and allow_freshness_warning)
        published = should_publish and not check_mode

        write_json(staging_dir / "delivery_cli_contract.json", cli_contract)
        report = build_run_report(
            contract=cli_contract,
            input_path_checks=input_checks,
            cache_audit=cache_result.audit,
            status=status,
            exit_code=exit_code,
            check_mode=check_mode,
            published=published,
            allow_freshness_warning=allow_freshness_warning,
            output_dir=output_path,
            run_started_at_utc=run_started_at_utc,
            argv=argv or [],
        )
        write_json(staging_dir / "cli_run_report.json", report)
        output_entries = collect_output_entries(staging_dir)
        manifest = build_publish_manifest(
            staging_dir=staging_dir,
            contract=cli_contract,
            input_paths={
                "app_dir_app_manifest": app_path / "app_manifest.json",
                "app_dir_app_audit": app_path / "app_audit.json",
                "cache_state_contract": cache_contract_path,
                "freshness_policy": freshness_path,
                "delivery_cli_contract": cli_path,
            },
            output_entries=output_entries,
            status=status,
            exit_code=exit_code,
            check_mode=check_mode,
            published=published,
            run_started_at_utc=run_started_at_utc,
        )
        write_json(staging_dir / "cli_publish_manifest.json", manifest)

        if published:
            publish_staged_directory(staging_dir, output_path, overwrite=overwrite)
            final_report_path = output_path / "cli_run_report.json"
            final_manifest_path = output_path / "cli_publish_manifest.json"
        else:
            final_report_path = None
            final_manifest_path = None
        if report_output_path:
            write_json(report_output_path, report)

    return DeliveryCliResult(
        status=status,
        exit_code=exit_code,
        published=published,
        output_dir=output_path,
        report_path=final_report_path or report_output_path,
        manifest_path=final_manifest_path,
        report=report,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the phase 17 delivery pipeline through an explicit check/publish CLI.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--app-dir", type=Path, help="Input cache/state-ready app source directory.")
    parser.add_argument("--cache-state-contract", type=Path, help="Optional cache_state_contract.json.")
    parser.add_argument("--freshness-policy", type=Path, help="Optional freshness_policy.json.")
    parser.add_argument("--cli-contract", type=Path, help="Optional delivery_cli_contract.json.")
    parser.add_argument("--output-dir", type=Path, required=True, help="Published delivery package directory.")
    parser.add_argument("--write-example", type=Path, help="Write sample inputs before running the CLI.")
    parser.add_argument("--source-snapshot-at", help="Override source snapshot UTC timestamp.")
    parser.add_argument("--checked-at", help="Override freshness check UTC timestamp.")
    parser.add_argument("--run-started-at", default=DEFAULT_RUN_STARTED_AT_UTC, help="Deterministic run timestamp.")
    parser.add_argument("--check", action="store_true", help="Validate inputs and pipeline without publishing output-dir.")
    parser.add_argument("--allow-freshness-warning", action="store_true", help="Publish stale-only packages with exit code 20.")
    parser.add_argument("--overwrite", action="store_true", help="Replace an existing output directory after a staged build passes.")
    parser.add_argument("--report", type=Path, help="Optional JSON run report path for check or failed runs.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    parsed = parse_args(argv)
    app_dir = parsed.app_dir
    cache_contract = parsed.cache_state_contract
    freshness_policy = parsed.freshness_policy
    cli_contract = parsed.cli_contract
    if parsed.write_example:
        sample = write_sample_cli_inputs(parsed.write_example)
        app_dir = app_dir or sample["app_dir"]
        cache_contract = cache_contract or sample["cache_state_contract_path"]
        freshness_policy = freshness_policy or sample["freshness_policy_path"]
        cli_contract = cli_contract or sample["cli_contract_path"]
    if app_dir is None:
        report = system_error_report(
            message="missing required argument: --app-dir or --write-example",
            code="missing_app_dir",
            output_dir=parsed.output_dir.resolve(),
            check_mode=parsed.check,
            run_started_at_utc=parsed.run_started_at,
            argv=argv or sys.argv[1:],
        )
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return EXIT_CODE_POLICY["system_error"]
    try:
        result = run_delivery_cli(
            app_dir=app_dir,
            output_dir=parsed.output_dir,
            cache_state_contract_path=cache_contract,
            freshness_policy_path=freshness_policy,
            cli_contract_path=cli_contract,
            source_snapshot_utc=parsed.source_snapshot_at,
            checked_at_utc=parsed.checked_at,
            run_started_at_utc=parsed.run_started_at,
            check_mode=parsed.check,
            allow_freshness_warning=parsed.allow_freshness_warning,
            overwrite=parsed.overwrite,
            report_path=parsed.report,
            argv=argv or sys.argv[1:],
        )
    except DeliveryCliError as error:
        report = system_error_report(
            message=str(error),
            code=error.code,
            output_dir=parsed.output_dir.resolve(),
            check_mode=parsed.check,
            run_started_at_utc=parsed.run_started_at,
            argv=argv or sys.argv[1:],
        )
        if parsed.report:
            write_json(parsed.report, report)
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return EXIT_CODE_POLICY["system_error"]
    except Exception as error:
        report = system_error_report(
            message=str(error),
            code="unexpected_system_error",
            output_dir=parsed.output_dir.resolve(),
            check_mode=parsed.check,
            run_started_at_utc=parsed.run_started_at,
            argv=argv or sys.argv[1:],
        )
        if parsed.report:
            write_json(parsed.report, report)
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return EXIT_CODE_POLICY["system_error"]

    response = {
        "status": result.status,
        "exit_code": result.exit_code,
        "published": result.published,
        "output_dir": str(result.output_dir),
        "report": str(result.report_path) if result.report_path else "",
        "manifest": str(result.manifest_path) if result.manifest_path else "",
        "blocking_errors": result.report.get("cache_state_audit", {}).get("blocking_errors", []),
    }
    print(json.dumps(response, ensure_ascii=False, indent=2, sort_keys=True))
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
