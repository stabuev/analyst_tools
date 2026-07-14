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
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import streamlit


APP_VERSION = "1.0.0"
REQUIRED_APPENDIX_FILES = [
    "interactive_spec.json",
    "interactive_appendix.html",
    "plotly_figure_spec.json",
    "source_table_links.csv",
    "interaction_audit.json",
    "interaction_manifest.json",
    "static-fallbacks/metric_status.svg",
]
REQUIRED_VIEWS = ["decision_summary", "guardrail_explorer", "evidence_table", "downloads"]
REQUIRED_FILTERS = ["all", "ok", "watch", "breached"]
REQUIRED_DOWNLOAD_IDS = [
    "metric_summary",
    "claim_evidence_matrix",
    "plotly_figure_spec",
    "static_fallback_svg",
    "source_table_links",
    "app_contract",
    "interaction_audit",
]
REQUIRED_STREAMLIT_MARKERS = [
    "import streamlit as st",
    "st.set_page_config",
    "st.sidebar.multiselect",
    "st.plotly_chart",
    "st.dataframe",
    "st.download_button",
    "st.warning",
    "st.error",
    "st.stop",
]
FORBIDDEN_APP_PATTERNS = [
    "pd.read_sql",
    "requests.",
    "urllib.",
    "st.secrets",
    "os.environ",
    "openai",
    "@st.cache_data",
    "@st.cache_resource",
]
REQUIRED_METRIC_COLUMNS = ["metric_id", "label", "current", "baseline", "threshold", "status", "owner"]
REQUIRED_EVIDENCE_COLUMNS = [
    "claim_id",
    "evidence_id",
    "metric_id",
    "quality_status",
    "decision_impact",
]
SENSITIVE_FIELD_RE = re.compile(r"(email|phone|token|secret|password|ssn|passport|user_id)", re.I)
SENSITIVE_VALUE_RE = re.compile(r"[\w.%-]+@[\w.-]+\.[A-Za-z]{2,}|(?:token|secret|password)=\S+", re.I)


@dataclass(frozen=True)
class StreamlitAppBuildResult:
    output_dir: Path
    app_path: Path
    contract_path: Path
    filters_audit_path: Path
    download_manifest_path: Path
    download_bundle_path: Path
    audit_path: Path
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


def default_app_contract() -> dict[str, Any]:
    return {
        "app_id": "trial-onboarding-streamlit-app",
        "source_appendix_id": "trial-onboarding-plotly-appendix",
        "audience": "Growth and Support weekly decision review",
        "audience_task": "Review guardrail breaches, inspect evidence, and download the checked bundle before deciding whether to pause rollout.",
        "required_views": ["decision_summary", "guardrail_explorer", "evidence_table", "downloads"],
        "status_filters": ["all", "ok", "watch", "breached"],
        "default_status_filter": ["breached", "watch"],
        "download_artifacts": [
            {"id": "metric_summary", "path": "app_data/metric_summary.csv", "required": True},
            {"id": "claim_evidence_matrix", "path": "app_data/claim_evidence_matrix.csv", "required": True},
            {"id": "plotly_figure_spec", "path": "app_data/plotly_figure_spec.json", "required": True},
            {"id": "static_fallback_svg", "path": "app_data/static-fallbacks/metric_status.svg", "required": True},
            {"id": "source_table_links", "path": "app_data/source_table_links.csv", "required": True},
            {"id": "app_contract", "path": "app_contract.json", "required": True},
            {"id": "interaction_audit", "path": "app_data/interaction_audit.json", "required": True},
        ],
        "quality_gate_policy": {
            "block_on_invalid_upstream": True,
            "show_warnings": True,
            "empty_state_required": True,
        },
        "input_policy": {
            "precomputed_only": True,
            "forbid_ad_hoc_recompute": True,
            "source_of_truth": "17-delivery/05-interactive-plotly",
        },
        "confidentiality_policy": {
            "forbidden_fields": ["email", "phone", "token", "secret", "password", "user_id"],
            "download_public_only": True,
        },
        "app_source_policy": {
            "no_network": True,
            "no_secrets": True,
            "no_cache_until_next_lesson": True,
        },
    }


