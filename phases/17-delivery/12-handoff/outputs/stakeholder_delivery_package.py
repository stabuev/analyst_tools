from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


HANDOFF_VERSION = "1.0.0"
DEFAULT_PACKAGE_NAME = "stakeholder-delivery-package"
DEFAULT_DELIVERY_ID = "trial-onboarding-weekly-delivery"
HANDOFF_EXIT_CODE_POLICY = {
    "success": 0,
    "handoff_contract_block": 2,
    "upstream_package_block": 10,
    "system_error": 30,
}
ALLOWED_DECISION_STATUSES = {
    "ship_now",
    "ship_with_warnings",
    "blocked_by_quality_gate",
    "needs_methodology_review",
    "stale_input",
    "owner_handoff_only",
}
REQUIRED_CONSUMER_FORMATS = {"memo", "workbook", "report", "interactive", "app", "automation"}
OPTIONAL_INTERFACE_FORMATS = {"optional-api", "optional-container"}
FORBIDDEN_PUBLIC_MARKERS = [
    "TOKEN=",
    "SECRET=",
    "PASSWORD=",
    "API_KEY=",
    "BEGIN PRIVATE KEY",
    "sk_live_",
    "ya_oauth",
]
TEXT_SUFFIXES = {
    ".csv",
    ".html",
    ".json",
    ".md",
    ".py",
    ".qmd",
    ".svg",
    ".txt",
    ".yml",
    ".yaml",
}
REQUIRED_PACKAGE_FILES = [
    "input/upstream-package-manifest.json",
    "input/delivery-spec.json",
    "input/evidence-index.csv",
    "input/quality-gate-summary.json",
    "memo/executive-memo.md",
    "memo/claim-evidence-matrix.csv",
    "memo/memo_audit.json",
    "workbook/stakeholder-workbook.xlsx",
    "workbook/workbook-audit.json",
    "workbook/data_dictionary.csv",
    "report/report.qmd",
    "report/report.html",
    "report/report.pdf",
    "report/report.docx",
    "report/format_qa_report.json",
    "interactive/plotly_figure_spec.json",
    "interactive/interactive-appendix.html",
    "interactive/static-fallbacks/metric_status.svg",
    "app/streamlit_app.py",
    "app/app_contract.json",
    "app/freshness-panel.json",
    "automation/delivery_cli_contract.json",
    "automation/schedule.yml",
    "automation/run-history.csv",
    "automation/freshness-report.json",
    "automation/cli_run_report.json",
    "optional-api/api.py",
    "optional-api/openapi-schema.json",
    "optional-api/api-contract-tests.json",
    "optional-api/api_audit.json",
    "optional-container/Dockerfile",
    "optional-container/.dockerignore",
    "optional-container/docker_build_context_report.json",
    "optional-container/docker_run_manifest.json",
    "optional-container/docker_audit.json",
    "handoff/runbook.md",
    "handoff/support-policy.md",
    "handoff/changelog.md",
    "handoff/stakeholder-email.md",
    "handoff/handoff_contract_tests.json",
    "handoff/handoff_audit.json",
    "manifest.json",
]


@dataclass(frozen=True)
class StakeholderDeliveryResult:
    status: str
    valid: bool
    decision_status: str
    output_dir: Path
    package_dir: Path
    audit_path: Path
    manifest_path: Path
    quality_summary_path: Path
    report: dict[str, Any]


