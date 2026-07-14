from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


PACKAGER_VERSION = "1.0.0"
REQUIRED_SPEC_FIELDS = {
    "report_id",
    "title",
    "audience",
    "decision_owner",
    "decision_status",
    "report_date",
    "source_memo_id",
    "source_workbook_id",
    "formats",
    "render",
    "parameters",
    "source_artifacts",
    "sections",
    "assumptions",
    "limitations",
    "figure_requirements",
    "confidentiality_policy",
}
REQUIRED_METRIC_COLUMNS = [
    "metric_id",
    "label",
    "current",
    "baseline",
    "threshold",
    "status",
    "owner",
]
REQUIRED_EVIDENCE_COLUMNS = [
    "claim_id",
    "evidence_id",
    "metric_id",
    "quality_status",
    "decision_impact",
]
ALLOWED_METRIC_STATUSES = {"ok", "watch", "breached"}
ALLOWED_QUALITY_STATUSES = {"pass", "warn", "block", "missing"}
SENSITIVE_FIELD_RE = re.compile(r"(email|phone|token|secret|password|ssn|passport|user_id)", re.I)
REBUILD_OUTPUT_KEYS = {"report_html", "source_links", "figure_svg"}


@dataclass(frozen=True)
class QuartoReportBuildResult:
    output_dir: Path
    project_path: Path
    qmd_path: Path
    params_path: Path
    html_path: Path
    figure_path: Path
    source_links_path: Path
    audit_path: Path
    rebuild_check_path: Path
    manifest_path: Path
    audit: dict[str, Any]


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


