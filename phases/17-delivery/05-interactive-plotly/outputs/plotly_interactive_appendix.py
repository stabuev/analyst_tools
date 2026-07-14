from __future__ import annotations

import argparse
import csv
import hashlib
import html
import importlib.util
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import plotly
import plotly.graph_objects as go
import plotly.io as pio


APPENDIX_VERSION = "1.0.0"
REQUIRED_DELIVERY_FILES = [
    "report.html",
    "report.pdf",
    "report.docx",
    "format_qa_report.json",
    "format_manifest.json",
    "link_audit.csv",
]
REQUIRED_SOURCE_IDS = ["metric_summary", "claim_evidence_matrix"]
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
REQUIRED_FILTERS = ["all", "ok", "watch", "breached"]
SENSITIVE_FIELD_RE = re.compile(r"(email|phone|token|secret|password|ssn|passport|user_id)", re.I)
SENSITIVE_VALUE_RE = re.compile(r"[\w.%-]+@[\w.-]+\.[A-Za-z]{2,}|(?:token|secret|password)=\S+", re.I)
PRIMARY_OUTPUT_KEYS = {
    "interactive_html",
    "plotly_figure_spec",
    "static_fallback_svg",
    "source_table_links",
}


@dataclass(frozen=True)
class InteractiveAppendixBuildResult:
    output_dir: Path
    html_path: Path
    figure_spec_path: Path
    fallback_path: Path
    source_links_path: Path
    audit_path: Path
    manifest_path: Path
    interactive_spec_path: Path
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


def default_interactive_spec() -> dict[str, Any]:
    return {
        "appendix_id": "trial-onboarding-plotly-appendix",
        "source_delivery_id": "trial-onboarding-multi-format-report",
        "figure_id": "fig-interactive-guardrails",
        "audience_task": "Investigate which guardrail metrics drive the pause_rollout decision.",
        "default_filter": "all",
        "allowed_filters": ["all", "ok", "watch", "breached"],
        "hover_fields": [
            "metric_id",
            "label",
            "status",
            "current",
            "baseline",
            "threshold",
            "owner",
            "evidence_count",
            "decision_impacts",
        ],
        "source_table_ids": ["metric_summary", "claim_evidence_matrix"],
        "redaction_policy": {
            "forbidden_fields": ["email", "phone", "token", "secret", "password", "user_id"],
            "redact_values": True,
        },
        "static_fallback_required": True,
        "include_plotlyjs": "inline",
    }