def read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: str | Path, payload: Any) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def read_csv(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def write_csv(path: str | Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def write_text(path: str | Path, text: str) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(text, encoding="utf-8")


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


def optional_manifest_entry(path: Path | None, *, start: Path) -> dict[str, Any]:
    if path is not None and path.is_file():
        return manifest_entry(path, start=start)
    if path is not None:
        return {"path": relpath(path, start=start), "sha256": "", "bytes": 0, "missing": True}
    return {"path": "", "sha256": "", "bytes": 0, "missing": True}


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


def load_module(relative_lesson: str, artifact_name: str, module_name: str):
    current = Path(__file__).resolve()
    artifact_path = current.parents[2] / relative_lesson / "outputs" / artifact_name
    spec = importlib.util.spec_from_file_location(module_name, artifact_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module: {artifact_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_docker_builder():
    return load_module("11-docker", "docker_packaging_audit.py", "docker_packaging_audit_for_handoff")


def load_workbook_builder():
    return load_module("02-excel-xlsxwriter", "stakeholder_workbook_builder.py", "stakeholder_workbook_builder_for_handoff")


def default_handoff_contract() -> dict[str, Any]:
    return {
        "delivery_id": DEFAULT_DELIVERY_ID,
        "version": HANDOFF_VERSION,
        "decision_status": "ship_now",
        "owner": {
            "primary": "support-analytics-owner",
            "backup": "product-analytics-backup",
            "escalation_channel": "#trial-onboarding-delivery",
        },
        "cadence": "weekly Monday 06:17 UTC",
        "rerun_command": (
            "uv run --locked python phases/17-delivery/12-handoff/outputs/"
            "stakeholder_delivery_package.py --write-example /tmp/stakeholder-handoff-example "
            "--output-dir /tmp/stakeholder-delivery-package"
        ),
        "consumer_formats": sorted(REQUIRED_CONSUMER_FORMATS),
        "optional_interfaces": sorted(OPTIONAL_INTERFACE_FORMATS),
        "known_limitations": [
            "Tiny teaching data demonstrates delivery contracts and is not production volume.",
            "Optional API and Docker packages are local interfaces, not cloud deployment claims.",
            "Decision recommendation inherits upstream evidence boundaries and quality gates.",
        ],
        "support_policy": {
            "response_time": "next business day for freshness or rerun issues",
            "escalation_path": [
                "#trial-onboarding-delivery",
                "support-analytics-owner",
                "product-analytics-backup",
            ],
            "retirement_triggers": [
                "decision no longer active",
                "owner and backup owner unavailable",
                "quality gate blocked for two consecutive scheduled runs",
                "freshness overdue for two cadences",
                "upstream methodology replaced by a new evidence package",
            ],
            "out_of_scope": [
                "new causal claims beyond upstream evidence",
                "production API authentication",
                "registry or cloud deployment of the optional Docker image",
            ],
        },
        "confidentiality_policy": {
            "public_artifacts_no_secrets": True,
            "sensitive_columns_redacted": True,
            "no_runtime_credentials_required": True,
        },
    }


def normalize_handoff_contract(contract: dict[str, Any] | None) -> dict[str, Any]:
    normalized = default_handoff_contract()
    if not contract:
        return normalized
    for key, value in contract.items():
        if isinstance(value, dict) and isinstance(normalized.get(key), dict):
            merged = dict(normalized[key])
            merged.update(value)
            normalized[key] = merged
        else:
            normalized[key] = value
    return normalized


def handoff_contract_errors(contract: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not contract.get("delivery_id"):
        errors.append("delivery_id_required")
    if contract.get("decision_status") not in ALLOWED_DECISION_STATUSES:
        errors.append("decision_status_must_be_allowed")
    owner = contract.get("owner", {})
    for field in ["primary", "backup", "escalation_channel"]:
        if not owner.get(field):
            errors.append(f"owner_{field}_required")
    if owner.get("primary") and owner.get("primary") == owner.get("backup"):
        errors.append("backup_owner_must_differ_from_primary")
    if not contract.get("cadence"):
        errors.append("cadence_required")
    rerun_command = contract.get("rerun_command", "")
    if "stakeholder_delivery_package.py" not in rerun_command or "--output-dir" not in rerun_command:
        errors.append("rerun_command_must_reference_handoff_builder_and_output_dir")
    consumer_formats = set(contract.get("consumer_formats", []))
    missing_formats = REQUIRED_CONSUMER_FORMATS - consumer_formats
    for item in sorted(missing_formats):
        errors.append(f"missing_consumer_format:{item}")
    optional = set(contract.get("optional_interfaces", []))
    missing_optional = OPTIONAL_INTERFACE_FORMATS - optional
    for item in sorted(missing_optional):
        errors.append(f"missing_optional_interface:{item}")
    if len(contract.get("known_limitations", [])) < 2:
        errors.append("known_limitations_must_have_at_least_two_items")
    support = contract.get("support_policy", {})
    if not support.get("response_time"):
        errors.append("support_response_time_required")
    if len(support.get("escalation_path", [])) < 2:
        errors.append("support_escalation_path_must_have_two_steps")
    if len(support.get("retirement_triggers", [])) < 2:
        errors.append("retirement_triggers_must_have_at_least_two_items")
    confidentiality = contract.get("confidentiality_policy", {})
    for field in ["public_artifacts_no_secrets", "sensitive_columns_redacted", "no_runtime_credentials_required"]:
        if not confidentiality.get(field):
            errors.append(f"confidentiality_{field}_required")
    return errors


def source_layout(source_root: str | Path) -> dict[str, Path]:
    root = Path(source_root).resolve()
    cli_inputs = root / "fastapi-inputs" / "schedule-inputs" / "cli-inputs"
    app_inputs = cli_inputs / "cache-state-inputs" / "app-inputs"
    plotly_inputs = app_inputs / "plotly-inputs"
    return {
        "root": root,
        "cli_inputs": cli_inputs,
        "quarto_inputs": plotly_inputs / "format-inputs" / "quarto-inputs",
        "quarto_report": plotly_inputs / "format-inputs" / "quarto-report-package",
        "multi_format_report": plotly_inputs / "multi-format-report",
        "interactive_appendix": app_inputs / "interactive-appendix",
        "published_delivery": root / "fastapi-inputs" / "scheduled-package" / "published-delivery",
        "scheduled_package": root / "fastapi-inputs" / "scheduled-package",
        "api_package": root / "fastapi-package" / "fastapi-delivery-api",
    }


def required_source_map(
    *,
    source_root: str | Path,
    docker_package_dir: str | Path,
    workbook_package_dir: str | Path,
) -> dict[str, Path]:
    layout = source_layout(source_root)
    docker_dir = Path(docker_package_dir).resolve()
    workbook_dir = Path(workbook_package_dir).resolve()
    return {
        "memo/executive-memo.md": layout["quarto_inputs"] / "executive_memo.md",
        "memo/claim-evidence-matrix.csv": layout["quarto_inputs"] / "claim_evidence_matrix.csv",
        "memo/memo_audit.json": layout["quarto_inputs"] / "memo_audit.json",
        "workbook/stakeholder-workbook.xlsx": workbook_dir / "stakeholder_workbook.xlsx",
        "workbook/workbook-audit.json": workbook_dir / "workbook_audit.json",
        "workbook/data_dictionary.csv": workbook_dir / "data_dictionary.csv",
        "report/report.qmd": layout["quarto_report"] / "report.qmd",
        "report/report.html": layout["multi_format_report"] / "report.html",
        "report/report.pdf": layout["multi_format_report"] / "report.pdf",
        "report/report.docx": layout["multi_format_report"] / "report.docx",
        "report/format_qa_report.json": layout["multi_format_report"] / "format_qa_report.json",
        "report/render_manifest.json": layout["quarto_report"] / "render_manifest.json",
        "report/source_links.csv": layout["quarto_report"] / "source_links.csv",
        "interactive/plotly_figure_spec.json": layout["interactive_appendix"] / "plotly_figure_spec.json",
        "interactive/interactive-appendix.html": layout["interactive_appendix"] / "interactive_appendix.html",
        "interactive/static-fallbacks/metric_status.svg": layout["interactive_appendix"] / "static-fallbacks" / "metric_status.svg",
        "interactive/interaction_audit.json": layout["interactive_appendix"] / "interaction_audit.json",
        "app/streamlit_app.py": layout["published_delivery"] / "streamlit_app.py",
        "app/app_contract.json": layout["published_delivery"] / "app_contract.json",
        "app/freshness-panel.json": layout["published_delivery"] / "freshness_report.json",
        "app/app_audit.json": layout["published_delivery"] / "app_audit.json",
        "app/cache_state_contract.json": layout["published_delivery"] / "cache_state_contract.json",
        "app/downloads/stakeholder_app_bundle.zip": layout["published_delivery"] / "downloads" / "stakeholder_app_bundle.zip",
        "automation/delivery_cli_contract.json": layout["published_delivery"] / "delivery_cli_contract.json",
        "automation/schedule.yml": layout["scheduled_package"] / "schedule_workflow.yml",
        "automation/run-history.csv": layout["scheduled_package"] / "run_history.csv",
        "automation/freshness-report.json": layout["scheduled_package"] / "schedule_freshness_report.json",
        "automation/cli_run_report.json": layout["published_delivery"] / "cli_run_report.json",
        "automation/schedule_run_report.json": layout["scheduled_package"] / "schedule_run_report.json",
        "automation/scheduled_publish_manifest.json": layout["scheduled_package"] / "scheduled_publish_manifest.json",
        "optional-api/api.py": layout["api_package"] / "api.py",
        "optional-api/openapi-schema.json": layout["api_package"] / "openapi_schema.json",
        "optional-api/api-contract-tests.json": layout["api_package"] / "api_contract_tests.json",
        "optional-api/api_audit.json": layout["api_package"] / "api_audit.json",
        "optional-api/api_manifest.json": layout["api_package"] / "api_manifest.json",
        "optional-api/cli_fallback.md": layout["api_package"] / "cli_fallback.md",
        "optional-container/Dockerfile": docker_dir / "Dockerfile",
        "optional-container/.dockerignore": docker_dir / ".dockerignore",
        "optional-container/docker_build_context_report.json": docker_dir / "docker_build_context_report.json",
        "optional-container/docker_run_manifest.json": docker_dir / "docker_run_manifest.json",
        "optional-container/docker_audit.json": docker_dir / "docker_audit.json",
        "optional-container/docker_manifest.json": docker_dir / "docker_manifest.json",
        "optional-container/docker_runbook.md": docker_dir / "docker_runbook.md",
    }


def copy_sources(package_dir: Path, source_map: dict[str, Path]) -> list[str]:
    missing: list[str] = []
    for relative, source in source_map.items():
        destination = package_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.is_file():
            shutil.copy2(source, destination)
        else:
            missing.append(relative)
    return missing


def audit_payload(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"valid": False, "status": "missing", "summary": {"blocking_errors": ["missing_audit_file"]}}
    return read_json(path)


def blocking_errors_from(payload: dict[str, Any]) -> list[str]:
    summary = payload.get("summary", {})
    errors = summary.get("blocking_errors", [])
    if isinstance(errors, list):
        return [str(error) for error in errors]
    return []


def warnings_from(payload: dict[str, Any]) -> list[str]:
    summary = payload.get("summary", {})
    warnings = summary.get("warnings", [])
    if isinstance(warnings, list):
        return [str(warning) for warning in warnings]
    warning_ledger = payload.get("warning_ledger", [])
    if isinstance(warning_ledger, list):
        return [str(item.get("id", item)) if isinstance(item, dict) else str(item) for item in warning_ledger]
    return []


def payload_is_valid(payload: dict[str, Any]) -> bool:
    if payload.get("valid") is False:
        return False
    if payload.get("status") in {"data_quality_block", "api_contract_block", "container_contract_block", "system_error"}:
        return False
    if payload.get("readiness_status") in {"blocked", "invalid"}:
        return False
    return not blocking_errors_from(payload)


def build_quality_gate_summary(package_dir: Path, contract: dict[str, Any]) -> dict[str, Any]:
    gate_paths = {
        "memo": package_dir / "memo" / "memo_audit.json",
        "workbook": package_dir / "workbook" / "workbook-audit.json",
        "report": package_dir / "report" / "format_qa_report.json",
        "interactive": package_dir / "interactive" / "interaction_audit.json",
        "app": package_dir / "app" / "app_audit.json",
        "automation": package_dir / "automation" / "schedule_run_report.json",
        "optional_api": package_dir / "optional-api" / "api_audit.json",
        "optional_container": package_dir / "optional-container" / "docker_audit.json",
    }
    gates: list[dict[str, Any]] = []
    for layer, path in gate_paths.items():
        payload = audit_payload(path)
        gates.append(
            {
                "layer": layer,
                "path": relpath(path, start=package_dir),
                "valid": payload_is_valid(payload),
                "status": payload.get("status") or payload.get("readiness_status") or "unknown",
                "blocking_errors": blocking_errors_from(payload),
                "warnings": warnings_from(payload),
            }
        )
    freshness = audit_payload(package_dir / "automation" / "freshness-report.json")
    freshness_state = str(freshness.get("freshness_state", "unknown"))
    all_valid = all(gate["valid"] for gate in gates)
    all_warnings = [warning for gate in gates for warning in gate["warnings"]]
    if not all_valid:
        decision_status = "blocked_by_quality_gate"
    elif freshness_state != "fresh":
        decision_status = "stale_input"
    elif all_warnings and contract.get("decision_status") == "ship_now":
        decision_status = "ship_with_warnings"
    else:
        decision_status = str(contract.get("decision_status", "ship_now"))
    return {
        "version": HANDOFF_VERSION,
        "delivery_id": contract["delivery_id"],
        "decision_status": decision_status,
        "all_quality_gates_valid": all_valid,
        "freshness_state": freshness_state,
        "gates": gates,
        "blocking_layers": [gate["layer"] for gate in gates if not gate["valid"]],
        "warning_count": len(all_warnings),
    }


def build_evidence_index(package_dir: Path, contract: dict[str, Any]) -> list[dict[str, Any]]:
    rows = [
        {"layer": "memo", "artifact": "executive memo", "path": "memo/executive-memo.md", "purpose": "decision narrative and claim boundary"},
        {"layer": "workbook", "artifact": "stakeholder workbook", "path": "workbook/stakeholder-workbook.xlsx", "purpose": "tabular stakeholder view"},
        {"layer": "report", "artifact": "multi-format report", "path": "report/report.html", "purpose": "reproducible report output"},
        {"layer": "interactive", "artifact": "Plotly appendix", "path": "interactive/interactive-appendix.html", "purpose": "interactive decision exploration"},
        {"layer": "app", "artifact": "Streamlit app", "path": "app/streamlit_app.py", "purpose": "local stakeholder interface"},
        {"layer": "automation", "artifact": "scheduled workflow", "path": "automation/schedule.yml", "purpose": "rerun cadence and freshness visibility"},
        {"layer": "optional-api", "artifact": "FastAPI endpoint", "path": "optional-api/api.py", "purpose": "optional read-only API surface"},
        {"layer": "optional-container", "artifact": "Docker package", "path": "optional-container/Dockerfile", "purpose": "optional local runtime wrapper"},
    ]
    for row in rows:
        path = package_dir / row["path"]
        row["sha256"] = sha256_file(path) if path.is_file() else ""
        row["owner"] = contract["owner"]["primary"]
    return rows


def scan_public_artifacts(package_dir: Path) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    assignment_patterns = {
        "TOKEN=": re.compile(r"(?:^|[\s;\"'])TOKEN\s*=", re.IGNORECASE | re.MULTILINE),
        "SECRET=": re.compile(r"(?:^|[\s;\"'])SECRET\s*=", re.IGNORECASE | re.MULTILINE),
        "PASSWORD=": re.compile(r"(?:^|[\s;\"'])PASSWORD\s*=", re.IGNORECASE | re.MULTILINE),
        "API_KEY=": re.compile(r"(?:^|[\s;\"'])API_KEY\s*=", re.IGNORECASE | re.MULTILINE),
    }
    for path in sorted(item for item in package_dir.rglob("*") if item.is_file()):
        relative = relpath(path, start=package_dir)
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for marker, pattern in assignment_patterns.items():
            if pattern.search(text):
                findings.append({"path": relative, "marker": marker})
        for marker in ["BEGIN PRIVATE KEY", "sk_live_", "ya_oauth"]:
            if marker in text:
                findings.append({"path": relative, "marker": marker})
    return findings


def build_handoff_contract_tests(contract: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": HANDOFF_VERSION,
        "delivery_id": contract["delivery_id"],
        "tests": [
            {
                "id": "all_consumer_formats_are_present",
                "expected": "memo, workbook, report, interactive appendix, app and automation files exist.",
                "source": "stakeholder-delivery-package/",
            },
            {
                "id": "optional_interfaces_are_contract_checked",
                "expected": "FastAPI and Docker are included only with passing audits.",
                "source": "optional-api/api_audit.json and optional-container/docker_audit.json",
            },
            {
                "id": "owner_backup_escalation_and_retirement_are_documented",
                "expected": "Runbook and support policy name owner, backup owner, escalation path and retirement triggers.",
                "source": "handoff/runbook.md and handoff/support-policy.md",
            },
            {
                "id": "decision_status_is_explicit_and_allowed",
                "expected": "Decision status is one of the phase contract statuses.",
                "source": "input/quality-gate-summary.json",
            },
            {
                "id": "public_artifacts_have_no_secret_markers",
                "expected": "No environment-style credential assignments or private-key material in public text artifacts.",
                "source": "handoff_audit.json",
            },
            {
                "id": "manifest_hashes_every_package_file",
                "expected": "Root manifest records SHA-256 for all package files except itself.",
                "source": "manifest.json",
            },
        ],
    }


def build_runbook(contract: dict[str, Any], quality_summary: dict[str, Any]) -> str:
    owner = contract["owner"]
    return f"""# Stakeholder Delivery Runbook

## Decision Status

- Delivery id: `{contract["delivery_id"]}`
- Decision status: `{quality_summary["decision_status"]}`
- Freshness state: `{quality_summary["freshness_state"]}`
- Cadence: {contract["cadence"]}

## Owners

- Primary owner: {owner["primary"]}
- Backup owner: {owner["backup"]}
- Escalation channel: {owner["escalation_channel"]}

## Rerun

```bash
{contract["rerun_command"]}
```

## Package Map

- `memo/` - executive memo and claim-evidence matrix.
- `workbook/` - stakeholder workbook and workbook audit.
- `report/` - QMD source and HTML/PDF/DOCX outputs.
- `interactive/` - Plotly HTML appendix and static fallback.
- `app/` - Streamlit app, freshness panel and app contract.
- `automation/` - CLI/schedule handoff, run history and freshness report.
- `optional-api/` - read-only FastAPI interface.
- `optional-container/` - local Docker wrapper and context audit.

## Known Limitations

{chr(10).join(f"- {item}" for item in contract["known_limitations"])}
"""


def build_support_policy(contract: dict[str, Any]) -> str:
    support = contract["support_policy"]
    return f"""# Support Policy

## Response

{support["response_time"]}.

## Escalation

{chr(10).join(f"- {step}" for step in support["escalation_path"])}

## Boundaries

{chr(10).join(f"- {item}" for item in support.get("out_of_scope", []))}

## When To Retire This Artifact

Retire or replace this delivery package when any trigger below is true:

{chr(10).join(f"- {item}" for item in support["retirement_triggers"])}
"""


def build_changelog(contract: dict[str, Any]) -> str:
    return f"""# Changelog

## [1.0.0] - 2026-01-05

### Added

- Final stakeholder delivery package for `{contract["delivery_id"]}`.
- Handoff runbook, support policy, stakeholder email and checksum manifest.
- Memo, workbook, report, interactive appendix, Streamlit app, CLI/schedule, optional API and optional Docker package.

### Changed

- Consolidated prior phase 17 delivery artifacts into one auditable package tree.

### Security

- Public artifact scan checks for secret markers and private-key material.
"""


def build_stakeholder_email(contract: dict[str, Any], quality_summary: dict[str, Any]) -> str:
    owner = contract["owner"]
    return f"""Subject: Trial onboarding weekly delivery is ready ({quality_summary["decision_status"]})

Hi team,

The stakeholder delivery package `{contract["delivery_id"]}` is ready for review.

- Decision status: `{quality_summary["decision_status"]}`
- Freshness state: `{quality_summary["freshness_state"]}`
- Primary owner: {owner["primary"]}
- Backup owner: {owner["backup"]}
- Escalation: {owner["escalation_channel"]}

Start with `memo/executive-memo.md`, then use the workbook/report/app depending on your workflow.
The package includes rerun instructions, known limitations, support policy and SHA-256 manifest.
"""


def collect_manifest_entries(package_dir: Path) -> dict[str, dict[str, Any]]:
    entries: dict[str, dict[str, Any]] = {}
    for path in sorted(item for item in package_dir.rglob("*") if item.is_file()):
        relative = relpath(path, start=package_dir)
        if relative == "manifest.json":
            continue
        key = relative.replace("/", "_").replace(".", "_").replace("-", "_")
        entries[key] = manifest_entry(path, start=package_dir)
    return entries


def build_manifest(
    *,
    package_dir: Path,
    source_root: Path,
    docker_package_dir: Path,
    workbook_package_dir: Path,
    handoff_contract_input_path: Path | None,
    status: str,
    valid: bool,
    decision_status: str,
) -> dict[str, Any]:
    return {
        "version": HANDOFF_VERSION,
        "renderer_used": "stakeholder_delivery_package",
        "status": status,
        "valid": valid,
        "decision_status": decision_status,
        "hash_algorithm": "sha256",
        "inputs": {
            "source_root": {"path": str(source_root), "sha256": "", "bytes": 0, "directory": True},
            "docker_manifest": optional_manifest_entry(Path(docker_package_dir) / "docker_manifest.json", start=package_dir),
            "workbook_manifest": optional_manifest_entry(Path(workbook_package_dir) / "manifest.json", start=package_dir),
            "handoff_contract_input": optional_manifest_entry(handoff_contract_input_path, start=package_dir),
        },
        "outputs": collect_manifest_entries(package_dir),
    }


def package_presence_errors(package_dir: Path) -> list[str]:
    return [
        relative
        for relative in REQUIRED_PACKAGE_FILES
        if relative not in {"manifest.json", "handoff/handoff_audit.json"}
        and not (package_dir / relative).is_file()
    ]


def build_stakeholder_delivery_package(
    *,
    source_root: str | Path,
    docker_package_dir: str | Path,
    workbook_package_dir: str | Path,
    output_dir: str | Path,
    handoff_contract_path: str | Path | None = None,
    overwrite: bool = True,
) -> StakeholderDeliveryResult:
    output_path = Path(output_dir).resolve()
    package_dir = output_path / DEFAULT_PACKAGE_NAME
    if package_dir.exists() and overwrite:
        shutil.rmtree(package_dir)
    if package_dir.exists():
        raise FileExistsError(f"output package already exists: {package_dir}")
    package_dir.mkdir(parents=True, exist_ok=True)

    source_path = Path(source_root).resolve()
    docker_path = Path(docker_package_dir).resolve()
    workbook_path = Path(workbook_package_dir).resolve()
    input_contract_path = Path(handoff_contract_path).resolve() if handoff_contract_path else None
    contract = normalize_handoff_contract(read_json(input_contract_path) if input_contract_path else None)
    contract_errors = handoff_contract_errors(contract)

    missing_sources = copy_sources(
        package_dir,
        required_source_map(
            source_root=source_path,
            docker_package_dir=docker_path,
            workbook_package_dir=workbook_path,
        ),
    )
    write_json(package_dir / "input" / "delivery-spec.json", contract)
    scheduled_manifest = source_layout(source_path)["scheduled_package"] / "scheduled_publish_manifest.json"
    write_json(
        package_dir / "input" / "upstream-package-manifest.json",
        read_json(scheduled_manifest) if scheduled_manifest.is_file() else {"missing": str(scheduled_manifest)},
    )

    quality_summary = build_quality_gate_summary(package_dir, contract)
    write_json(package_dir / "input" / "quality-gate-summary.json", quality_summary)
    write_csv(
        package_dir / "input" / "evidence-index.csv",
        build_evidence_index(package_dir, contract),
        ["layer", "artifact", "path", "purpose", "sha256", "owner"],
    )
    write_json(package_dir / "handoff" / "handoff_contract_tests.json", build_handoff_contract_tests(contract))
    write_text(package_dir / "handoff" / "runbook.md", build_runbook(contract, quality_summary))
    write_text(package_dir / "handoff" / "support-policy.md", build_support_policy(contract))
    write_text(package_dir / "handoff" / "changelog.md", build_changelog(contract))
    write_text(package_dir / "handoff" / "stakeholder-email.md", build_stakeholder_email(contract, quality_summary))

    missing_package_files = package_presence_errors(package_dir)
    secret_findings = scan_public_artifacts(package_dir)
    decision_status = quality_summary["decision_status"]
    checks = [
        check(
            "handoff_contract_names_owner_backup_cadence_rerun_support_and_retirement",
            not contract_errors,
            observed=contract_errors,
            expected="delivery id, allowed decision status, primary/backup owners, rerun command, support and retirement policy",
            message="A delivery package without owner and retirement policy is a file dump, not a handoff.",
        ),
        check(
            "required_delivery_tree_contains_all_consumer_formats_and_optional_interfaces",
            not missing_sources and not missing_package_files,
            observed={"missing_sources": missing_sources, "missing_package_files": missing_package_files},
            expected=REQUIRED_PACKAGE_FILES,
            message="The final package should expose the full delivery surface in one predictable tree.",
        ),
        check(
            "quality_gate_summary_allows_decision_status_without_hiding_blockers",
            quality_summary["all_quality_gates_valid"] and decision_status in ALLOWED_DECISION_STATUSES,
            observed=quality_summary,
            expected="all gates valid and decision status is explicit",
            message="Decision status should be derived from evidence gates and freshness, not from optimism.",
        ),
        check(
            "handoff_docs_include_rerun_owner_escalation_limitations_and_retirement",
            all(
                marker in (package_dir / "handoff" / "runbook.md").read_text(encoding="utf-8")
                + (package_dir / "handoff" / "support-policy.md").read_text(encoding="utf-8")
                for marker in [
                    contract["owner"]["primary"],
                    contract["owner"]["backup"],
                    contract["owner"]["escalation_channel"],
                    contract["rerun_command"],
                    "When To Retire This Artifact",
                ]
            ),
            observed="handoff/runbook.md + handoff/support-policy.md",
            expected="owner, backup, escalation, rerun command and retirement section",
            message="The next owner must know how to rerun, escalate and retire the artifact.",
        ),
        check(
            "public_artifacts_have_no_secret_or_private_key_markers",
            not secret_findings,
            observed=secret_findings,
            expected=FORBIDDEN_PUBLIC_MARKERS,
            message="The handoff package is meant to travel; it cannot carry credentials.",
        ),
        check(
            "changelog_is_human_readable_and_names_notable_delivery_changes",
            "## [1.0.0]" in (package_dir / "handoff" / "changelog.md").read_text(encoding="utf-8")
            and "### Added" in (package_dir / "handoff" / "changelog.md").read_text(encoding="utf-8")
            and "### Security" in (package_dir / "handoff" / "changelog.md").read_text(encoding="utf-8"),
            observed=(package_dir / "handoff" / "changelog.md").read_text(encoding="utf-8"),
            expected="versioned changelog with Added and Security sections",
            message="Stakeholders need notable changes, not raw commit history.",
        ),
        check(
            "handoff_contract_tests_cover_tree_optional_interfaces_status_secrets_and_manifest",
            len(build_handoff_contract_tests(contract)["tests"]) >= 6,
            observed=build_handoff_contract_tests(contract),
            expected="contract tests cover package tree, optional interfaces, support policy, decision status, secrets and manifest",
            message="The final package ships reviewable expectations with the artifacts.",
        ),
    ]
    blocking_errors = [item["id"] for item in checks if not item["valid"] and item["severity"] == "block"]
    if missing_sources or not quality_summary["all_quality_gates_valid"]:
        status = "upstream_package_block"
    elif contract_errors or secret_findings or missing_package_files:
        status = "handoff_contract_block"
    elif blocking_errors:
        status = "handoff_contract_block"
    else:
        status = "success"
    valid = not blocking_errors
    audit = {
        "version": HANDOFF_VERSION,
        "delivery_id": contract.get("delivery_id"),
        "status": status,
        "valid": valid,
        "decision_status": decision_status,
        "source_root": str(source_path),
        "docker_package_dir": str(docker_path),
        "workbook_package_dir": str(workbook_path),
        "package_dir": str(package_dir),
        "checks": checks,
        "summary": {
            "blocking_errors": blocking_errors,
            "contract_errors": contract_errors,
            "missing_sources": missing_sources,
            "missing_package_files": missing_package_files,
            "secret_findings": secret_findings,
            "quality_blocking_layers": quality_summary["blocking_layers"],
            "check_count": len(checks),
        },
    }
    audit_path = package_dir / "handoff" / "handoff_audit.json"
    write_json(audit_path, audit)

    manifest = build_manifest(
        package_dir=package_dir,
        source_root=source_path,
        docker_package_dir=docker_path,
        workbook_package_dir=workbook_path,
        handoff_contract_input_path=input_contract_path,
        status=status,
        valid=valid,
        decision_status=decision_status,
    )
    manifest_path = package_dir / "manifest.json"
    write_json(manifest_path, manifest)

    return StakeholderDeliveryResult(
        status=status,
        valid=valid,
        decision_status=decision_status,
        output_dir=output_path,
        package_dir=package_dir,
        audit_path=audit_path,
        manifest_path=manifest_path,
        quality_summary_path=package_dir / "input" / "quality-gate-summary.json",
        report=audit,
    )


def write_sample_handoff_inputs(root: str | Path) -> dict[str, Path]:
    root_path = Path(root).resolve()
    root_path.mkdir(parents=True, exist_ok=True)
    docker_builder = load_docker_builder()
    source_root = root_path / "delivery-source"
    docker_sample = docker_builder.write_sample_docker_inputs(source_root)
    docker_result = docker_builder.build_docker_packaging_audit(
        api_package_dir=docker_sample["api_package_dir"],
        container_contract_path=docker_sample["container_contract_path"],
        output_dir=root_path / "docker-package",
    )

    workbook_builder = load_workbook_builder()
    workbook_inputs = workbook_builder.write_sample_inputs(root_path / "workbook-inputs")
    workbook_result = workbook_builder.build_stakeholder_workbook(
        spec_path=workbook_inputs["spec_path"],
        metrics_path=workbook_inputs["metrics_path"],
        evidence_path=workbook_inputs["evidence_path"],
        memo_audit_path=workbook_inputs["memo_audit_path"],
        output_dir=root_path / "workbook-package",
    )

    contract_path = root_path / "handoff_contract.json"
    write_json(contract_path, default_handoff_contract())
    return {
        "source_root": source_root,
        "docker_package_dir": docker_result.package_dir,
        "workbook_package_dir": workbook_result.output_dir,
        "handoff_contract_path": contract_path,
    }


def system_error_report(
    *,
    message: str,
    code: str,
    output_dir: Path,
    argv: list[str],
) -> dict[str, Any]:
    return {
        "version": HANDOFF_VERSION,
        "status": "system_error",
        "valid": False,
        "decision_status": "blocked_by_quality_gate",
        "exit_code": HANDOFF_EXIT_CODE_POLICY["system_error"],
        "output_dir": str(output_dir),
        "command": {"program": "stakeholder_delivery_package.py", "arguments": argv},
        "error": {"code": code, "message": message},
        "summary": {"blocking_errors": [code], "warnings": [], "check_count": 0},
        "checks": [],
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the final stakeholder delivery handoff package for phase 17.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--source-root", type=Path, help="Root written by write_sample_handoff_inputs or an equivalent phase 17 source tree.")
    parser.add_argument("--docker-package-dir", type=Path, help="Docker package produced by lesson 17/11.")
    parser.add_argument("--workbook-package-dir", type=Path, help="Workbook package produced by lesson 17/02.")
    parser.add_argument("--handoff-contract", type=Path, help="Optional handoff_contract.json path.")
    parser.add_argument("--output-dir", type=Path, required=True, help="Output directory for stakeholder-delivery-package.")
    parser.add_argument("--write-example", type=Path, help="Write sample upstream delivery, workbook, Docker and handoff contract inputs.")
    parser.add_argument("--no-overwrite", action="store_true", help="Do not replace an existing stakeholder-delivery-package directory.")
    parser.add_argument("--fail-on-invalid", action="store_true", help="Return non-zero when handoff checks fail.")
    parser.add_argument("--report", type=Path, help="Optional copy of handoff_audit.json.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    parsed = parse_args(argv)
    source_root = parsed.source_root
    docker_package_dir = parsed.docker_package_dir
    workbook_package_dir = parsed.workbook_package_dir
    handoff_contract = parsed.handoff_contract
    if parsed.write_example:
        sample = write_sample_handoff_inputs(parsed.write_example)
        source_root = source_root or sample["source_root"]
        docker_package_dir = docker_package_dir or sample["docker_package_dir"]
        workbook_package_dir = workbook_package_dir or sample["workbook_package_dir"]
        handoff_contract = handoff_contract or sample["handoff_contract_path"]
    missing = [
        name
        for name, value in [
            ("--source-root", source_root),
            ("--docker-package-dir", docker_package_dir),
            ("--workbook-package-dir", workbook_package_dir),
        ]
        if value is None
    ]
    if missing:
        report = system_error_report(
            message="missing required arguments: " + ", ".join(missing),
            code="missing_handoff_inputs",
            output_dir=parsed.output_dir.resolve(),
            argv=argv or sys.argv[1:],
        )
        if parsed.report:
            write_json(parsed.report, report)
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return HANDOFF_EXIT_CODE_POLICY["system_error"]
    try:
        result = build_stakeholder_delivery_package(
            source_root=source_root,
            docker_package_dir=docker_package_dir,
            workbook_package_dir=workbook_package_dir,
            handoff_contract_path=handoff_contract,
            output_dir=parsed.output_dir,
            overwrite=not parsed.no_overwrite,
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
        return HANDOFF_EXIT_CODE_POLICY["system_error"]
    if parsed.report:
        write_json(parsed.report, result.report)
    response = {
        "status": result.status,
        "valid": result.valid,
        "decision_status": result.decision_status,
        "output_dir": str(result.output_dir),
        "package_dir": str(result.package_dir),
        "quality_summary": str(result.quality_summary_path),
        "audit": str(result.audit_path),
        "manifest": str(result.manifest_path),
    }
    print(json.dumps(response, ensure_ascii=False, indent=2, sort_keys=True))
    if result.valid:
        return HANDOFF_EXIT_CODE_POLICY["success"]
    if parsed.fail_on_invalid:
        return HANDOFF_EXIT_CODE_POLICY.get(result.status, HANDOFF_EXIT_CODE_POLICY["handoff_contract_block"])
    return HANDOFF_EXIT_CODE_POLICY["success"]


if __name__ == "__main__":
    raise SystemExit(main())