def sha256_file(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def relpath(path: str | Path, *, start: str | Path) -> str:
    return Path(os.path.relpath(Path(path), Path(start))).as_posix()


def is_portable_relative(path_value: str) -> bool:
    path = Path(path_value)
    return not path.is_absolute() and ".." not in path.parts


def as_number(value: str, *, field: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field} must be numeric: {value!r}") from error


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


def sample_report_spec() -> dict[str, Any]:
    return {
        "report_id": "trial-onboarding-quarto-report",
        "title": "Reproducible delivery report: onboarding rollout risk",
        "audience": "Growth weekly decision review",
        "decision_owner": "Head of Growth",
        "decision_status": "pause_rollout",
        "report_date": "2026-05-22",
        "source_memo_id": "trial-onboarding-risk-memo",
        "source_workbook_id": "trial-onboarding-stakeholder-workbook",
        "formats": ["html"],
        "render": {
            "command": "quarto render report.qmd --to html --execute-params params.yml",
            "engine": "jupyter",
            "kernel": "python3",
            "execute": True,
            "embed_resources": True,
        },
        "parameters": {
            "decision_window": "2026-05-15/2026-05-21",
            "metric_status_filter": "all",
            "freshness_cutoff": "2026-05-21",
        },
        "source_artifacts": [
            {
                "source_id": "executive_memo",
                "kind": "memo",
                "path": "executive_memo.md",
                "referenced_in_section": "decision_summary",
                "required": True,
            },
            {
                "source_id": "metric_summary",
                "kind": "table",
                "path": "metric_summary.csv",
                "referenced_in_section": "metric_summary",
                "required": True,
            },
            {
                "source_id": "claim_evidence_matrix",
                "kind": "table",
                "path": "claim_evidence_matrix.csv",
                "referenced_in_section": "evidence_lineage",
                "required": True,
            },
            {
                "source_id": "workbook_audit",
                "kind": "audit",
                "path": "workbook_audit.json",
                "referenced_in_section": "quality_gates",
                "required": True,
            },
            {
                "source_id": "memo_audit",
                "kind": "audit",
                "path": "memo_audit.json",
                "referenced_in_section": "quality_gates",
                "required": True,
            },
        ],
        "sections": [
            "decision_summary",
            "metric_summary",
            "evidence_lineage",
            "quality_gates",
            "assumptions",
            "limitations",
            "rerun",
        ],
        "assumptions": [
            "Metric rows come from the same complete decision window as the memo.",
            "Workbook audit passed before the report package was rendered.",
            "Rows are stakeholder-safe aggregates, not customer-level exports.",
        ],
        "limitations": [
            "The report preserves the upstream no-causal-claim boundary.",
            "The tiny sample is a delivery contract fixture, not a production volume test.",
            "HTML preview is deterministic; full Quarto rendering requires the external Quarto CLI.",
        ],
        "figure_requirements": [
            {
                "figure_id": "fig-guardrails",
                "path": "figures/guardrail_status.svg",
                "source": "metric_summary.csv",
                "caption": "Guardrail status by stakeholder metric.",
            }
        ],
        "confidentiality_policy": {
            "allowed_public_fields": sorted(
                set(REQUIRED_METRIC_COLUMNS) | set(REQUIRED_EVIDENCE_COLUMNS)
            ),
            "sensitive_fields": [],
        },
    }


def sample_metric_rows() -> list[dict[str, str]]:
    return [
        {
            "metric_id": "support_ticket_rate_7d",
            "label": "Support ticket rate, 7d",
            "current": "0.018",
            "baseline": "0.011",
            "threshold": "0.010",
            "status": "breached",
            "owner": "Support analytics",
        },
        {
            "metric_id": "subscription_cancel_rate_14d",
            "label": "Subscription cancellation rate, 14d",
            "current": "0.031",
            "baseline": "0.022",
            "threshold": "0.024",
            "status": "breached",
            "owner": "Growth analytics",
        },
        {
            "metric_id": "support_reason_coverage",
            "label": "Support reason coverage",
            "current": "0.740",
            "baseline": "0.910",
            "threshold": "0.900",
            "status": "watch",
            "owner": "Support analytics",
        },
    ]


def sample_evidence_rows() -> list[dict[str, str]]:
    return [
        {
            "claim_id": "guardrails-above-threshold",
            "evidence_id": "support-ticket-rate",
            "metric_id": "support_ticket_rate_7d",
            "quality_status": "pass",
            "decision_impact": "usable",
        },
        {
            "claim_id": "guardrails-above-threshold",
            "evidence_id": "cancel-rate",
            "metric_id": "subscription_cancel_rate_14d",
            "quality_status": "pass",
            "decision_impact": "usable",
        },
        {
            "claim_id": "quality-gates-usable",
            "evidence_id": "support-reason-coverage",
            "metric_id": "support_reason_coverage",
            "quality_status": "warn",
            "decision_impact": "usable_with_disclosure",
        },
        {
            "claim_id": "calendar-context-only",
            "evidence_id": "release-calendar",
            "metric_id": "__context__",
            "quality_status": "pass",
            "decision_impact": "context_only",
        },
    ]


def sample_workbook_audit() -> dict[str, Any]:
    return {
        "valid": True,
        "workbook_id": "trial-onboarding-stakeholder-workbook",
        "readiness_status": "ready",
        "summary": {"blocking_errors": [], "warnings": []},
    }


def sample_memo_audit() -> dict[str, Any]:
    return {
        "valid": True,
        "memo_id": "trial-onboarding-risk-memo",
        "readiness_status": "ready_with_warnings",
        "recommended_decision": "pause_rollout",
        "summary": {
            "blocking_errors": [],
            "warnings": ["evidence_quality_warnings_are_disclosed"],
        },
    }


def sample_executive_memo() -> str:
    return """# Executive memo: onboarding rollout risk

Recommendation: pause the rollout until support-ticket and cancellation guardrails are back
inside threshold. This memo is the upstream narrative source for the Quarto report.

Boundary: the evidence supports an operational rollout decision, not a causal claim about
the onboarding flow.
"""


def write_sample_inputs(root: str | Path) -> dict[str, Path]:
    root_path = Path(root)
    root_path.mkdir(parents=True, exist_ok=True)
    spec_path = root_path / "report_spec.json"
    metrics_path = root_path / "metric_summary.csv"
    evidence_path = root_path / "claim_evidence_matrix.csv"
    workbook_audit_path = root_path / "workbook_audit.json"
    memo_audit_path = root_path / "memo_audit.json"
    memo_path = root_path / "executive_memo.md"
    write_json(spec_path, sample_report_spec())
    write_csv(metrics_path, sample_metric_rows(), REQUIRED_METRIC_COLUMNS)
    write_csv(evidence_path, sample_evidence_rows(), REQUIRED_EVIDENCE_COLUMNS)
    write_json(workbook_audit_path, sample_workbook_audit())
    write_json(memo_audit_path, sample_memo_audit())
    memo_path.write_text(sample_executive_memo(), encoding="utf-8")
    return {
        "spec_path": spec_path,
        "metrics_path": metrics_path,
        "evidence_path": evidence_path,
        "workbook_audit_path": workbook_audit_path,
        "memo_audit_path": memo_audit_path,
        "memo_path": memo_path,
    }


def validate_inputs(
    *,
    spec: dict[str, Any],
    metrics: list[dict[str, str]],
    evidence: list[dict[str, str]],
    workbook_audit: dict[str, Any],
    memo_audit: dict[str, Any],
    source_root: Path,
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    missing_spec_fields = sorted(REQUIRED_SPEC_FIELDS - set(spec))
    checks.append(
        check(
            "spec_has_required_fields",
            not missing_spec_fields,
            observed=missing_spec_fields,
            expected=[],
            message="Report spec must define audience, render contract, sources and limitations.",
        )
    )

    missing_metric_columns = sorted(
        {
            column
            for row in metrics
            for column in REQUIRED_METRIC_COLUMNS
            if column not in row
        }
    )
    checks.append(
        check(
            "metric_summary_has_required_columns",
            bool(metrics) and not missing_metric_columns,
            observed=missing_metric_columns,
            expected=[],
            message="Metric summary is the executable report input.",
        )
    )

    missing_evidence_columns = sorted(
        {
            column
            for row in evidence
            for column in REQUIRED_EVIDENCE_COLUMNS
            if column not in row
        }
    )
    checks.append(
        check(
            "evidence_matrix_has_required_columns",
            bool(evidence) and not missing_evidence_columns,
            observed=missing_evidence_columns,
            expected=[],
            message="Report evidence lineage must preserve claim/evidence ids.",
        )
    )

    invalid_metric_statuses = sorted(
        {
            row.get("metric_id", "<missing-id>")
            for row in metrics
            if row.get("status") not in ALLOWED_METRIC_STATUSES
        }
    )
    checks.append(
        check(
            "metric_statuses_are_known",
            not invalid_metric_statuses,
            observed=invalid_metric_statuses,
            expected=sorted(ALLOWED_METRIC_STATUSES),
            message="Unknown metric status cannot drive a deterministic figure or summary.",
        )
    )

    invalid_quality_statuses = sorted(
        {
            row.get("evidence_id", "<missing-id>")
            for row in evidence
            if row.get("quality_status") not in ALLOWED_QUALITY_STATUSES
        }
    )
    checks.append(
        check(
            "evidence_quality_statuses_are_known",
            not invalid_quality_statuses,
            observed=invalid_quality_statuses,
            expected=sorted(ALLOWED_QUALITY_STATUSES),
            message="Unknown evidence quality cannot be disclosed consistently.",
        )
    )

    numeric_errors: list[str] = []
    for row in metrics:
        for field in ("current", "baseline", "threshold"):
            try:
                as_number(row.get(field, ""), field=field)
            except ValueError:
                numeric_errors.append(f"{row.get('metric_id', '<missing-id>')}:{field}")
    checks.append(
        check(
            "metric_numeric_fields_are_numbers",
            not numeric_errors,
            observed=numeric_errors,
            expected=[],
            message="Executable tables and figure generation require numeric metric fields.",
        )
    )

    checks.append(
        check(
            "upstream_workbook_audit_is_valid",
            bool(workbook_audit.get("valid")),
            observed=workbook_audit.get("summary", {}).get("blocking_errors", []),
            expected=[],
            message="Report cannot be rendered from a blocked stakeholder workbook.",
        )
    )
    checks.append(
        check(
            "upstream_memo_audit_is_valid",
            bool(memo_audit.get("valid")),
            observed=memo_audit.get("summary", {}).get("blocking_errors", []),
            expected=[],
            message="Report cannot be rendered from a blocked decision memo.",
        )
    )

    render = spec.get("render", {})
    render_command = render.get("command", "")
    checks.append(
        check(
            "render_command_targets_quarto_html_with_params",
            isinstance(render_command, str)
            and render_command.startswith("quarto render report.qmd")
            and "--to html" in render_command
            and "--execute-params params.yml" in render_command,
            observed=render_command,
            expected="quarto render report.qmd --to html --execute-params params.yml",
            message="The handoff manifest must name the reproducible Quarto render command.",
        )
    )
    checks.append(
        check(
            "render_executes_python_kernel",
            render.get("engine") == "jupyter"
            and render.get("kernel") == "python3"
            and render.get("execute") is True,
            observed=render,
            expected={"engine": "jupyter", "kernel": "python3", "execute": True},
            message="The report must be executable with the Python kernel, not a static notebook export.",
        )
    )

    assumptions = spec.get("assumptions", [])
    limitations = spec.get("limitations", [])
    checks.append(
        check(
            "assumptions_are_explicit",
            isinstance(assumptions, list) and len(assumptions) >= 2,
            observed=assumptions,
            expected="at least two assumptions",
            message="Stakeholders need assumptions near the result, not hidden in source notebooks.",
        )
    )
    checks.append(
        check(
            "limitations_are_explicit",
            isinstance(limitations, list) and len(limitations) >= 2,
            observed=limitations,
            expected="at least two limitations",
            message="Report delivery must preserve claim boundaries.",
        )
    )

    source_artifacts = spec.get("source_artifacts", [])
    artifact_errors: list[str] = []
    artifact_ids: set[str] = set()
    for item in source_artifacts:
        source_id = item.get("source_id") if isinstance(item, dict) else None
        path_value = item.get("path") if isinstance(item, dict) else None
        if not source_id or source_id in artifact_ids:
            artifact_errors.append(f"duplicate_or_missing_id:{source_id}")
        if source_id:
            artifact_ids.add(source_id)
        if not isinstance(path_value, str) or not is_portable_relative(path_value):
            artifact_errors.append(f"non_portable_path:{source_id}")
            continue
        if item.get("required", True) and not (source_root / path_value).is_file():
            artifact_errors.append(f"missing_source:{source_id}:{path_value}")
    checks.append(
        check(
            "source_artifacts_are_portable_and_present",
            isinstance(source_artifacts, list) and bool(source_artifacts) and not artifact_errors,
            observed=sorted(artifact_errors),
            expected=[],
            message="Quarto reports must link to clean local source files, not hidden absolute paths.",
        )
    )

    figure_requirements = spec.get("figure_requirements", [])
    figure_errors: list[str] = []
    for item in figure_requirements:
        figure_id = item.get("figure_id") if isinstance(item, dict) else None
        path_value = item.get("path") if isinstance(item, dict) else None
        if not isinstance(figure_id, str) or not figure_id.startswith("fig-"):
            figure_errors.append(f"bad_figure_id:{figure_id}")
        if not isinstance(path_value, str) or not is_portable_relative(path_value):
            figure_errors.append(f"bad_figure_path:{figure_id}")
    checks.append(
        check(
            "figure_requirements_are_cross_referenceable",
            isinstance(figure_requirements, list) and bool(figure_requirements) and not figure_errors,
            observed=sorted(figure_errors),
            expected=[],
            message="Report figures need portable paths and Quarto cross-reference ids.",
        )
    )

    source_headers = set()
    for rows in (metrics, evidence):
        for row in rows:
            source_headers.update(row)
    sensitive_headers = sorted(column for column in source_headers if SENSITIVE_FIELD_RE.search(column))
    sensitive_policy = spec.get("confidentiality_policy", {}).get("sensitive_fields", [])
    checks.append(
        check(
            "no_sensitive_fields_in_report_sources",
            not sensitive_headers and not sensitive_policy,
            observed={"headers": sensitive_headers, "policy": sensitive_policy},
            expected={"headers": [], "policy": []},
            message="Report package must not include sensitive fields or publish a spec that allows them.",
        )
    )
    return checks


def build_audit(checks: list[dict[str, Any]], *, report_id: str) -> dict[str, Any]:
    blockers = [item["id"] for item in checks if not item["valid"] and item["severity"] == "block"]
    warnings = [item["id"] for item in checks if not item["valid"] and item["severity"] == "warn"]
    return {
        "version": PACKAGER_VERSION,
        "valid": not blockers,
        "report_id": report_id,
        "readiness_status": "blocked" if blockers else "ready",
        "summary": {
            "blocking_errors": blockers,
            "warnings": warnings,
            "check_count": len(checks),
        },
        "checks": checks,
    }


def metric_summary(metrics: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "metric_count": len(metrics),
        "breached_count": sum(1 for row in metrics if row.get("status") == "breached"),
        "watch_count": sum(1 for row in metrics if row.get("status") == "watch"),
        "current_total": round(sum(as_number(row.get("current", "0"), field="current") for row in metrics), 6),
        "baseline_total": round(sum(as_number(row.get("baseline", "0"), field="baseline") for row in metrics), 6),
    }


def render_project_config(spec: dict[str, Any]) -> str:
    payload = {
        "project": {
            "type": "default",
            "render": ["report.qmd"],
            "output-dir": ".",
        },
        "toc": True,
        "number-sections": True,
        "execute": {
            "echo": False,
            "warning": False,
            "error": False,
        },
        "format": {
            "html": {
                "embed-resources": bool(spec.get("render", {}).get("embed_resources", True)),
                "code-fold": True,
                "anchor-sections": True,
            }
        },
    }
    return yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)


def render_params(
    *,
    spec: dict[str, Any],
    metrics_path: Path,
    evidence_path: Path,
    workbook_audit_path: Path,
    memo_audit_path: Path,
    output_dir: Path,
) -> str:
    payload = {
        "metrics_path": relpath(metrics_path, start=output_dir),
        "evidence_path": relpath(evidence_path, start=output_dir),
        "workbook_audit_path": relpath(workbook_audit_path, start=output_dir),
        "memo_audit_path": relpath(memo_audit_path, start=output_dir),
        **spec.get("parameters", {}),
    }
    return yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)


