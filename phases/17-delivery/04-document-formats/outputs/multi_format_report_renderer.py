from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import html
import importlib.util
import json
import os
import re
import shutil
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


RENDERER_VERSION = "1.0.0"
REQUIRED_TARGETS = ["html", "pdf", "docx"]
SUPPORTED_TARGETS = set(REQUIRED_TARGETS)
REQUIRED_REPORT_FILES = [
    "report.qmd",
    "report.html",
    "report_audit.json",
    "render_manifest.json",
    "source_links.csv",
]
INTERACTIVE_MARKERS = ("<script", "plotly", "observable", "```{ojs}", "htmlwidgets")


@dataclass(frozen=True)
class MultiFormatBuildResult:
    output_dir: Path
    html_path: Path
    pdf_path: Path
    docx_path: Path
    targets_path: Path
    asset_inventory_path: Path
    link_audit_path: Path
    qa_report_path: Path
    manifest_path: Path
    qa_report: dict[str, Any]


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


def default_format_spec() -> dict[str, Any]:
    return {
        "delivery_id": "trial-onboarding-multi-format-report",
        "source_report_id": "trial-onboarding-quarto-report",
        "required_targets": ["html", "pdf", "docx"],
        "targets": {
            "html": {
                "output": "report.html",
                "required": True,
                "self_contained": True,
                "render_command": "quarto render report.qmd --to html --execute-params params.yml",
            },
            "pdf": {
                "output": "report.pdf",
                "required": True,
                "self_contained": True,
                "render_command": "quarto render report.qmd --to pdf --execute-params params.yml",
                "requires_external_engine": "TinyTeX or another supported PDF engine",
            },
            "docx": {
                "output": "report.docx",
                "required": True,
                "self_contained": True,
                "render_command": "quarto render report.qmd --to docx --execute-params params.yml",
            },
        },
        "format_limits": {
            "max_table_columns_for_pdf": 8,
            "max_unbroken_token_chars": 52,
            "block_interactive_content_for_static_targets": True,
        },
        "handoff": {
            "audience": "Growth weekly decision review",
            "delivery_mode": "file_bundle",
            "owner": "Head of Growth",
        },
    }