def load_format_renderer():
    current = Path(__file__).resolve()
    renderer_path = current.parents[2] / "04-document-formats" / "outputs" / "multi_format_report_renderer.py"
    spec = importlib.util.spec_from_file_location("multi_format_renderer_for_plotly", renderer_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load format renderer: {renderer_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_sample_delivery_package(root: str | Path) -> dict[str, Path]:
    root_path = Path(root)
    root_path.mkdir(parents=True, exist_ok=True)
    renderer = load_format_renderer()
    sample = renderer.write_sample_report_package(root_path / "format-inputs")
    format_result = renderer.build_multi_format_report(
        report_dir=sample["report_dir"],
        format_spec_path=sample["format_spec_path"],
        output_dir=root_path / "multi-format-report",
    )
    interactive_spec_path = root_path / "interactive_spec.json"
    write_json(interactive_spec_path, default_interactive_spec())
    return {
        "delivery_dir": format_result.output_dir,
        "interactive_spec_path": interactive_spec_path,
        "source_report_dir": sample["report_dir"],
    }


def normalize_interactive_spec(spec: dict[str, Any] | None) -> dict[str, Any]:
    return default_interactive_spec() if spec is None else dict(spec)


def resolve_source_tables(delivery_dir: str | Path) -> dict[str, Any]:
    delivery_path = Path(delivery_dir)
    manifest_path = delivery_path / "format_manifest.json"
    manifest = read_json(manifest_path) if manifest_path.is_file() else {}
    source_links_entry = manifest.get("inputs", {}).get("source_links", {})
    if source_links_entry.get("path"):
        source_links_path = (delivery_path / source_links_entry["path"]).resolve()
    else:
        source_links_path = delivery_path / "source_links.csv"
    report_dir = source_links_path.parent
    source_links = read_csv(source_links_path) if source_links_path.is_file() else []
    resolved: dict[str, Any] = {
        "manifest": manifest,
        "source_links_path": source_links_path,
        "report_dir": report_dir,
        "source_links": source_links,
        "tables": {},
    }
    for source_id in REQUIRED_SOURCE_IDS:
        row = next((item for item in source_links if item.get("source_id") == source_id), None)
        if row is None:
            continue
        path = Path(row.get("path", ""))
        table_path = path if path.is_absolute() else (report_dir / path).resolve()
        resolved["tables"][source_id] = {
            "path": table_path,
            "source_link": row,
            "rows": read_csv(table_path) if table_path.is_file() else [],
        }
    return resolved


def as_float(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def sensitive_columns(rows: list[dict[str, str]]) -> list[str]:
    headers = {column for row in rows for column in row}
    return sorted(column for column in headers if SENSITIVE_FIELD_RE.search(column))


def sensitive_values(rows: list[dict[str, str]]) -> list[str]:
    values: list[str] = []
    for row in rows:
        for column, value in row.items():
            text = str(value or "")
            if text and (SENSITIVE_FIELD_RE.search(column) or SENSITIVE_VALUE_RE.search(text)):
                values.append(text)
    return sorted(set(values))


def evidence_summary(evidence_rows: list[dict[str, str]]) -> dict[str, dict[str, Any]]:
    summary: dict[str, dict[str, Any]] = {}
    for row in evidence_rows:
        metric_id = row.get("metric_id", "")
        if not metric_id or metric_id == "__context__":
            continue
        bucket = summary.setdefault(metric_id, {"evidence_count": 0, "decision_impacts": set(), "quality_statuses": set()})
        bucket["evidence_count"] += 1
        bucket["decision_impacts"].add(row.get("decision_impact", ""))
        bucket["quality_statuses"].add(row.get("quality_status", ""))
    normalized: dict[str, dict[str, Any]] = {}
    for metric_id, bucket in summary.items():
        normalized[metric_id] = {
            "evidence_count": bucket["evidence_count"],
            "decision_impacts": ", ".join(sorted(value for value in bucket["decision_impacts"] if value)),
            "quality_statuses": ", ".join(sorted(value for value in bucket["quality_statuses"] if value)),
        }
    return normalized


def augment_metrics(metrics: list[dict[str, str]], evidence: list[dict[str, str]]) -> list[dict[str, Any]]:
    evidence_by_metric = evidence_summary(evidence)
    rows: list[dict[str, Any]] = []
    for row in metrics:
        enriched = {column: row.get(column, "") for column in REQUIRED_METRIC_COLUMNS}
        current = as_float(row.get("current", "0"))
        threshold = as_float(row.get("threshold", "0"))
        baseline = as_float(row.get("baseline", "0"))
        enriched["current_value"] = current
        enriched["threshold_value"] = threshold
        enriched["baseline_value"] = baseline
        enriched["threshold_gap"] = round(current - threshold, 6)
        evidence_item = evidence_by_metric.get(row.get("metric_id", ""), {})
        enriched["evidence_count"] = int(evidence_item.get("evidence_count", 0))
        enriched["decision_impacts"] = evidence_item.get("decision_impacts", "")
        enriched["quality_statuses"] = evidence_item.get("quality_statuses", "")
        rows.append(enriched)
    return rows


def color_for_status(status: str) -> str:
    return {
        "ok": "#2E7D32",
        "watch": "#C77700",
        "breached": "#B3261E",
    }.get(status, "#6B7280")


def rows_for_filter(rows: list[dict[str, Any]], status_filter: str) -> list[dict[str, Any]]:
    if status_filter == "all":
        return rows
    return [row for row in rows if row.get("status") == status_filter]


def customdata_for_rows(rows: list[dict[str, Any]], hover_fields: list[str]) -> list[list[Any]]:
    return [[row.get(field, "") for field in hover_fields] for row in rows]


def build_plotly_figure(rows: list[dict[str, Any]], spec: dict[str, Any]) -> go.Figure:
    hover_fields = list(spec.get("hover_fields", []))
    figure = go.Figure()
    filters = list(spec.get("allowed_filters", []))
    for index, status_filter in enumerate(filters):
        subset = rows_for_filter(rows, status_filter)
        figure.add_bar(
            x=[row["current_value"] for row in subset],
            y=[row["label"] for row in subset],
            orientation="h",
            name=status_filter,
            marker_color=[color_for_status(str(row.get("status", ""))) for row in subset],
            customdata=customdata_for_rows(subset, hover_fields),
            hovertemplate=(
                "metric_id=%{customdata[0]}<br>"
                "label=%{customdata[1]}<br>"
                "status=%{customdata[2]}<br>"
                "current=%{customdata[3]} baseline=%{customdata[4]} threshold=%{customdata[5]}<br>"
                "owner=%{customdata[6]}<br>"
                "evidence_count=%{customdata[7]} impacts=%{customdata[8]}<extra></extra>"
            ),
            visible=index == 0,
        )
    buttons = []
    for index, status_filter in enumerate(filters):
        visible = [False] * len(filters)
        visible[index] = True
        buttons.append(
            {
                "label": "All" if status_filter == "all" else status_filter.title(),
                "method": "update",
                "args": [
                    {"visible": visible},
                    {"title": f"Stakeholder guardrails: {status_filter}"},
                ],
            }
        )
    figure.update_layout(
        title="Stakeholder guardrails: all",
        xaxis_title="Current metric value",
        yaxis_title="Metric",
        hovermode="closest",
        bargap=0.35,
        updatemenus=[
            {
                "type": "dropdown",
                "direction": "down",
                "buttons": buttons,
                "x": 1.02,
                "xanchor": "left",
                "y": 1.0,
                "yanchor": "top",
            }
        ],
        annotations=[
            {
                "text": html.escape(spec.get("audience_task", "")),
                "xref": "paper",
                "yref": "paper",
                "x": 0,
                "y": -0.18,
                "showarrow": False,
                "align": "left",
            }
        ],
    )
    return figure


def render_static_fallback(rows: list[dict[str, Any]], *, title: str) -> str:
    width = 900
    height = 280
    left = 300
    top = 50
    row_height = 36
    gap = 20
    scale = 9000
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" role="img" aria-label="{html.escape(title)}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="24" y="28" font-family="Arial" font-size="18" font-weight="700" fill="#111827">{html.escape(title)}</text>',
    ]
    for index, row in enumerate(rows):
        y = top + index * (row_height + gap)
        current = float(row["current_value"])
        threshold = float(row["threshold_value"])
        bar_width = max(8, min(520, int(current * scale)))
        threshold_x = left + min(520, int(threshold * scale))
        lines.append(f'<g data-metric-id="{html.escape(str(row["metric_id"]))}">')
        lines.append(f'<title>{html.escape(str(row["metric_id"]))}</title>')
        lines.append(f'<text x="24" y="{y + 16}" font-family="Arial" font-size="13" fill="#374151">{html.escape(str(row["label"]))}</text>')
        lines.append(f'<text x="24" y="{y + 32}" font-family="Arial" font-size="10" fill="#6B7280">{html.escape(str(row["metric_id"]))}</text>')
        lines.append(f'<rect x="{left}" y="{y}" width="{bar_width}" height="{row_height}" fill="{color_for_status(str(row["status"]))}" opacity="0.82"/>')
        lines.append(f'<line x1="{threshold_x}" y1="{y - 5}" x2="{threshold_x}" y2="{y + row_height + 5}" stroke="#111827" stroke-width="2"/>')
        lines.append(f'<text x="{left + bar_width + 10}" y="{y + 24}" font-family="Arial" font-size="12" fill="#111827">{current:.3f} / threshold {threshold:.3f}</text>')
        lines.append("</g>")
    lines.append("</svg>")
    return "\n".join(lines) + "\n"


def figure_json_payload(figure: go.Figure, spec: dict[str, Any], redacted_fields: list[str]) -> dict[str, Any]:
    payload = figure.to_plotly_json()
    payload["lesson_metadata"] = {
        "appendix_id": spec.get("appendix_id"),
        "figure_id": spec.get("figure_id"),
        "allowed_filters": spec.get("allowed_filters", []),
        "hover_fields": spec.get("hover_fields", []),
        "redacted_field_count": len(redacted_fields),
        "static_fallback": "static-fallbacks/metric_status.svg",
    }
    return payload


def render_source_links_table(rows: list[dict[str, Any]]) -> str:
    body = []
    for row in rows:
        body.append(
            "<tr>"
            f"<td>{html.escape(str(row['source_id']))}</td>"
            f"<td>{html.escape(str(row['path']))}</td>"
            f"<td>{html.escape(str(row['sha256'])[:12])}</td>"
            f"<td>{html.escape(str(row['row_count']))}</td>"
            "</tr>"
        )
    return (
        '<section id="source-table-links"><h2>Source table links</h2>'
        "<table><thead><tr><th>source_id</th><th>path</th><th>sha256</th><th>rows</th></tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table></section>"
    )


def render_interactive_html(
    *,
    figure: go.Figure,
    source_rows: list[dict[str, Any]],
    fallback_path: Path,
    output_dir: Path,
    include_plotlyjs: str,
) -> str:
    include_js: bool | str = True if include_plotlyjs == "inline" else include_plotlyjs
    plotly_html = pio.to_html(
        figure,
        include_plotlyjs=include_js,
        full_html=True,
        div_id="plotly-interactive-appendix",
    )
    fallback_rel = relpath(fallback_path, start=output_dir)
    addon = (
        render_source_links_table(source_rows)
        + '<section id="static-fallback"><h2>Static fallback</h2>'
        + f'<img src="{html.escape(fallback_rel)}" alt="Static fallback for stakeholder guardrail metrics">'
        + "</section>"
    )
    return plotly_html.replace("</body>", addon + "\n</body>")


def build_source_table_links(
    *,
    output_dir: Path,
    source_info: dict[str, Any],
    metrics: list[dict[str, str]],
    evidence: list[dict[str, str]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for source_id, row_count, grain in [
        ("metric_summary", len(metrics), "metric_id"),
        ("claim_evidence_matrix", len(evidence), "claim_id/evidence_id"),
    ]:
        table = source_info["tables"].get(source_id, {})
        path = table.get("path")
        rows.append(
            {
                "source_id": source_id,
                "path": relpath(path, start=output_dir) if path else "",
                "sha256": sha256_file(path) if path and Path(path).is_file() else "",
                "row_count": row_count,
                "grain": grain,
                "used_in": "plotly_interactive_appendix",
            }
        )
    return rows


def manifest_entry(path: Path, *, start: Path) -> dict[str, Any]:
    return {
        "path": relpath(path, start=start),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
    }


def optional_manifest_entry(path: Path, *, start: Path) -> dict[str, Any]:
    if path.is_file():
        return manifest_entry(path, start=start)
    return {
        "path": relpath(path, start=start),
        "sha256": "",
        "bytes": 0,
        "missing": True,
    }


def compare_previous_manifest(
    *,
    previous_manifest_path: Path | None,
    current_inputs: dict[str, dict[str, Any]],
    current_outputs: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if previous_manifest_path is None or not previous_manifest_path.is_file():
        return {
            "status": "initial_interactive_render",
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
        if key in PRIMARY_OUTPUT_KEYS and previous_outputs.get(key, {}).get("sha256") != value.get("sha256")
    )
    stale_outputs = sorted(PRIMARY_OUTPUT_KEYS - set(changed_outputs)) if changed_inputs else []
    unexpected_output_changes = changed_outputs if not changed_inputs else []
    return {
        "status": "compared_to_previous_interactive_manifest",
        "valid": not stale_outputs and not unexpected_output_changes,
        "changed_inputs": changed_inputs,
        "changed_outputs": changed_outputs,
        "stale_outputs": stale_outputs,
        "unexpected_output_changes": unexpected_output_changes,
    }


def audit_interactive_appendix(
    *,
    delivery_dir: str | Path,
    output_dir: str | Path,
    interactive_spec: dict[str, Any] | None = None,
    output_entries: dict[str, dict[str, Any]] | None = None,
    initial_checks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    delivery_path = Path(delivery_dir)
    output_path = Path(output_dir)
    spec = normalize_interactive_spec(interactive_spec)
    checks = list(initial_checks or [])

    missing_delivery_files = sorted(name for name in REQUIRED_DELIVERY_FILES if not (delivery_path / name).is_file())
    checks.append(
        check(
            "delivery_package_is_complete",
            not missing_delivery_files,
            observed=missing_delivery_files,
            expected=REQUIRED_DELIVERY_FILES,
            message="Interactive appendix must start from the checked multi-format package.",
        )
    )

    qa_path = delivery_path / "format_qa_report.json"
    format_qa = read_json(qa_path) if qa_path.is_file() else {}
    checks.append(
        check(
            "upstream_format_qa_is_valid",
            bool(format_qa.get("valid")),
            observed=format_qa.get("summary", {}).get("blocking_errors", []),
            expected=[],
            message="Interactive delivery cannot promote a blocked HTML/PDF/DOCX package.",
        )
    )

    source_info = resolve_source_tables(delivery_path)
    missing_source_tables = sorted(source_id for source_id in REQUIRED_SOURCE_IDS if source_id not in source_info["tables"])
    checks.append(
        check(
            "source_tables_resolve_from_delivery_manifest",
            not missing_source_tables and source_info["source_links_path"].is_file(),
            observed=missing_source_tables,
            expected=REQUIRED_SOURCE_IDS,
            message="Plotly appendix must cite the same source metric and evidence tables as the report.",
        )
    )

    link_audit_rows = read_csv(delivery_path / "link_audit.csv") if (delivery_path / "link_audit.csv").is_file() else []
    broken_link_ids = sorted(row.get("source_id", "") for row in link_audit_rows if row.get("status") != "ok")
    checks.append(
        check(
            "upstream_link_audit_has_no_broken_sources",
            bool(link_audit_rows) and not broken_link_ids,
            observed=broken_link_ids,
            expected=[],
            message="The interactive appendix should not add UI on top of broken source lineage.",
        )
    )

    filters = list(spec.get("allowed_filters", []))
    hover_fields = list(spec.get("hover_fields", []))
    missing_filters = sorted(set(REQUIRED_FILTERS) - set(filters))
    missing_hover_fields = sorted(
        set(default_interactive_spec()["hover_fields"]) - set(hover_fields)
    )
    checks.append(
        check(
            "interactive_spec_declares_filters_hover_sources_and_fallback",
            not missing_filters
            and not missing_hover_fields
            and spec.get("static_fallback_required") is True
            and set(REQUIRED_SOURCE_IDS).issubset(set(spec.get("source_table_ids", []))),
            observed={"missing_filters": missing_filters, "missing_hover_fields": missing_hover_fields},
            expected="all/watch/breached/ok filters, required hover fields, source ids and fallback policy",
            message="Interactive controls are part of the delivery contract, not decoration.",
        )
    )

    metrics = source_info["tables"].get("metric_summary", {}).get("rows", [])
    evidence = source_info["tables"].get("claim_evidence_matrix", {}).get("rows", [])
    metric_missing_columns = sorted(
        {column for row in metrics for column in REQUIRED_METRIC_COLUMNS if column not in row}
    )
    evidence_missing_columns = sorted(
        {column for row in evidence for column in REQUIRED_EVIDENCE_COLUMNS if column not in row}
    )
    checks.append(
        check(
            "source_tables_have_required_columns",
            bool(metrics)
            and bool(evidence)
            and not metric_missing_columns
            and not evidence_missing_columns,
            observed={"metric": metric_missing_columns, "evidence": evidence_missing_columns},
            expected={"metric": REQUIRED_METRIC_COLUMNS, "evidence": REQUIRED_EVIDENCE_COLUMNS},
            message="Hover and source links need stable source table columns.",
        )
    )

    figure_path = output_path / "plotly_figure_spec.json"
    figure_spec = read_json(figure_path) if figure_path.is_file() else {}
    buttons = figure_spec.get("layout", {}).get("updatemenus", [{}])[0].get("buttons", [])
    traces = figure_spec.get("data", [])
    checks.append(
        check(
            "figure_json_has_dropdown_filters_and_customdata",
            len(traces) == len(filters)
            and len(buttons) == len(filters)
            and all("customdata" in trace for trace in traces),
            observed={"trace_count": len(traces), "button_count": len(buttons)},
            expected={"traces": len(filters), "buttons": len(filters)},
            message="Plotly JSON must preserve filter controls and per-point context.",
        )
    )

    hover_templates = [trace.get("hovertemplate", "") for trace in traces]
    checks.append(
        check(
            "hover_context_contains_metric_status_owner_and_evidence",
            all("metric_id=" in template and "status=" in template and "owner=" in template and "evidence_count=" in template for template in hover_templates),
            observed=hover_templates[:1],
            expected="metric_id/status/owner/evidence_count in hovertemplate",
            message="Hover must explain the decision context without exposing raw sensitive rows.",
        )
    )

    source_table_links_path = output_path / "source_table_links.csv"
    source_table_link_rows = read_csv(source_table_links_path) if source_table_links_path.is_file() else []
    checks.append(
        check(
            "source_table_links_cover_metric_and_evidence_tables",
            {row.get("source_id") for row in source_table_link_rows} == set(REQUIRED_SOURCE_IDS)
            and all(len(row.get("sha256", "")) == 64 for row in source_table_link_rows),
            observed=source_table_link_rows,
            expected=REQUIRED_SOURCE_IDS,
            message="Interactive appendix needs machine-readable links back to source tables.",
        )
    )

    html_path = output_path / "interactive_appendix.html"
    html_text = html_path.read_text(encoding="utf-8") if html_path.is_file() else ""
    script_sources = re.findall(r"<script[^>]+src=[\"']([^\"']+)[\"']", html_text, flags=re.IGNORECASE)
    cdn_script_sources = [source for source in script_sources if "cdn.plot.ly" in source.lower()]
    checks.append(
        check(
            "interactive_html_is_standalone_plotly_export",
            html_path.is_file()
            and "Plotly.newPlot" in html_text
            and "plotly-interactive-appendix" in html_text
            and "dash-renderer" not in html_text.lower()
            and not cdn_script_sources,
            observed={
                "exists": html_path.is_file(),
                "bytes": html_path.stat().st_size if html_path.is_file() else 0,
                "external_plotly_scripts": cdn_script_sources,
            },
            expected="standalone Plotly HTML export without Dash or CDN dependency",
            message="The lesson ships a standalone Plotly appendix, not a Dash app.",
        )
    )

    fallback_path = output_path / "static-fallbacks" / "metric_status.svg"
    fallback_text = fallback_path.read_text(encoding="utf-8") if fallback_path.is_file() else ""
    checks.append(
        check(
            "static_fallback_exists_and_is_linked",
            (
                fallback_path.is_file()
                and "static-fallbacks/metric_status.svg" in html_text
                and "support_ticket_rate_7d" in fallback_text
            ),
            observed={"exists": fallback_path.is_file()},
            expected="static SVG fallback linked from HTML",
            message="Stakeholders without JavaScript need a static fallback or source table.",
        )
    )

    metric_sensitive = sensitive_columns(metrics)
    evidence_sensitive = sensitive_columns(evidence)
    source_sensitive_values = sensitive_values(metrics) + sensitive_values(evidence)
    policy_fields = spec.get("redaction_policy", {}).get("forbidden_fields", [])
    policy_covers_sensitive = all(
        any(forbidden.lower() in column.lower() for forbidden in policy_fields)
        for column in metric_sensitive + evidence_sensitive
    )
    policy_redacts_values = spec.get("redaction_policy", {}).get("redact_values") is True
    public_text = (
        json.dumps(figure_spec, ensure_ascii=False)
        + html_text
        + fallback_text
        + json.dumps(source_table_link_rows, ensure_ascii=False)
    )
    leaked_columns = [column for column in metric_sensitive + evidence_sensitive if column in public_text]
    leaked_values = [value for value in source_sensitive_values if value in public_text]
    source_has_sensitive_data = bool(metric_sensitive or evidence_sensitive or source_sensitive_values)
    checks.append(
        check(
            "sensitive_fields_are_redacted_from_public_outputs",
            (not source_has_sensitive_data)
            or (policy_covers_sensitive and policy_redacts_values and not leaked_columns and not leaked_values),
            observed={
                "redacted_fields": sorted(metric_sensitive + evidence_sensitive),
                "leaked_columns": sorted(leaked_columns),
                "leaked_value_count": len(leaked_values),
            },
            expected="sensitive source fields may exist only if policy covers them and public outputs omit them",
            message="Hover context should enrich decisions without leaking sensitive source fields.",
        )
    )

    if output_entries is not None:
        missing_hashes = sorted(key for key, value in output_entries.items() if len(value.get("sha256", "")) != 64)
    else:
        missing_hashes = ["not_provided"]
    checks.append(
        check(
            "manifest_hashes_interactive_outputs",
            not missing_hashes,
            observed=missing_hashes,
            expected=[],
            message="Interactive HTML, JSON spec, fallback and links need checksums.",
        )
    )

    blockers = [item["id"] for item in checks if not item["valid"] and item["severity"] == "block"]
    warnings = [item["id"] for item in checks if not item["valid"] and item["severity"] == "warn"]
    return {
        "version": APPENDIX_VERSION,
        "valid": not blockers,
        "appendix_id": spec.get("appendix_id"),
        "readiness_status": "blocked" if blockers else ("ready_with_warnings" if warnings else "ready"),
        "redaction_summary": {
            "redacted_fields": sorted(set(sensitive_columns(metrics) + sensitive_columns(evidence))),
        },
        "summary": {
            "blocking_errors": blockers,
            "warnings": warnings,
            "check_count": len(checks),
        },
        "checks": checks,
    }


def build_interactive_appendix(
    *,
    delivery_dir: str | Path,
    output_dir: str | Path,
    interactive_spec_path: str | Path | None = None,
    previous_manifest_path: str | Path | None = None,
) -> InteractiveAppendixBuildResult:
    delivery_path = Path(delivery_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    (output_path / "static-fallbacks").mkdir(parents=True, exist_ok=True)

    interactive_spec = read_json(interactive_spec_path) if interactive_spec_path else default_interactive_spec()
    interactive_spec = normalize_interactive_spec(interactive_spec)
    source_info = resolve_source_tables(delivery_path)
    metrics = source_info["tables"].get("metric_summary", {}).get("rows", [])
    evidence = source_info["tables"].get("claim_evidence_matrix", {}).get("rows", [])
    rows = augment_metrics(metrics, evidence)
    redacted_fields = sorted(set(sensitive_columns(metrics) + sensitive_columns(evidence)))

    figure = build_plotly_figure(rows, interactive_spec)
    html_path = output_path / "interactive_appendix.html"
    figure_spec_path = output_path / "plotly_figure_spec.json"
    fallback_path = output_path / "static-fallbacks" / "metric_status.svg"
    source_links_path = output_path / "source_table_links.csv"
    audit_path = output_path / "interaction_audit.json"
    manifest_path = output_path / "interaction_manifest.json"
    interactive_spec_output_path = output_path / "interactive_spec.json"

    write_json(interactive_spec_output_path, interactive_spec)
    fallback_path.write_text(
        render_static_fallback(rows, title="Static fallback: stakeholder guardrails"),
        encoding="utf-8",
    )
    source_table_links = build_source_table_links(
        output_dir=output_path,
        source_info=source_info,
        metrics=metrics,
        evidence=evidence,
    )
    write_csv(
        source_links_path,
        source_table_links,
        ["source_id", "path", "sha256", "row_count", "grain", "used_in"],
    )
    figure_payload = figure_json_payload(figure, interactive_spec, redacted_fields)
    write_json(figure_spec_path, figure_payload)
    html_path.write_text(
        render_interactive_html(
            figure=figure,
            source_rows=source_table_links,
            fallback_path=fallback_path,
            output_dir=output_path,
            include_plotlyjs=interactive_spec.get("include_plotlyjs", "inline"),
        ),
        encoding="utf-8",
    )

    table_entries = {
        source_id: manifest_entry(table["path"], start=output_path)
        for source_id, table in source_info.get("tables", {}).items()
        if table.get("path") and Path(table["path"]).is_file()
    }
    input_entries = {
        "format_manifest": optional_manifest_entry(delivery_path / "format_manifest.json", start=output_path),
        "format_qa_report": optional_manifest_entry(delivery_path / "format_qa_report.json", start=output_path),
        "format_link_audit": optional_manifest_entry(delivery_path / "link_audit.csv", start=output_path),
        "interactive_spec": manifest_entry(interactive_spec_output_path, start=output_path),
        **{f"source_{source_id}": value for source_id, value in table_entries.items()},
    }
    output_entries = {
        "interactive_html": manifest_entry(html_path, start=output_path),
        "plotly_figure_spec": manifest_entry(figure_spec_path, start=output_path),
        "static_fallback_svg": manifest_entry(fallback_path, start=output_path),
        "source_table_links": manifest_entry(source_links_path, start=output_path),
    }
    previous = Path(previous_manifest_path) if previous_manifest_path is not None else None
    rebuild_check = compare_previous_manifest(
        previous_manifest_path=previous,
        current_inputs=input_entries,
        current_outputs=output_entries,
    )
    rebuild_result = check(
        "interactive_rebuild_check_is_consistent",
        rebuild_check["valid"],
        observed=rebuild_check,
        expected="changed inputs change interactive outputs; unchanged inputs do not drift",
        message="Interactive appendix should not silently go stale or change without input changes.",
    )

    audit = audit_interactive_appendix(
        delivery_dir=delivery_path,
        output_dir=output_path,
        interactive_spec=interactive_spec,
        output_entries=output_entries,
        initial_checks=[rebuild_result],
    )
    write_json(audit_path, audit)
    output_entries["interaction_audit"] = manifest_entry(audit_path, start=output_path)

    manifest = {
        "version": APPENDIX_VERSION,
        "appendix_id": interactive_spec.get("appendix_id"),
        "hash_algorithm": "sha256",
        "renderer_used": "plotly_interactive_appendix_builder",
        "plotly_version": plotly.__version__,
        "delivery_dir": relpath(delivery_path, start=output_path),
        "inputs": input_entries,
        "outputs": output_entries,
        "rebuild_check": rebuild_check,
    }
    write_json(manifest_path, manifest)

    return InteractiveAppendixBuildResult(
        output_dir=output_path,
        html_path=html_path,
        figure_spec_path=figure_spec_path,
        fallback_path=fallback_path,
        source_links_path=source_links_path,
        audit_path=audit_path,
        manifest_path=manifest_path,
        interactive_spec_path=interactive_spec_output_path,
        audit=audit,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a Plotly interactive appendix for a checked delivery report.")
    parser.add_argument("--delivery-dir", type=Path, help="Path to the multi-format delivery package from lesson 17/04.")
    parser.add_argument("--interactive-spec", type=Path, help="Optional interactive_spec.json.")
    parser.add_argument("--previous-manifest", type=Path, help="Optional previous interaction_manifest.json.")
    parser.add_argument("--output-dir", type=Path, required=True, help="Directory for the interactive appendix bundle.")
    parser.add_argument("--write-example", type=Path, help="Write an example 17/04 delivery package before building.")
    parser.add_argument("--fail-on-invalid", action="store_true", help="Return exit code 2 when interaction audit blocks delivery.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    delivery_dir = args.delivery_dir
    interactive_spec = args.interactive_spec
    if args.write_example:
        sample = write_sample_delivery_package(args.write_example)
        delivery_dir = sample["delivery_dir"]
        if interactive_spec is None:
            interactive_spec = sample["interactive_spec_path"]
    if delivery_dir is None:
        raise SystemExit("missing required argument: --delivery-dir or --write-example")

    result = build_interactive_appendix(
        delivery_dir=delivery_dir,
        interactive_spec_path=interactive_spec,
        output_dir=args.output_dir,
        previous_manifest_path=args.previous_manifest,
    )
    response = {
        "valid": result.audit["valid"],
        "readiness_status": result.audit["readiness_status"],
        "blocking_errors": result.audit["summary"]["blocking_errors"],
        "html": str(result.html_path),
        "figure_spec": str(result.figure_spec_path),
        "static_fallback": str(result.fallback_path),
        "manifest": str(result.manifest_path),
    }
    print(json.dumps(response, ensure_ascii=False, indent=2, sort_keys=True))
    if args.fail_on_invalid and not result.audit["valid"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