def normalize_contract(contract: dict[str, Any] | None) -> dict[str, Any]:
    return default_app_contract() if contract is None else dict(contract)


def load_plotly_builder():
    current = Path(__file__).resolve()
    builder_path = current.parents[2] / "05-interactive-plotly" / "outputs" / "plotly_interactive_appendix.py"
    spec = importlib.util.spec_from_file_location("plotly_builder_for_streamlit", builder_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load Plotly appendix builder: {builder_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_sample_app_inputs(root: str | Path) -> dict[str, Path]:
    root_path = Path(root).resolve()
    root_path.mkdir(parents=True, exist_ok=True)
    plotly_builder = load_plotly_builder()
    sample = plotly_builder.write_sample_delivery_package(root_path / "plotly-inputs")
    appendix = plotly_builder.build_interactive_appendix(
        delivery_dir=sample["delivery_dir"],
        interactive_spec_path=sample["interactive_spec_path"],
        output_dir=root_path / "interactive-appendix",
    )
    contract_path = root_path / "app_contract.json"
    write_json(contract_path, default_app_contract())
    return {
        "interactive_dir": appendix.output_dir,
        "app_contract_path": contract_path,
        "delivery_dir": sample["delivery_dir"],
        "source_report_dir": sample["source_report_dir"],
    }


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


def public_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    hidden = set(sensitive_columns(rows))
    return [{column: value for column, value in row.items() if column not in hidden} for row in rows]


def csv_fieldnames(rows: list[dict[str, str]], fallback: list[str]) -> list[str]:
    if not rows:
        return fallback
    fields: list[str] = []
    for row in rows:
        for column in row:
            if column not in fields:
                fields.append(column)
    return fields


def resolve_source_table_path(interactive_dir: Path, source_row: dict[str, str]) -> Path | None:
    path_text = source_row.get("path", "")
    if not path_text:
        return None
    path = Path(path_text)
    if path.is_absolute():
        return path
    resolved = (interactive_dir / path).resolve()
    if resolved.exists():
        return resolved
    parts = path.parts
    for index, part in enumerate(parts):
        if part in {"..", "."}:
            continue
        candidate = (Path("/") / Path(*parts[index:])).resolve()
        if candidate.exists():
            return candidate
    return resolved


def load_appendix_tables(interactive_dir: str | Path) -> dict[str, Any]:
    interactive_path = Path(interactive_dir).resolve()
    links_path = interactive_path / "source_table_links.csv"
    source_links = read_csv(links_path) if links_path.is_file() else []
    tables: dict[str, dict[str, Any]] = {}
    for source_id in ["metric_summary", "claim_evidence_matrix"]:
        link = next((row for row in source_links if row.get("source_id") == source_id), None)
        table_path = resolve_source_table_path(interactive_path, link) if link else None
        expected_sha = (link or {}).get("sha256", "")
        actual_sha = sha256_file(table_path) if table_path and table_path.is_file() else ""
        tables[source_id] = {
            "source_link": link or {},
            "path": table_path,
            "expected_sha256": expected_sha,
            "actual_sha256": actual_sha,
            "hash_matches": bool(expected_sha and actual_sha and expected_sha == actual_sha),
            "rows": read_csv(table_path) if table_path and table_path.is_file() else [],
        }
    return {"source_links": source_links, "tables": tables}


def appendix_source_hash_mismatches(appendix_data: dict[str, Any]) -> list[dict[str, Any]]:
    mismatches: list[dict[str, Any]] = []
    for source_id, table in appendix_data.get("tables", {}).items():
        if not table.get("hash_matches"):
            mismatches.append(
                {
                    "source_id": source_id,
                    "expected_sha256": table.get("expected_sha256", ""),
                    "actual_sha256": table.get("actual_sha256", ""),
                    "path": str(table.get("path") or ""),
                }
            )
    return mismatches


def sanitized_source_links(
    *,
    metrics: list[dict[str, str]],
    evidence: list[dict[str, str]],
    original_links: list[dict[str, str]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    counts = {"metric_summary": len(metrics), "claim_evidence_matrix": len(evidence)}
    grains = {"metric_summary": "metric_id", "claim_evidence_matrix": "claim_id/evidence_id"}
    for source_id in ["metric_summary", "claim_evidence_matrix"]:
        original = next((row for row in original_links if row.get("source_id") == source_id), {})
        rows.append(
            {
                "source_id": source_id,
                "path": f"app_data/{source_id}.csv",
                "source_sha256": original.get("sha256", ""),
                "row_count": counts[source_id],
                "grain": grains[source_id],
                "used_in": "streamlit_stakeholder_app",
            }
        )
    return rows


def build_filters_audit(metrics: list[dict[str, str]], contract: dict[str, Any]) -> dict[str, Any]:
    statuses = sorted({row.get("status", "") for row in metrics if row.get("status")})
    status_counts = {status: sum(1 for row in metrics if row.get("status") == status) for status in statuses}
    default_filter = list(contract.get("default_status_filter", []))
    allowed_filters = list(contract.get("status_filters", []))
    missing_status_filters = sorted(set(statuses) - set(allowed_filters))
    invalid_default = sorted(set(default_filter) - set(allowed_filters))
    non_empty_defaults = (
        len(metrics)
        if "all" in default_filter
        else sum(count for status, count in status_counts.items() if status in default_filter)
    )
    return {
        "valid": not missing_status_filters and not invalid_default and non_empty_defaults > 0,
        "status_values": statuses,
        "status_counts": status_counts,
        "allowed_filters": allowed_filters,
        "default_status_filter": default_filter,
        "missing_status_filters": missing_status_filters,
        "invalid_default_filter_values": invalid_default,
        "default_result_rows": non_empty_defaults,
    }


def render_streamlit_app_source() -> str:
    return '''from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st


APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "app_data"
DOWNLOAD_DIR = APP_DIR / "downloads"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path)


def load_figure(path: Path) -> go.Figure:
    payload = load_json(path)
    payload.pop("lesson_metadata", None)
    return go.Figure(payload)


def filter_metrics(metrics: pd.DataFrame, selected_statuses: list[str]) -> pd.DataFrame:
    if not selected_statuses or "all" in selected_statuses:
        return metrics
    return metrics[metrics["status"].isin(selected_statuses)]


def filter_evidence(evidence: pd.DataFrame, metric_ids: list[str]) -> pd.DataFrame:
    if not metric_ids:
        return evidence.iloc[0:0]
    return evidence[evidence["metric_id"].isin(metric_ids)]


def show_quality_gate(interaction_audit: dict) -> None:
    if not interaction_audit.get("valid"):
        st.error("Upstream interactive appendix is blocked. Do not use this app for a decision.")
        st.json(interaction_audit.get("summary", {}))
        st.stop()
    warnings = interaction_audit.get("summary", {}).get("warnings", [])
    if warnings:
        st.warning("Upstream appendix has warnings: " + ", ".join(warnings))


def main() -> None:
    st.set_page_config(page_title="Trial onboarding decision app", layout="wide")
    contract = load_json(APP_DIR / "app_contract.json")
    interaction_audit = load_json(DATA_DIR / "interaction_audit.json")
    metrics = load_csv(DATA_DIR / "metric_summary.csv")
    evidence = load_csv(DATA_DIR / "claim_evidence_matrix.csv")
    source_links = load_csv(DATA_DIR / "source_table_links.csv")

    st.title("Trial onboarding decision app")
    st.caption(contract["audience_task"])
    show_quality_gate(interaction_audit)

    selected_statuses = st.sidebar.multiselect(
        "Metric status",
        options=contract["status_filters"],
        default=contract["default_status_filter"],
        key="status_filter",
    )
    view = st.sidebar.radio("Decision view", options=contract["required_views"], index=0)
    filtered_metrics = filter_metrics(metrics, selected_statuses)
    metric_ids = filtered_metrics["metric_id"].tolist()
    filtered_evidence = filter_evidence(evidence, metric_ids)

    if filtered_metrics.empty:
        st.warning("No metrics match the selected filters.")

    if view == "decision_summary":
        breached = int((metrics["status"] == "breached").sum())
        watch = int((metrics["status"] == "watch").sum())
        ok = int((metrics["status"] == "ok").sum())
        left, middle, right = st.columns(3)
        left.metric("Breached", breached)
        middle.metric("Watch", watch)
        right.metric("OK", ok)
        st.dataframe(filtered_metrics, use_container_width=True, hide_index=True)
    elif view == "guardrail_explorer":
        figure = load_figure(DATA_DIR / "plotly_figure_spec.json")
        st.plotly_chart(figure, use_container_width=True)
        st.dataframe(filtered_metrics, use_container_width=True, hide_index=True)
    elif view == "evidence_table":
        st.dataframe(filtered_evidence, use_container_width=True, hide_index=True)
        st.dataframe(source_links, use_container_width=True, hide_index=True)
    else:
        bundle_path = DOWNLOAD_DIR / "stakeholder_app_bundle.zip"
        st.download_button(
            "Download stakeholder app bundle",
            data=bundle_path.read_bytes(),
            file_name="stakeholder_app_bundle.zip",
            mime="application/zip",
            type="primary",
        )
        st.dataframe(source_links, use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()
'''


def app_runbook() -> str:
    return """# Streamlit stakeholder app

Run locally:

```bash
streamlit run streamlit_app.py
```

The app reads only precomputed files from `app_data/`. Rebuild the upstream delivery
package before changing those files.
"""


def deterministic_zip(zip_path: Path, files: list[tuple[str, Path]]) -> None:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for arcname, path in sorted(files):
            info = zipfile.ZipInfo(arcname)
            info.date_time = (2026, 1, 1, 0, 0, 0)
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes())


def download_manifest_rows(downloads: list[dict[str, Any]], output_dir: Path) -> list[dict[str, Any]]:
    rows = []
    for item in downloads:
        path = output_dir / item["path"]
        rows.append(
            {
                "artifact_id": item["id"],
                "path": item["path"],
                "sha256": sha256_file(path) if path.is_file() else "",
                "bytes": path.stat().st_size if path.is_file() else 0,
                "included_in_zip": True,
            }
        )
    return rows


def public_text_for_paths(paths: list[Path]) -> str:
    chunks: list[str] = []
    for path in paths:
        if path.is_file():
            if path.suffix == ".zip":
                with zipfile.ZipFile(path) as archive:
                    for name in archive.namelist():
                        chunks.append(name)
                        chunks.append(archive.read(name).decode("utf-8", errors="ignore"))
            else:
                chunks.append(path.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(chunks)


def public_audit_payload(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, nested in value.items():
            if key in {"redacted_fields", "leaked_columns", "leaked_values"} and isinstance(nested, list):
                sanitized[f"{key[:-1]}_count" if key.endswith("s") else f"{key}_count"] = len(nested)
            else:
                sanitized[key] = public_audit_payload(nested)
        return sanitized
    if isinstance(value, list):
        return [public_audit_payload(item) for item in value]
    return value


def audit_streamlit_app(
    *,
    interactive_dir: str | Path,
    output_dir: str | Path,
    app_contract: dict[str, Any] | None = None,
    output_entries: dict[str, dict[str, Any]] | None = None,
    source_sensitive_values: list[str] | None = None,
    source_sensitive_columns: list[str] | None = None,
) -> dict[str, Any]:
    interactive_path = Path(interactive_dir)
    output_path = Path(output_dir)
    contract = normalize_contract(app_contract)
    checks: list[dict[str, Any]] = []

    missing_appendix_files = sorted(
        name for name in REQUIRED_APPENDIX_FILES if not (interactive_path / name).is_file()
    )
    checks.append(
        check(
            "interactive_appendix_package_is_complete",
            not missing_appendix_files,
            observed=missing_appendix_files,
            expected=REQUIRED_APPENDIX_FILES,
            message="The Streamlit app must start from the checked Plotly appendix bundle.",
        )
    )

    appendix_data = load_appendix_tables(interactive_path)
    source_hash_mismatches = appendix_source_hash_mismatches(appendix_data)
    checks.append(
        check(
            "appendix_source_table_hashes_match_links",
            not source_hash_mismatches,
            observed=source_hash_mismatches,
            expected="source table hashes recorded by the Plotly appendix",
            message="The app must not silently read source tables that changed after the checked appendix was built.",
        )
    )

    interaction_audit_path = interactive_path / "interaction_audit.json"
    interaction_audit = read_json(interaction_audit_path) if interaction_audit_path.is_file() else {}
    checks.append(
        check(
            "upstream_interaction_audit_is_valid",
            bool(interaction_audit.get("valid")),
            observed=interaction_audit.get("summary", {}).get("blocking_errors", []),
            expected=[],
            message="Do not wrap a blocked interactive appendix in an app.",
        )
    )

    views = list(contract.get("required_views", []))
    filters = list(contract.get("status_filters", []))
    downloads = list(contract.get("download_artifacts", []))
    download_ids = [item.get("id") for item in downloads]
    checks.append(
        check(
            "app_contract_declares_views_filters_downloads_and_quality_policy",
            set(REQUIRED_VIEWS).issubset(set(views))
            and set(REQUIRED_FILTERS).issubset(set(filters))
            and set(REQUIRED_DOWNLOAD_IDS).issubset(set(download_ids))
            and contract.get("quality_gate_policy", {}).get("empty_state_required") is True,
            observed={"views": views, "filters": filters, "download_ids": download_ids},
            expected={"views": REQUIRED_VIEWS, "filters": REQUIRED_FILTERS, "downloads": REQUIRED_DOWNLOAD_IDS},
            message="App UX controls are part of the stakeholder delivery contract.",
        )
    )

    input_policy = contract.get("input_policy", {})
    app_source_policy = contract.get("app_source_policy", {})
    checks.append(
        check(
            "app_uses_precomputed_artifacts_only",
            input_policy.get("precomputed_only") is True
            and input_policy.get("forbid_ad_hoc_recompute") is True
            and app_source_policy.get("no_network") is True
            and app_source_policy.get("no_secrets") is True,
            observed={"input_policy": input_policy, "app_source_policy": app_source_policy},
            expected="precomputed-only, no network and no secrets",
            message="The app should deliver checked artifacts, not rerun hidden analysis.",
        )
    )

    filters_audit_path = output_path / "filters_audit.json"
    filters_audit = read_json(filters_audit_path) if filters_audit_path.is_file() else {}
    checks.append(
        check(
            "filters_audit_matches_metric_status_values",
            bool(filters_audit.get("valid"))
            and not filters_audit.get("missing_status_filters")
            and filters_audit.get("default_result_rows", 0) > 0,
            observed=filters_audit,
            expected="all source statuses covered and default filter non-empty",
            message="Filters must not hide the decision rows by default.",
        )
    )

    app_path = output_path / "streamlit_app.py"
    app_source = app_path.read_text(encoding="utf-8") if app_path.is_file() else ""
    missing_markers = [marker for marker in REQUIRED_STREAMLIT_MARKERS if marker not in app_source]
    forbidden_patterns = [pattern for pattern in FORBIDDEN_APP_PATTERNS if pattern in app_source]
    checks.append(
        check(
            "streamlit_app_source_uses_required_api_and_quality_states",
            app_path.is_file() and not missing_markers,
            observed=missing_markers,
            expected=REQUIRED_STREAMLIT_MARKERS,
            message="The generated app should expose filters, charts, tables, downloads and blockers.",
        )
    )
    checks.append(
        check(
            "streamlit_app_source_avoids_forbidden_runtime_patterns",
            not forbidden_patterns,
            observed=forbidden_patterns,
            expected=[],
            message="Lesson 17/06 is a checked app wrapper, not network, secrets or cache logic.",
        )
    )

    download_manifest_path = output_path / "download_manifest.json"
    download_manifest = read_json(download_manifest_path) if download_manifest_path.is_file() else {}
    zip_path = output_path / "downloads" / "stakeholder_app_bundle.zip"
    expected_zip_names = sorted(row["path"] for row in download_manifest.get("files", []))
    zip_names = sorted(zipfile.ZipFile(zip_path).namelist()) if zip_path.is_file() else []
    checks.append(
        check(
            "download_bundle_contains_declared_public_artifacts",
            zip_path.is_file() and zip_names == expected_zip_names,
            observed=zip_names,
            expected=expected_zip_names,
            message="Download button must return the same checked files named in the manifest.",
        )
    )

    app_source_links = output_path / "app_data" / "source_table_links.csv"
    source_rows = read_csv(app_source_links) if app_source_links.is_file() else []
    checks.append(
        check(
            "source_links_are_carried_into_app_data",
            {row.get("source_id") for row in source_rows} == {"metric_summary", "claim_evidence_matrix"}
            and all(len(row.get("source_sha256", "")) == 64 for row in source_rows),
            observed=source_rows,
            expected=["metric_summary", "claim_evidence_matrix"],
            message="The app should keep lineage for tables shown and downloaded.",
        )
    )

    public_paths = [
        output_path / "streamlit_app.py",
        output_path / "app_contract.json",
        output_path / "app_data" / "metric_summary.csv",
        output_path / "app_data" / "claim_evidence_matrix.csv",
        output_path / "app_data" / "plotly_figure_spec.json",
        output_path / "app_data" / "source_table_links.csv",
        zip_path,
    ]
    public_text = public_text_for_paths(public_paths)
    source_values = source_sensitive_values or []
    source_columns = source_sensitive_columns or []
    leaked_values = [value for value in source_values if value and value in public_text]
    leaked_columns = [column for column in source_columns if re.search(column, public_text, flags=re.IGNORECASE)]
    checks.append(
        check(
            "downloads_and_app_data_exclude_sensitive_fields",
            not leaked_values and not leaked_columns,
            observed={"leaked_value_count": len(leaked_values), "leaked_columns": sorted(leaked_columns)},
            expected="no sensitive source fields or values in app outputs",
            message="App downloads are public delivery artifacts.",
        )
    )

    if output_entries is not None:
        missing_hashes = sorted(key for key, value in output_entries.items() if len(value.get("sha256", "")) != 64)
    else:
        missing_hashes = ["not_provided"]
    checks.append(
        check(
            "manifest_hashes_streamlit_app_outputs",
            not missing_hashes,
            observed=missing_hashes,
            expected=[],
            message="App source, data, downloads and audits need checksums.",
        )
    )

    blockers = [item["id"] for item in checks if not item["valid"] and item["severity"] == "block"]
    warnings = [item["id"] for item in checks if not item["valid"] and item["severity"] == "warn"]
    return {
        "version": APP_VERSION,
        "app_id": contract.get("app_id"),
        "valid": not blockers,
        "readiness_status": "blocked" if blockers else ("ready_with_warnings" if warnings else "ready"),
        "summary": {
            "blocking_errors": blockers,
            "warnings": warnings,
            "check_count": len(checks),
        },
        "checks": checks,
    }


def build_streamlit_app(
    *,
    interactive_dir: str | Path,
    output_dir: str | Path,
    app_contract_path: str | Path | None = None,
) -> StreamlitAppBuildResult:
    interactive_path = Path(interactive_dir)
    output_path = Path(output_dir)
    app_data_dir = output_path / "app_data"
    static_dir = app_data_dir / "static-fallbacks"
    downloads_dir = output_path / "downloads"
    output_path.mkdir(parents=True, exist_ok=True)
    app_data_dir.mkdir(parents=True, exist_ok=True)
    static_dir.mkdir(parents=True, exist_ok=True)
    downloads_dir.mkdir(parents=True, exist_ok=True)

    contract = read_json(app_contract_path) if app_contract_path else default_app_contract()
    contract = normalize_contract(contract)
    appendix_data = load_appendix_tables(interactive_path)
    raw_metrics = appendix_data["tables"]["metric_summary"]["rows"]
    raw_evidence = appendix_data["tables"]["claim_evidence_matrix"]["rows"]
    source_sensitive = sensitive_values(raw_metrics) + sensitive_values(raw_evidence)
    source_sensitive_fields = sensitive_columns(raw_metrics) + sensitive_columns(raw_evidence)
    metrics = public_rows(raw_metrics)
    evidence = public_rows(raw_evidence)

    contract_path = output_path / "app_contract.json"
    metrics_path = app_data_dir / "metric_summary.csv"
    evidence_path = app_data_dir / "claim_evidence_matrix.csv"
    figure_path = app_data_dir / "plotly_figure_spec.json"
    fallback_path = static_dir / "metric_status.svg"
    source_links_path = app_data_dir / "source_table_links.csv"
    interaction_audit_path = app_data_dir / "interaction_audit.json"
    interaction_manifest_path = app_data_dir / "interaction_manifest.json"
    app_path = output_path / "streamlit_app.py"
    runbook_path = output_path / "app_runbook.md"
    filters_audit_path = output_path / "filters_audit.json"
    download_manifest_path = output_path / "download_manifest.json"
    bundle_path = downloads_dir / "stakeholder_app_bundle.zip"
    audit_path = output_path / "app_audit.json"
    manifest_path = output_path / "app_manifest.json"

    write_json(contract_path, contract)
    write_csv(metrics_path, metrics, csv_fieldnames(metrics, REQUIRED_METRIC_COLUMNS))
    write_csv(evidence_path, evidence, csv_fieldnames(evidence, REQUIRED_EVIDENCE_COLUMNS))
    write_csv(
        source_links_path,
        sanitized_source_links(
            metrics=metrics,
            evidence=evidence,
            original_links=appendix_data["source_links"],
        ),
        ["source_id", "path", "source_sha256", "row_count", "grain", "used_in"],
    )
    if (interactive_path / "plotly_figure_spec.json").is_file():
        shutil.copyfile(interactive_path / "plotly_figure_spec.json", figure_path)
    else:
        write_json(figure_path, {})
    if (interactive_path / "static-fallbacks" / "metric_status.svg").is_file():
        shutil.copyfile(interactive_path / "static-fallbacks" / "metric_status.svg", fallback_path)
    else:
        fallback_path.write_text("", encoding="utf-8")
    if (interactive_path / "interaction_audit.json").is_file():
        write_json(interaction_audit_path, public_audit_payload(read_json(interactive_path / "interaction_audit.json")))
    else:
        write_json(interaction_audit_path, {})
    if (interactive_path / "interaction_manifest.json").is_file():
        shutil.copyfile(interactive_path / "interaction_manifest.json", interaction_manifest_path)
    else:
        write_json(interaction_manifest_path, {})

    app_path.write_text(render_streamlit_app_source(), encoding="utf-8")
    runbook_path.write_text(app_runbook(), encoding="utf-8")
    filters_audit = build_filters_audit(metrics, contract)
    write_json(filters_audit_path, filters_audit)

    downloads = list(contract.get("download_artifacts", []))
    manifest_files = download_manifest_rows(downloads, output_path)
    write_json(
        download_manifest_path,
        {
            "version": APP_VERSION,
            "download_bundle": "downloads/stakeholder_app_bundle.zip",
            "files": manifest_files,
        },
    )
    deterministic_zip(
        bundle_path,
        [(row["path"], output_path / row["path"]) for row in manifest_files if (output_path / row["path"]).is_file()],
    )

    output_entries = {
        "streamlit_app": manifest_entry(app_path, start=output_path),
        "app_contract": manifest_entry(contract_path, start=output_path),
        "metric_summary": manifest_entry(metrics_path, start=output_path),
        "claim_evidence_matrix": manifest_entry(evidence_path, start=output_path),
        "plotly_figure_spec": manifest_entry(figure_path, start=output_path),
        "static_fallback_svg": manifest_entry(fallback_path, start=output_path),
        "source_table_links": manifest_entry(source_links_path, start=output_path),
        "interaction_audit": manifest_entry(interaction_audit_path, start=output_path),
        "interaction_manifest": manifest_entry(interaction_manifest_path, start=output_path),
        "filters_audit": manifest_entry(filters_audit_path, start=output_path),
        "download_manifest": manifest_entry(download_manifest_path, start=output_path),
        "download_bundle": manifest_entry(bundle_path, start=output_path),
        "app_runbook": manifest_entry(runbook_path, start=output_path),
    }
    audit = audit_streamlit_app(
        interactive_dir=interactive_path,
        output_dir=output_path,
        app_contract=contract,
        output_entries=output_entries,
        source_sensitive_values=source_sensitive,
        source_sensitive_columns=source_sensitive_fields,
    )
    write_json(audit_path, audit)
    output_entries["app_audit"] = manifest_entry(audit_path, start=output_path)

    input_entries = {
        "app_contract": manifest_entry(contract_path, start=output_path),
        **{
            f"appendix_{name.replace('/', '_').replace('.', '_')}": optional_manifest_entry(
                interactive_path / name,
                start=output_path,
            )
            for name in REQUIRED_APPENDIX_FILES
        },
    }
    manifest = {
        "version": APP_VERSION,
        "app_id": contract.get("app_id"),
        "hash_algorithm": "sha256",
        "renderer_used": "streamlit_stakeholder_app_builder",
        "streamlit_version": streamlit.__version__,
        "interactive_dir": relpath(interactive_path, start=output_path),
        "inputs": input_entries,
        "outputs": output_entries,
    }
    write_json(manifest_path, manifest)

    return StreamlitAppBuildResult(
        output_dir=output_path,
        app_path=app_path,
        contract_path=contract_path,
        filters_audit_path=filters_audit_path,
        download_manifest_path=download_manifest_path,
        download_bundle_path=bundle_path,
        audit_path=audit_path,
        manifest_path=manifest_path,
        audit=audit,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a checked Streamlit app bundle from a Plotly appendix.")
    parser.add_argument("--interactive-dir", type=Path, help="Path to the 17/05 interactive appendix bundle.")
    parser.add_argument("--app-contract", type=Path, help="Optional app_contract.json.")
    parser.add_argument("--output-dir", type=Path, required=True, help="Directory for the Streamlit app bundle.")
    parser.add_argument("--write-example", type=Path, help="Write a sample upstream Plotly appendix before building.")
    parser.add_argument("--fail-on-invalid", action="store_true", help="Return exit code 2 when app audit blocks delivery.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    interactive_dir = args.interactive_dir
    app_contract = args.app_contract
    if args.write_example:
        sample = write_sample_app_inputs(args.write_example)
        interactive_dir = sample["interactive_dir"]
        if app_contract is None:
            app_contract = sample["app_contract_path"]
    if interactive_dir is None:
        raise SystemExit("missing required argument: --interactive-dir or --write-example")

    result = build_streamlit_app(
        interactive_dir=interactive_dir,
        app_contract_path=app_contract,
        output_dir=args.output_dir,
    )
    response = {
        "valid": result.audit["valid"],
        "readiness_status": result.audit["readiness_status"],
        "blocking_errors": result.audit["summary"]["blocking_errors"],
        "app": str(result.app_path),
        "download_bundle": str(result.download_bundle_path),
        "manifest": str(result.manifest_path),
    }
    print(json.dumps(response, ensure_ascii=False, indent=2, sort_keys=True))
    if args.fail_on_invalid and not result.audit["valid"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