def load_upstream_packager():
    current = Path(__file__).resolve()
    packager_path = current.parents[2] / "03-quarto" / "outputs" / "quarto_report_packager.py"
    spec = importlib.util.spec_from_file_location("quarto_report_packager_for_formats", packager_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load upstream packager: {packager_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_sample_report_package(root: str | Path) -> dict[str, Path]:
    root_path = Path(root)
    root_path.mkdir(parents=True, exist_ok=True)
    packager = load_upstream_packager()
    input_dir = root_path / "quarto-inputs"
    report_dir = root_path / "quarto-report-package"
    paths = packager.write_sample_inputs(input_dir)
    packager.build_quarto_report(
        spec_path=paths["spec_path"],
        metrics_path=paths["metrics_path"],
        evidence_path=paths["evidence_path"],
        workbook_audit_path=paths["workbook_audit_path"],
        memo_audit_path=paths["memo_audit_path"],
        output_dir=report_dir,
    )
    format_spec_path = root_path / "format_targets.json"
    write_json(format_spec_path, default_format_spec())
    return {"report_dir": report_dir, "format_spec_path": format_spec_path}


def normalize_format_spec(format_spec: dict[str, Any] | None) -> dict[str, Any]:
    if format_spec is None:
        return default_format_spec()
    normalized = dict(format_spec)
    targets = normalized.get("targets", {})
    if isinstance(targets, list):
        normalized["targets"] = {item["format"]: {key: value for key, value in item.items() if key != "format"} for item in targets}
    return normalized


def expected_render_commands() -> dict[str, str]:
    return {
        target: f"quarto render report.qmd --to {target} --execute-params params.yml"
        for target in REQUIRED_TARGETS
    }


def target_render_command(spec: dict[str, Any], target: str) -> str:
    return spec.get("targets", {}).get(target, {}).get("render_command", expected_render_commands()[target])


def extract_title(html_text: str) -> str:
    match = re.search(r"<title>(.*?)</title>", html_text, flags=re.IGNORECASE | re.DOTALL)
    if match:
        return html.unescape(re.sub(r"\s+", " ", match.group(1)).strip())
    heading = re.search(r"<h1[^>]*>(.*?)</h1>", html_text, flags=re.IGNORECASE | re.DOTALL)
    if heading:
        return html.unescape(re.sub(r"<.*?>", "", heading.group(1)).strip())
    return "Stakeholder delivery report"


def extract_decision_status(html_text: str) -> str:
    match = re.search(
        r"Decision status:\s*<span[^>]*>(.*?)</span>",
        html_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if match:
        return html.unescape(re.sub(r"<.*?>", "", match.group(1)).strip())
    text = re.sub(r"<.*?>", " ", html_text)
    match = re.search(r"Decision status:\s*([A-Za-z0-9_-]+)", text)
    return match.group(1) if match else "unknown"


def report_summary(report_dir: Path) -> dict[str, Any]:
    html_path = report_dir / "report.html"
    html_text = html_path.read_text(encoding="utf-8") if html_path.is_file() else ""
    audit_path = report_dir / "report_audit.json"
    audit = read_json(audit_path) if audit_path.is_file() else {}
    figure_path = report_dir / "figures" / "guardrail_status.svg"
    return {
        "title": extract_title(html_text),
        "decision_status": extract_decision_status(html_text),
        "report_id": audit.get("report_id", "unknown-report"),
        "figure_path": figure_path,
        "figure_sha256": sha256_file(figure_path) if figure_path.is_file() else "",
    }


def render_delivery_html(*, report_dir: Path, spec: dict[str, Any], summary: dict[str, Any]) -> str:
    source_html_path = report_dir / "report.html"
    source_html = source_html_path.read_text(encoding="utf-8") if source_html_path.is_file() else ""
    figure_path = summary["figure_path"]
    if figure_path.is_file():
        encoded = base64.b64encode(figure_path.read_bytes()).decode("ascii")
        source_html = source_html.replace(
            'src="figures/guardrail_status.svg"',
            f'src="data:image/svg+xml;base64,{encoded}"',
        )
    banner = (
        '<div id="format-contract" data-format-target="html">'
        f'Multi-format delivery target: HTML. Source report: {html.escape(summary["report_id"])}. '
        f'Delivery owner: {html.escape(spec.get("handoff", {}).get("owner", ""))}. '
        f'Figure reference: guardrail_status.svg sha256 {html.escape(summary["figure_sha256"][:16])}.'
        "</div>"
    )
    if "<body>" in source_html:
        source_html = source_html.replace("<body>", f"<body>\n  {banner}", 1)
    else:
        source_html = f"<!doctype html><html><body>{banner}<h1>{html.escape(summary['title'])}</h1></body></html>"
    return source_html


def pdf_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def render_pdf_bytes(*, spec: dict[str, Any], summary: dict[str, Any]) -> bytes:
    command = target_render_command(spec, "pdf")
    lines = [
        "Delivery report PDF target",
        f"Title: {summary['title']}",
        f"Source report: {summary['report_id']}",
        f"Decision status: {summary['decision_status']}",
        f"Figure: guardrail_status.svg sha256 {summary['figure_sha256'][:16]}",
        f"Real render command: {command}",
        "Renderer: lesson deterministic multi-format preview",
    ]
    content_lines = ["BT", "/F1 17 Tf", "72 760 Td", f"({pdf_escape(lines[0])}) Tj", "/F1 10 Tf"]
    for line in lines[1:]:
        content_lines.append("0 -20 Td")
        content_lines.append(f"({pdf_escape(line[:100])}) Tj")
    content_lines.append("ET")
    stream = "\n".join(content_lines).encode("latin-1", errors="replace")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    body = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets: list[int] = []
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(body))
        body.extend(f"{index} 0 obj\n".encode("ascii"))
        body.extend(obj)
        body.extend(b"\nendobj\n")
    xref_offset = len(body)
    body.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("ascii"))
    for offset in offsets:
        body.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    body.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode(
            "ascii"
        )
    )
    return bytes(body)


def docx_paragraph(text: str) -> str:
    return f"<w:p><w:r><w:t>{html.escape(text)}</w:t></w:r></w:p>"