def render_qmd(spec: dict[str, Any]) -> str:
    title = spec["title"]
    figure = spec["figure_requirements"][0]
    assumptions = "\n".join(f"- {item}" for item in spec["assumptions"])
    limitations = "\n".join(f"- {item}" for item in spec["limitations"])
    source_lines = "\n".join(
        f"- `{item['source_id']}` -> `{item['path']}` ({item['kind']})"
        for item in spec["source_artifacts"]
    )
    front_matter = {
        "title": title,
        "format": {"html": {"embed-resources": True, "toc": True, "code-fold": True}},
        "execute": {"echo": False, "warning": False, "error": False},
        "jupyter": spec.get("render", {}).get("kernel", "python3"),
    }
    front = yaml.safe_dump(front_matter, sort_keys=False, allow_unicode=True).strip()
    return f"""---
{front}
---

```{{python}}
#| tags: [parameters]
metrics_path = "metric_summary.csv"
evidence_path = "claim_evidence_matrix.csv"
workbook_audit_path = "workbook_audit.json"
memo_audit_path = "memo_audit.json"
decision_window = "{spec['parameters'].get('decision_window', '')}"
metric_status_filter = "{spec['parameters'].get('metric_status_filter', 'all')}"
freshness_cutoff = "{spec['parameters'].get('freshness_cutoff', '')}"
```

```{{python}}
#| label: load-clean-inputs
#| include: false
import json
from pathlib import Path
import pandas as pd

metrics = pd.read_csv(metrics_path)
evidence = pd.read_csv(evidence_path)
workbook_audit = json.loads(Path(workbook_audit_path).read_text())
memo_audit = json.loads(Path(memo_audit_path).read_text())
breached_count = int((metrics["status"] == "breached").sum())
```

## Decision summary

Audience: **{spec['audience']}**.
Decision owner: **{spec['decision_owner']}**.
Decision status: **{spec['decision_status']}**.
Report date: **{spec['report_date']}**.

This report is rendered from clean inputs with:

```{{python}}
#| label: reproducibility-check
print(f"metrics={{len(metrics)}} breached={{breached_count}} workbook_valid={{workbook_audit['valid']}} memo_valid={{memo_audit['valid']}}")
```

## Metric summary

```{{python}}
#| label: tbl-metrics
#| tbl-cap: "Stakeholder metric summary"
metrics[["metric_id", "label", "current", "baseline", "threshold", "status", "owner"]]
```

See @fig-guardrails for the stakeholder status picture.

![{figure['caption']}]({figure['path']}){{#{figure['figure_id']}}}

## Evidence lineage

```{{python}}
#| label: tbl-evidence
#| tbl-cap: "Claim to evidence lineage"
evidence[["claim_id", "evidence_id", "metric_id", "quality_status", "decision_impact"]]
```

## Source links

{source_lines}

## Assumptions

{assumptions}

## Limitations

{limitations}

## Rerun

Render command:

```bash
{spec['render']['command']}
```
"""


def status_color(status: str) -> str:
    return {
        "ok": "#B7E1CD",
        "watch": "#FFF2CC",
        "breached": "#F4CCCC",
    }.get(status, "#E5E7EB")


def render_svg(metrics: list[dict[str, str]], *, title: str) -> str:
    width = 860
    height = 260
    left = 260
    top = 48
    bar_height = 34
    gap = 24
    scale = 560
    rows: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" role="img" aria-label="{html.escape(title)}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="24" y="28" font-family="Arial" font-size="18" font-weight="700" fill="#111827">{html.escape(title)}</text>',
    ]
    for index, row in enumerate(metrics):
        y = top + index * (bar_height + gap)
        current = as_number(row["current"], field="current")
        threshold = as_number(row["threshold"], field="threshold")
        bar_width = max(4, min(scale, int(current * scale)))
        threshold_x = left + min(scale, int(threshold * scale))
        rows.append(
            f'<text x="24" y="{y + 23}" font-family="Arial" font-size="13" fill="#374151">{html.escape(row["label"])}</text>'
        )
        rows.append(
            f'<rect x="{left}" y="{y}" width="{bar_width}" height="{bar_height}" fill="{status_color(row["status"])}" stroke="#111827" stroke-width="1"/>'
        )
        rows.append(
            f'<line x1="{threshold_x}" y1="{y - 5}" x2="{threshold_x}" y2="{y + bar_height + 5}" stroke="#991B1B" stroke-width="2"/>'
        )
        rows.append(
            f'<text x="{left + bar_width + 8}" y="{y + 22}" font-family="Arial" font-size="12" fill="#111827">{current:.3f} / threshold {threshold:.3f}</text>'
        )
    rows.append("</svg>")
    return "\n".join(rows) + "\n"