def render_docx(*, output_path: Path, spec: dict[str, Any], summary: dict[str, Any]) -> None:
    command = target_render_command(spec, "docx")
    paragraphs = [
        "Delivery report DOCX target",
        f"Title: {summary['title']}",
        f"Source report: {summary['report_id']}",
        f"Decision status: {summary['decision_status']}",
        f"Figure reference: guardrail_status.svg sha256 {summary['figure_sha256']}",
        f"Real render command: {command}",
        "Renderer boundary: deterministic lesson preview, not a replacement for Quarto CLI.",
    ]
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>"
        + "".join(docx_paragraph(item) for item in paragraphs)
        + '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr>'
        + "</w:body></w:document>"
    )
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>
"""
    root_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>
"""
    document_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>
"""
    core_props = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>Delivery report DOCX target</dc:title>
  <dc:creator>analyst-tools-course</dc:creator>
  <dcterms:created xsi:type="dcterms:W3CDTF">2026-05-22T00:00:00Z</dcterms:created>
  <dcterms:modified xsi:type="dcterms:W3CDTF">2026-05-22T00:00:00Z</dcterms:modified>
</cp:coreProperties>
"""
    app_props = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">
  <Application>analyst-tools-course deterministic renderer</Application>
</Properties>
"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as docx:
        docx.writestr("[Content_Types].xml", content_types)
        docx.writestr("_rels/.rels", root_rels)
        docx.writestr("word/_rels/document.xml.rels", document_rels)
        docx.writestr("word/document.xml", document_xml)
        docx.writestr("docProps/core.xml", core_props)
        docx.writestr("docProps/app.xml", app_props)


def build_link_audit_rows(report_dir: Path, source_links: list[dict[str, str]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in source_links:
        raw_path = row.get("path", "")
        path = Path(raw_path)
        if path.is_absolute():
            exists = False
            actual_hash = ""
            status = "absolute_path"
        else:
            resolved = (report_dir / path).resolve()
            exists = resolved.is_file()
            actual_hash = sha256_file(resolved) if exists else ""
            if not exists:
                status = "missing"
            elif actual_hash != row.get("sha256", ""):
                status = "hash_mismatch"
            else:
                status = "ok"
        rows.append(
            {
                "source_id": row.get("source_id", ""),
                "path": raw_path,
                "expected_sha256": row.get("sha256", ""),
                "actual_sha256": actual_hash,
                "exists": str(exists).lower(),
                "status": status,
            }
        )
    return rows


def manifest_entry(path: Path, *, start: Path) -> dict[str, Any]:
    return {
        "path": relpath(path, start=start),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
    }


def build_asset_inventory(output_dir: Path) -> list[dict[str, Any]]:
    assets = [
        ("html_report", "html", output_dir / "report.html", "embedded delivery HTML"),
        ("pdf_report", "pdf", output_dir / "report.pdf", "deterministic PDF delivery preview"),
        ("docx_report", "docx", output_dir / "report.docx", "deterministic DOCX delivery preview"),
    ]
    rows: list[dict[str, Any]] = []
    for asset_id, fmt, path, role in assets:
        rows.append(
            {
                "asset_id": asset_id,
                "format": fmt,
                "path": path.name,
                "sha256": sha256_file(path) if path.is_file() else "",
                "bytes": path.stat().st_size if path.is_file() else 0,
                "role": role,
            }
        )
    return rows


def compare_previous_manifest(
    *,
    previous_manifest_path: Path | None,
    current_inputs: dict[str, dict[str, Any]],
    current_outputs: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if previous_manifest_path is None or not previous_manifest_path.is_file():
        return {
            "status": "initial_format_render",
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
    primary_output_keys = {"html_report", "pdf_report", "docx_report"}
    changed_outputs = sorted(
        key
        for key, value in current_outputs.items()
        if key in primary_output_keys and previous_outputs.get(key, {}).get("sha256") != value.get("sha256")
    )
    stale_outputs = sorted(primary_output_keys - set(changed_outputs)) if changed_inputs else []
    unexpected_output_changes = changed_outputs if not changed_inputs else []
    return {
        "status": "compared_to_previous_format_manifest",
        "valid": not stale_outputs and not unexpected_output_changes,
        "changed_inputs": changed_inputs,
        "changed_outputs": changed_outputs,
        "stale_outputs": stale_outputs,
        "unexpected_output_changes": unexpected_output_changes,
    }


def layout_warnings(*, html_text: str, format_spec: dict[str, Any]) -> list[str]:
    limits = format_spec.get("format_limits", {})
    max_columns = int(limits.get("max_table_columns_for_pdf", 8))
    max_token = int(limits.get("max_unbroken_token_chars", 52))
    warnings: list[str] = []
    tables = re.findall(r"<table\b.*?</table>", html_text, flags=re.IGNORECASE | re.DOTALL)
    max_observed_columns = 0
    for table in tables:
        max_observed_columns = max(max_observed_columns, len(re.findall(r"<th\b", table, flags=re.IGNORECASE)))
    if max_observed_columns > max_columns:
        warnings.append(f"wide_table_for_pdf_docx:{max_observed_columns}_columns")
    text_without_data_uris = re.sub(r"data:[^\"')\s]+", "data-uri", html_text)
    long_tokens = sorted(set(re.findall(rf"\b[A-Za-z0-9_./:-]{{{max_token + 1},}}\b", text_without_data_uris)))
    if long_tokens:
        warnings.append(f"long_unbroken_tokens:{len(long_tokens)}")
    return warnings


def docx_relationships_are_internal(path: Path) -> bool:
    try:
        with zipfile.ZipFile(path) as docx:
            rel_files = [name for name in docx.namelist() if name.endswith(".rels")]
            for rel_file in rel_files:
                text = docx.read(rel_file).decode("utf-8", errors="replace")
                if 'TargetMode="External"' in text:
                    return False
            return {"[Content_Types].xml", "_rels/.rels", "word/document.xml"}.issubset(set(docx.namelist()))
    except zipfile.BadZipFile:
        return False


def docx_contains(path: Path, needle: str) -> bool:
    try:
        with zipfile.ZipFile(path) as docx:
            return needle in docx.read("word/document.xml").decode("utf-8", errors="replace")
    except (KeyError, zipfile.BadZipFile):
        return False


def audit_format_package(
    *,
    report_dir: str | Path,
    output_dir: str | Path,
    format_spec: dict[str, Any] | None = None,
    output_entries: dict[str, dict[str, Any]] | None = None,
    initial_checks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    report_path = Path(report_dir)
    output_path = Path(output_dir)
    spec = normalize_format_spec(format_spec)
    checks: list[dict[str, Any]] = list(initial_checks or [])

    missing_report_files = sorted(name for name in REQUIRED_REPORT_FILES if not (report_path / name).is_file())
    checks.append(
        check(
            "source_report_package_is_complete",
            not missing_report_files,
            observed=missing_report_files,
            expected=REQUIRED_REPORT_FILES,
            message="Multi-format delivery must start from the reproducible report package built in 17/03.",
        )
    )

    report_audit = read_json(report_path / "report_audit.json") if (report_path / "report_audit.json").is_file() else {}
    checks.append(
        check(
            "upstream_report_audit_is_valid",
            bool(report_audit.get("valid")),
            observed=report_audit.get("summary", {}).get("blocking_errors", []),
            expected=[],
            message="Blocked Quarto report packages cannot be promoted into delivery formats.",
        )
    )

    render_manifest = read_json(report_path / "render_manifest.json") if (report_path / "render_manifest.json").is_file() else {}
    checks.append(
        check(
            "upstream_render_manifest_is_traceable",
            render_manifest.get("hash_algorithm") == "sha256"
            and "report_qmd" in render_manifest.get("outputs", {})
            and "report_html" in render_manifest.get("outputs", {}),
            observed=render_manifest.get("outputs", {}),
            expected=["report_qmd", "report_html"],
            message="Format rendering needs upstream input/output hashes, not only finished files.",
        )
    )

    target_map = spec.get("targets", {})
    requested_targets = set(target_map)
    required_targets = set(spec.get("required_targets", []))
    unsupported = sorted((requested_targets | required_targets) - SUPPORTED_TARGETS)
    missing_required = sorted(set(REQUIRED_TARGETS) - required_targets)
    checks.append(
        check(
            "format_targets_cover_html_pdf_docx",
            not unsupported and not missing_required and set(REQUIRED_TARGETS).issubset(requested_targets),
            observed={"unsupported": unsupported, "missing_required": missing_required, "requested": sorted(requested_targets)},
            expected=REQUIRED_TARGETS,
            message="The lesson contract requires explicit HTML, PDF and DOCX targets.",
        )
    )

    expected_commands = expected_render_commands()
    bad_commands = sorted(
        target
        for target in REQUIRED_TARGETS
        if target_map.get(target, {}).get("render_command") != expected_commands[target]
    )
    checks.append(
        check(
            "format_render_commands_are_explicit",
            not bad_commands,
            observed={target: target_map.get(target, {}).get("render_command") for target in bad_commands},
            expected=expected_commands,
            message="Manifest must preserve real Quarto commands for each delivery target.",
        )
    )

    link_rows = read_csv(report_path / "source_links.csv") if (report_path / "source_links.csv").is_file() else []
    link_audit = build_link_audit_rows(report_path, link_rows)
    broken_links = sorted(row["source_id"] for row in link_audit if row["status"] != "ok")
    checks.append(
        check(
            "source_links_resolve_with_expected_hashes",
            bool(link_rows) and not broken_links,
            observed=broken_links,
            expected=[],
            message="Changing formats must not detach the report from its source evidence.",
        )
    )

    qmd_text = (report_path / "report.qmd").read_text(encoding="utf-8") if (report_path / "report.qmd").is_file() else ""
    interactive_markers = sorted(marker for marker in INTERACTIVE_MARKERS if marker in qmd_text.lower())
    checks.append(
        check(
            "static_targets_have_no_interactive_only_content",
            not interactive_markers
            or not spec.get("format_limits", {}).get("block_interactive_content_for_static_targets", True),
            observed=interactive_markers,
            expected=[],
            message="PDF and DOCX targets need a static fallback before interactive content is introduced.",
        )
    )

    html_path = output_path / "report.html"
    pdf_path = output_path / "report.pdf"
    docx_path = output_path / "report.docx"
    html_text = html_path.read_text(encoding="utf-8") if html_path.is_file() else ""
    bad_html_srcs = [
        value
        for value in re.findall(r'\bsrc="([^"]+)"', html_text)
        if not value.startswith("data:") and not value.startswith("#")
    ]
    checks.append(
        check(
            "html_output_embeds_local_figure_resources",
            html_path.is_file() and "data:image/svg+xml;base64," in html_text and not bad_html_srcs,
            observed=bad_html_srcs,
            expected="data URI for local figure resources",
            message="Self-contained HTML should not require adjacent figure files or network access.",
        )
    )

    pdf_bytes = pdf_path.read_bytes() if pdf_path.is_file() else b""
    checks.append(
        check(
            "pdf_output_is_valid_delivery_file",
            pdf_bytes.startswith(b"%PDF-1.4") and pdf_bytes.rstrip().endswith(b"%%EOF") and len(pdf_bytes) > 600,
            observed={"exists": pdf_path.is_file(), "bytes": len(pdf_bytes)},
            expected="PDF header, EOF marker and non-empty content",
            message="PDF target must be a real file artifact, not a missing or stale placeholder.",
        )
    )

    checks.append(
        check(
            "docx_output_is_valid_ooxml_package",
            docx_path.is_file() and docx_relationships_are_internal(docx_path),
            observed={"exists": docx_path.is_file()},
            expected="[Content_Types].xml, _rels/.rels and word/document.xml without external relationships",
            message="DOCX target is a zipped OOXML package and should not depend on external resources.",
        )
    )

    figure_hash = report_summary(report_path)["figure_sha256"]
    figure_refs_ok = (
        "guardrail_status.svg" in html_text
        and b"guardrail_status.svg" in pdf_bytes
        and docx_contains(docx_path, "guardrail_status.svg")
        and figure_hash[:16] in html_text + pdf_bytes.decode("latin-1", errors="ignore")
        and docx_contains(docx_path, figure_hash)
    )
    checks.append(
        check(
            "figures_are_preserved_across_targets",
            figure_refs_ok,
            observed={"figure_sha256": figure_hash},
            expected="HTML, PDF and DOCX mention the required figure and checksum",
            message="The same required figure must remain visible or traceable in every delivery target.",
        )
    )

    if output_entries is not None:
        missing_hashes = sorted(key for key, value in output_entries.items() if len(value.get("sha256", "")) != 64)
    else:
        missing_hashes = ["not_provided"]
    checks.append(
        check(
            "format_manifest_hashes_primary_outputs",
            not missing_hashes,
            observed=missing_hashes,
            expected=[],
            message="The format manifest must hash every generated delivery asset.",
        )
    )

    warnings = layout_warnings(html_text=html_text, format_spec=spec)
    checks.append(
        check(
            "layout_sensitive_warnings_are_recorded",
            not warnings,
            severity="warn",
            observed=warnings,
            expected=[],
            message="PDF/DOCX layout risks should be visible without blocking otherwise valid delivery.",
        )
    )

    blockers = [item["id"] for item in checks if not item["valid"] and item["severity"] == "block"]
    warning_ids = [item["id"] for item in checks if not item["valid"] and item["severity"] == "warn"]
    return {
        "version": RENDERER_VERSION,
        "valid": not blockers,
        "delivery_id": spec.get("delivery_id"),
        "readiness_status": "blocked" if blockers else ("ready_with_warnings" if warning_ids else "ready"),
        "summary": {
            "blocking_errors": blockers,
            "warnings": warning_ids,
            "check_count": len(checks),
        },
        "checks": checks,
        "link_audit": link_audit,
    }


def build_multi_format_report(
    *,
    report_dir: str | Path,
    output_dir: str | Path,
    format_spec_path: str | Path | None = None,
    previous_manifest_path: str | Path | None = None,
) -> MultiFormatBuildResult:
    report_path = Path(report_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    format_spec = read_json(format_spec_path) if format_spec_path is not None else default_format_spec()
    format_spec = normalize_format_spec(format_spec)
    summary = report_summary(report_path)

    html_path = output_path / "report.html"
    pdf_path = output_path / "report.pdf"
    docx_path = output_path / "report.docx"
    targets_path = output_path / "format_targets.json"
    asset_inventory_path = output_path / "asset_inventory.csv"
    link_audit_path = output_path / "link_audit.csv"
    qa_report_path = output_path / "format_qa_report.json"
    manifest_path = output_path / "format_manifest.json"

    write_json(targets_path, format_spec)
    html_path.write_text(render_delivery_html(report_dir=report_path, spec=format_spec, summary=summary), encoding="utf-8")
    pdf_path.write_bytes(render_pdf_bytes(spec=format_spec, summary=summary))
    render_docx(output_path=docx_path, spec=format_spec, summary=summary)

    asset_rows = build_asset_inventory(output_path)
    write_csv(
        asset_inventory_path,
        asset_rows,
        ["asset_id", "format", "path", "sha256", "bytes", "role"],
    )
    source_links = read_csv(report_path / "source_links.csv") if (report_path / "source_links.csv").is_file() else []
    link_rows = build_link_audit_rows(report_path, source_links)
    write_csv(
        link_audit_path,
        link_rows,
        ["source_id", "path", "expected_sha256", "actual_sha256", "exists", "status"],
    )

    input_entries = {
        "source_report_qmd": manifest_entry(report_path / "report.qmd", start=output_path)
        if (report_path / "report.qmd").is_file()
        else {"path": relpath(report_path / "report.qmd", start=output_path), "sha256": "", "bytes": 0},
        "source_report_html": manifest_entry(report_path / "report.html", start=output_path)
        if (report_path / "report.html").is_file()
        else {"path": relpath(report_path / "report.html", start=output_path), "sha256": "", "bytes": 0},
        "source_report_audit": manifest_entry(report_path / "report_audit.json", start=output_path)
        if (report_path / "report_audit.json").is_file()
        else {"path": relpath(report_path / "report_audit.json", start=output_path), "sha256": "", "bytes": 0},
        "source_render_manifest": manifest_entry(report_path / "render_manifest.json", start=output_path)
        if (report_path / "render_manifest.json").is_file()
        else {"path": relpath(report_path / "render_manifest.json", start=output_path), "sha256": "", "bytes": 0},
        "source_links": manifest_entry(report_path / "source_links.csv", start=output_path)
        if (report_path / "source_links.csv").is_file()
        else {"path": relpath(report_path / "source_links.csv", start=output_path), "sha256": "", "bytes": 0},
        "format_targets": manifest_entry(targets_path, start=output_path),
    }
    output_entries = {
        "html_report": manifest_entry(html_path, start=output_path),
        "pdf_report": manifest_entry(pdf_path, start=output_path),
        "docx_report": manifest_entry(docx_path, start=output_path),
        "asset_inventory": manifest_entry(asset_inventory_path, start=output_path),
        "link_audit": manifest_entry(link_audit_path, start=output_path),
    }
    previous = Path(previous_manifest_path) if previous_manifest_path is not None else None
    rebuild_check = compare_previous_manifest(
        previous_manifest_path=previous,
        current_inputs=input_entries,
        current_outputs=output_entries,
    )
    rebuild_check_result = check(
        "format_rebuild_check_is_consistent",
        rebuild_check["valid"],
        observed=rebuild_check,
        expected="changed inputs produce changed primary outputs; unchanged inputs do not drift",
        message="Multi-format outputs should not silently go stale or change without input changes.",
    )

    qa_report = audit_format_package(
        report_dir=report_path,
        output_dir=output_path,
        format_spec=format_spec,
        output_entries=output_entries,
        initial_checks=[rebuild_check_result],
    )
    write_json(qa_report_path, qa_report)
    output_entries["format_qa_report"] = manifest_entry(qa_report_path, start=output_path)

    manifest = {
        "version": RENDERER_VERSION,
        "delivery_id": format_spec.get("delivery_id"),
        "source_report_id": summary["report_id"],
        "hash_algorithm": "sha256",
        "quarto_cli_available": shutil.which("quarto") is not None,
        "renderer_used": "lesson_deterministic_multi_format_renderer",
        "render_commands": {target: target_render_command(format_spec, target) for target in REQUIRED_TARGETS},
        "inputs": input_entries,
        "outputs": output_entries,
        "rebuild_check": rebuild_check,
    }
    write_json(manifest_path, manifest)

    return MultiFormatBuildResult(
        output_dir=output_path,
        html_path=html_path,
        pdf_path=pdf_path,
        docx_path=docx_path,
        targets_path=targets_path,
        asset_inventory_path=asset_inventory_path,
        link_audit_path=link_audit_path,
        qa_report_path=qa_report_path,
        manifest_path=manifest_path,
        qa_report=qa_report,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render and audit HTML, PDF and DOCX report targets.")
    parser.add_argument("--report-dir", type=Path, help="Path to the Quarto report package from lesson 17/03.")
    parser.add_argument("--format-spec", type=Path, help="Optional format_targets.json.")
    parser.add_argument("--previous-manifest", type=Path, help="Optional previous format_manifest.json.")
    parser.add_argument("--output-dir", type=Path, required=True, help="Directory for multi-format outputs.")
    parser.add_argument("--write-example", type=Path, help="Write an example upstream report package before rendering.")
    parser.add_argument("--fail-on-invalid", action="store_true", help="Return exit code 2 when format QA blocks delivery.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report_dir = args.report_dir
    format_spec = args.format_spec
    if args.write_example:
        sample = write_sample_report_package(args.write_example)
        report_dir = sample["report_dir"]
        if format_spec is None:
            format_spec = sample["format_spec_path"]
    if report_dir is None:
        raise SystemExit("missing required argument: --report-dir or --write-example")

    result = build_multi_format_report(
        report_dir=report_dir,
        format_spec_path=format_spec,
        output_dir=args.output_dir,
        previous_manifest_path=args.previous_manifest,
    )
    response = {
        "valid": result.qa_report["valid"],
        "readiness_status": result.qa_report["readiness_status"],
        "blocking_errors": result.qa_report["summary"]["blocking_errors"],
        "warnings": result.qa_report["summary"]["warnings"],
        "html": str(result.html_path),
        "pdf": str(result.pdf_path),
        "docx": str(result.docx_path),
        "manifest": str(result.manifest_path),
    }
    print(json.dumps(response, ensure_ascii=False, indent=2, sort_keys=True))
    if args.fail_on_invalid and not result.qa_report["valid"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