def render_html_table(rows: list[dict[str, str]], columns: list[str]) -> str:
    header = "".join(f"<th>{html.escape(column)}</th>" for column in columns)
    body_rows = []
    for row in rows:
        cells = "".join(f"<td>{html.escape(str(row.get(column, '')))}</td>" for column in columns)
        body_rows.append(f"<tr>{cells}</tr>")
    return f"<table><thead><tr>{header}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"


def render_html_preview(
    *,
    spec: dict[str, Any],
    metrics: list[dict[str, str]],
    evidence: list[dict[str, str]],
    source_links: list[dict[str, str]],
) -> str:
    summary = metric_summary(metrics)
    assumptions = "".join(f"<li>{html.escape(item)}</li>" for item in spec["assumptions"])
    limitations = "".join(f"<li>{html.escape(item)}</li>" for item in spec["limitations"])
    links = "".join(
        f'<li><a href="{html.escape(row["path"])}">{html.escape(row["source_id"])}</a> '
        f'({html.escape(row["kind"])}, sha256 {html.escape(row["sha256"][:12])})</li>'
        for row in source_links
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{html.escape(spec['title'])}</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 2rem; color: #111827; }}
    table {{ border-collapse: collapse; margin: 1rem 0; width: 100%; }}
    th, td {{ border: 1px solid #D1D5DB; padding: 0.45rem; text-align: left; }}
    th {{ background: #1F4E79; color: white; }}
    .callout {{ border-left: 4px solid #1F4E79; padding: 0.75rem 1rem; background: #F3F4F6; }}
    .status {{ font-weight: 700; }}
  </style>
</head>
<body>
  <h1>{html.escape(spec['title'])}</h1>
  <section id="decision-summary">
    <h2>Decision summary</h2>
    <p class="callout">Audience: {html.escape(spec['audience'])}. Owner: {html.escape(spec['decision_owner'])}.
    Decision status: <span class="status">{html.escape(spec['decision_status'])}</span>.
    Report date: {html.escape(spec['report_date'])}.</p>
    <p>Metrics: {summary['metric_count']}; breached: {summary['breached_count']}; watch: {summary['watch_count']}.</p>
  </section>
  <section id="metric-summary">
    <h2>Metric summary</h2>
    {render_html_table(metrics, REQUIRED_METRIC_COLUMNS)}
    <figure id="fig-guardrails">
      <img src="figures/guardrail_status.svg" alt="Guardrail status by stakeholder metric">
      <figcaption>Guardrail status by stakeholder metric.</figcaption>
    </figure>
  </section>
  <section id="evidence-lineage">
    <h2>Evidence lineage</h2>
    {render_html_table(evidence, REQUIRED_EVIDENCE_COLUMNS)}
  </section>
  <section id="source-links">
    <h2>Source links</h2>
    <ul>{links}</ul>
  </section>
  <section id="assumptions">
    <h2>Assumptions</h2>
    <ul>{assumptions}</ul>
  </section>
  <section id="limitations">
    <h2>Limitations</h2>
    <ul>{limitations}</ul>
  </section>
  <section id="rerun">
    <h2>Rerun</h2>
    <pre>{html.escape(spec['render']['command'])}</pre>
  </section>
</body>
</html>
"""


def build_source_links(spec: dict[str, Any], *, source_root: Path, output_dir: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for item in spec.get("source_artifacts", []):
        source_path = source_root / item["path"]
        rows.append(
            {
                "source_id": item["source_id"],
                "kind": item["kind"],
                "path": relpath(source_path, start=output_dir),
                "sha256": sha256_file(source_path) if source_path.is_file() else "",
                "referenced_in_section": item.get("referenced_in_section", ""),
            }
        )
    return rows


def manifest_entry(path: Path) -> dict[str, Any]:
    return {
        "path": path.name if path.parent.name != "figures" else f"figures/{path.name}",
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
    }


def compare_rebuild(
    *,
    previous_manifest_path: Path | None,
    current_inputs: dict[str, dict[str, Any]],
    current_outputs: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if previous_manifest_path is None or not previous_manifest_path.is_file():
        return {
            "status": "initial_render",
            "valid": True,
            "changed_inputs": [],
            "changed_outputs": [],
            "stale_outputs": [],
            "unexpected_output_changes": [],
        }
    previous = read_json(previous_manifest_path)
    previous_inputs = previous.get("inputs", {})
    previous_outputs = previous.get("outputs", {})
    changed_inputs = sorted(
        key
        for key, value in current_inputs.items()
        if previous_inputs.get(key, {}).get("sha256") != value.get("sha256")
    )
    changed_outputs = sorted(
        key
        for key, value in current_outputs.items()
        if key in REBUILD_OUTPUT_KEYS
        and previous_outputs.get(key, {}).get("sha256") != value.get("sha256")
    )
    stale_outputs = sorted(REBUILD_OUTPUT_KEYS - set(changed_outputs)) if changed_inputs else []
    unexpected_output_changes = changed_outputs if not changed_inputs else []
    return {
        "status": "compared_to_previous_manifest",
        "valid": not stale_outputs and not unexpected_output_changes,
        "changed_inputs": changed_inputs,
        "changed_outputs": changed_outputs,
        "stale_outputs": stale_outputs,
        "unexpected_output_changes": unexpected_output_changes,
    }


def audit_report_package(
    *,
    output_dir: str | Path,
    spec: dict[str, Any],
    metrics: list[dict[str, str]],
    evidence: list[dict[str, str]],
    workbook_audit: dict[str, Any],
    memo_audit: dict[str, Any],
    source_root: str | Path,
    initial_checks: list[dict[str, Any]],
) -> dict[str, Any]:
    output_path = Path(output_dir)
    source_root_path = Path(source_root)
    qmd_path = output_path / "report.qmd"
    html_path = output_path / "report.html"
    source_links_path = output_path / "source_links.csv"
    figure_path = output_path / "figures" / "guardrail_status.svg"
    checks = list(initial_checks)

    checks.append(
        check(
            "quarto_project_files_exist",
            (output_path / "_quarto.yml").is_file() and qmd_path.is_file() and (output_path / "params.yml").is_file(),
            observed=sorted(path.name for path in output_path.glob("*")),
            expected=["_quarto.yml", "params.yml", "report.qmd"],
            message="A reusable report package needs Quarto project config, params and qmd source.",
        )
    )

    qmd_text = qmd_path.read_text(encoding="utf-8") if qmd_path.is_file() else ""
    checks.append(
        check(
            "qmd_contains_executable_python_and_parameters",
            "```{python}" in qmd_text
            and "#| tags: [parameters]" in qmd_text
            and "#| label: tbl-metrics" in qmd_text
            and "@fig-guardrails" in qmd_text,
            observed={
                "python_blocks": qmd_text.count("```{python}"),
                "has_parameters": "#| tags: [parameters]" in qmd_text,
                "has_fig_ref": "@fig-guardrails" in qmd_text,
            },
            expected="parameters cell, executable blocks, table and figure cross-reference",
            message="Report source must be executable and navigable, not a pasted static export.",
        )
    )

    checks.append(
        check(
            "html_preview_exists_and_mentions_sources",
            html_path.is_file()
            and "Source links" in html_path.read_text(encoding="utf-8")
            and "fig-guardrails" in html_path.read_text(encoding="utf-8"),
            observed=html_path.name if html_path.is_file() else None,
            expected="report.html with source links and figure reference",
            message="Lesson preview keeps the report auditable even when Quarto CLI is absent.",
        )
    )

    expected_source_ids = {item["source_id"] for item in spec.get("source_artifacts", [])}
    if source_links_path.is_file():
        link_rows = read_csv(source_links_path)
        observed_source_ids = {row.get("source_id", "") for row in link_rows}
        missing_hashes = sorted(row.get("source_id", "") for row in link_rows if len(row.get("sha256", "")) != 64)
    else:
        observed_source_ids = set()
        missing_hashes = sorted(expected_source_ids)
    checks.append(
        check(
            "source_links_cover_required_artifacts",
            expected_source_ids == observed_source_ids and not missing_hashes,
            observed={"missing_ids": sorted(expected_source_ids - observed_source_ids), "bad_hashes": missing_hashes},
            expected=sorted(expected_source_ids),
            message="Every source artifact cited by the report must be linkable and checksummed.",
        )
    )

    figure_checks: list[str] = []
    for item in spec.get("figure_requirements", []):
        required_path = output_path / item["path"]
        if not required_path.is_file():
            figure_checks.append(f"missing:{item['figure_id']}")
        if item["figure_id"] not in qmd_text:
            figure_checks.append(f"unreferenced:{item['figure_id']}")
    checks.append(
        check(
            "required_figures_exist_and_are_referenced",
            not figure_checks,
            observed=sorted(figure_checks),
            expected=[],
            message="Figures are delivery artifacts and cannot be silently dropped.",
        )
    )

    project_config = yaml.safe_load((output_path / "_quarto.yml").read_text(encoding="utf-8")) if (output_path / "_quarto.yml").is_file() else {}
    checks.append(
        check(
            "quarto_project_embeds_html_resources",
            project_config.get("format", {}).get("html", {}).get("embed-resources") is True
            and project_config.get("project", {}).get("render") == ["report.qmd"],
            observed=project_config,
            expected={"project.render": ["report.qmd"], "format.html.embed-resources": True},
            message="HTML handoff should be self-contained unless the next format lesson changes the contract.",
        )
    )

    return build_audit(checks, report_id=spec.get("report_id", "<missing-report-id>"))


def build_quarto_report(
    *,
    spec_path: str | Path,
    metrics_path: str | Path,
    evidence_path: str | Path,
    workbook_audit_path: str | Path,
    memo_audit_path: str | Path,
    memo_path: str | Path | None = None,
    output_dir: str | Path,
    previous_manifest_path: str | Path | None = None,
) -> QuartoReportBuildResult:
    spec_file = Path(spec_path)
    metrics_file = Path(metrics_path)
    evidence_file = Path(evidence_path)
    workbook_audit_file = Path(workbook_audit_path)
    memo_audit_file = Path(memo_audit_path)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    (output_path / "figures").mkdir(parents=True, exist_ok=True)
    source_root = spec_file.parent

    spec = read_json(spec_file)
    metrics = read_csv(metrics_file)
    evidence = read_csv(evidence_file)
    workbook_audit = read_json(workbook_audit_file)
    memo_audit = read_json(memo_audit_file)

    input_checks = validate_inputs(
        spec=spec,
        metrics=metrics,
        evidence=evidence,
        workbook_audit=workbook_audit,
        memo_audit=memo_audit,
        source_root=source_root,
    )

    project_path = output_path / "_quarto.yml"
    params_path = output_path / "params.yml"
    qmd_path = output_path / "report.qmd"
    html_path = output_path / "report.html"
    figure_path = output_path / "figures" / "guardrail_status.svg"
    source_links_path = output_path / "source_links.csv"
    audit_path = output_path / "report_audit.json"
    rebuild_check_path = output_path / "rebuild_check.json"
    manifest_path = output_path / "render_manifest.json"

    project_path.write_text(render_project_config(spec), encoding="utf-8")
    params_path.write_text(
        render_params(
            spec=spec,
            metrics_path=metrics_file,
            evidence_path=evidence_file,
            workbook_audit_path=workbook_audit_file,
            memo_audit_path=memo_audit_file,
            output_dir=output_path,
        ),
        encoding="utf-8",
    )
    qmd_path.write_text(render_qmd(spec), encoding="utf-8")
    figure_path.write_text(render_svg(metrics, title="Guardrail status by stakeholder metric"), encoding="utf-8")
    source_links = build_source_links(spec, source_root=source_root, output_dir=output_path)
    write_csv(
        source_links_path,
        source_links,
        ["source_id", "kind", "path", "sha256", "referenced_in_section"],
    )
    html_path.write_text(
        render_html_preview(spec=spec, metrics=metrics, evidence=evidence, source_links=source_links),
        encoding="utf-8",
    )

    audit = audit_report_package(
        output_dir=output_path,
        spec=spec,
        metrics=metrics,
        evidence=evidence,
        workbook_audit=workbook_audit,
        memo_audit=memo_audit,
        source_root=source_root,
        initial_checks=input_checks,
    )
    write_json(audit_path, audit)

    input_entries = {
        "report_spec": manifest_entry(spec_file),
        "metric_summary": manifest_entry(metrics_file),
        "claim_evidence_matrix": manifest_entry(evidence_file),
        "workbook_audit": manifest_entry(workbook_audit_file),
        "memo_audit": manifest_entry(memo_audit_file),
    }
    memo_source = source_root / "executive_memo.md"
    if memo_source.is_file():
        input_entries["executive_memo"] = manifest_entry(memo_source)

    output_entries = {
        "project_config": manifest_entry(project_path),
        "params": manifest_entry(params_path),
        "report_qmd": manifest_entry(qmd_path),
        "report_html": manifest_entry(html_path),
        "source_links": manifest_entry(source_links_path),
        "report_audit": manifest_entry(audit_path),
        "figure_svg": manifest_entry(figure_path),
    }
    previous = Path(previous_manifest_path) if previous_manifest_path is not None else None
    rebuild_check = compare_rebuild(
        previous_manifest_path=previous,
        current_inputs=input_entries,
        current_outputs=output_entries,
    )
    write_json(rebuild_check_path, rebuild_check)
    output_entries["rebuild_check"] = manifest_entry(rebuild_check_path)

    manifest = {
        "version": PACKAGER_VERSION,
        "report_id": spec.get("report_id"),
        "hash_algorithm": "sha256",
        "quarto_cli_available": shutil.which("quarto") is not None,
        "render_command": spec.get("render", {}).get("command"),
        "renderer_used": "lesson_deterministic_html_preview",
        "inputs": input_entries,
        "outputs": output_entries,
        "rebuild_check": rebuild_check,
    }
    write_json(manifest_path, manifest)

    return QuartoReportBuildResult(
        output_dir=output_path,
        project_path=project_path,
        qmd_path=qmd_path,
        params_path=params_path,
        html_path=html_path,
        figure_path=figure_path,
        source_links_path=source_links_path,
        audit_path=audit_path,
        rebuild_check_path=rebuild_check_path,
        manifest_path=manifest_path,
        audit=audit,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a reproducible Quarto report package.")
    parser.add_argument("--spec", type=Path, help="Path to report_spec.json.")
    parser.add_argument("--metrics", type=Path, help="Path to metric_summary.csv.")
    parser.add_argument("--evidence", type=Path, help="Path to claim_evidence_matrix.csv.")
    parser.add_argument("--workbook-audit", type=Path, help="Path to workbook_audit.json.")
    parser.add_argument("--memo-audit", type=Path, help="Path to memo_audit.json.")
    parser.add_argument("--previous-manifest", type=Path, help="Optional previous render_manifest.json.")
    parser.add_argument("--output-dir", type=Path, required=True, help="Directory for the report package.")
    parser.add_argument("--write-example", type=Path, help="Write example inputs to this directory before building.")
    parser.add_argument("--fail-on-invalid", action="store_true", help="Return exit code 2 when the report audit fails.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.write_example:
        paths = write_sample_inputs(args.write_example)
    else:
        required = {
            "spec_path": args.spec,
            "metrics_path": args.metrics,
            "evidence_path": args.evidence,
            "workbook_audit_path": args.workbook_audit,
            "memo_audit_path": args.memo_audit,
        }
        missing = sorted(name for name, value in required.items() if value is None)
        if missing:
            raise SystemExit(f"missing required arguments: {', '.join(missing)}")
        paths = required

    result = build_quarto_report(
        spec_path=paths["spec_path"],
        metrics_path=paths["metrics_path"],
        evidence_path=paths["evidence_path"],
        workbook_audit_path=paths["workbook_audit_path"],
        memo_audit_path=paths["memo_audit_path"],
        output_dir=args.output_dir,
        previous_manifest_path=args.previous_manifest,
    )
    response = {
        "valid": result.audit["valid"],
        "readiness_status": result.audit["readiness_status"],
        "blocking_errors": result.audit["summary"]["blocking_errors"],
        "report": str(result.qmd_path),
        "html": str(result.html_path),
        "manifest": str(result.manifest_path),
    }
    print(json.dumps(response, ensure_ascii=False, indent=2, sort_keys=True))
    if args.fail_on_invalid and not result.audit["valid"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
