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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import streamlit


CACHE_STATE_VERSION = "1.0.0"
DEFAULT_SOURCE_SNAPSHOT_UTC = "2026-01-01T00:00:00Z"
DEFAULT_CHECKED_AT_UTC = "2026-01-01T00:10:00Z"
REQUIRED_APP_FILES = [
    "app_contract.json",
    "app_data/metric_summary.csv",
    "app_data/claim_evidence_matrix.csv",
    "app_data/plotly_figure_spec.json",
    "app_data/static-fallbacks/metric_status.svg",
    "app_data/source_table_links.csv",
    "app_data/interaction_audit.json",
    "app_data/interaction_manifest.json",
    "filters_audit.json",
    "download_manifest.json",
    "downloads/stakeholder_app_bundle.zip",
    "app_audit.json",
    "app_manifest.json",
]
TRACKED_INPUT_FILES = [
    "app_contract.json",
    "app_data/metric_summary.csv",
    "app_data/claim_evidence_matrix.csv",
    "app_data/plotly_figure_spec.json",
    "app_data/source_table_links.csv",
    "app_data/interaction_audit.json",
    "app_data/interaction_manifest.json",
    "app_data/static-fallbacks/metric_status.svg",
    "filters_audit.json",
    "download_manifest.json",
    "app_audit.json",
    "app_manifest.json",
]
REQUIRED_CACHE_FUNCTIONS = {
    "load_csv_cached": {"decorator": "st.cache_data", "kind": "data"},
    "load_json_cached": {"decorator": "st.cache_data", "kind": "data"},
    "load_figure_resource": {"decorator": "st.cache_resource", "kind": "resource"},
}
REQUIRED_SESSION_STATE_KEYS = [
    "selected_statuses",
    "decision_view",
    "last_seen_input_digest",
    "manual_refresh_count",
]
REQUIRED_SOURCE_MARKERS = [
    "@st.cache_data",
    "@st.cache_resource",
    "st.session_state",
    "load_csv_cached.clear()",
    "load_json_cached.clear()",
    "load_figure_resource.clear()",
    "st.sidebar.button",
    "st.sidebar.metric",
    "disabled=freshness_report[\"stale\"]",
]
FORBIDDEN_APP_PATTERNS = [
    "pd.read_sql",
    "requests.",
    "urllib.",
    "st.secrets",
    "os.environ",
    "openai",
    "persist=\"disk\"",
    "persist=True",
]
SENSITIVE_STATE_RE = re.compile(r"(email|phone|token|secret|password|ssn|passport|user_id)", re.I)


@dataclass(frozen=True)
class CacheStateBuildResult:
    output_dir: Path
    app_path: Path
    cache_state_contract_path: Path
    freshness_policy_path: Path
    freshness_report_path: Path
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


def default_cache_state_contract() -> dict[str, Any]:
    return {
        "cache_state_id": "trial-onboarding-cache-state-policy",
        "source_app_id": "trial-onboarding-streamlit-app",
        "cache_functions": [
            {
                "name": "load_csv_cached",
                "kind": "data",
                "decorator": "st.cache_data",
                "ttl_policy_ref": "data_cache_ttl_seconds",
                "max_entries_policy_ref": "data_cache_max_entries",
                "hash_inputs": ["path", "checksum"],
                "return_type": "pandas.DataFrame",
            },
            {
                "name": "load_json_cached",
                "kind": "data",
                "decorator": "st.cache_data",
                "ttl_policy_ref": "data_cache_ttl_seconds",
                "max_entries_policy_ref": "data_cache_max_entries",
                "hash_inputs": ["path", "checksum"],
                "return_type": "dict",
            },
            {
                "name": "load_figure_resource",
                "kind": "resource",
                "decorator": "st.cache_resource",
                "ttl_policy_ref": "resource_cache_ttl_seconds",
                "max_entries_policy_ref": "resource_cache_max_entries",
                "hash_inputs": ["path", "checksum"],
                "validate": "validate_figure_resource",
                "return_type": "immutable_figure_payload",
            },
        ],
        "session_state_keys": [
            {
                "key": "selected_statuses",
                "scope": "session",
                "purpose": "Per-user status filters.",
                "contains_sensitive_data": False,
            },
            {
                "key": "decision_view",
                "scope": "session",
                "purpose": "Per-user active decision view.",
                "contains_sensitive_data": False,
            },
            {
                "key": "last_seen_input_digest",
                "scope": "session",
                "purpose": "Reset UI defaults when app inputs change.",
                "contains_sensitive_data": False,
            },
            {
                "key": "manual_refresh_count",
                "scope": "session",
                "purpose": "Expose manual cache refreshes without storing user data.",
                "contains_sensitive_data": False,
            },
        ],
        "freshness_panel": {
            "required": True,
            "show_input_age_seconds": True,
            "show_input_digest": True,
            "show_stale_warning": True,
            "disable_download_when_stale": True,
        },
        "invalidation_policy": {
            "checksum_invalidation_required": True,
            "manual_cache_clear_required": True,
            "clear_data_cache": True,
            "clear_resource_cache": True,
            "reset_session_state_on_input_digest_change": True,
        },
        "app_source_policy": {
            "no_network": True,
            "no_secrets": True,
            "no_disk_persist_cache": True,
            "no_cross_session_sensitive_state": True,
        },
    }


def default_freshness_policy(
    *,
    source_snapshot_utc: str = DEFAULT_SOURCE_SNAPSHOT_UTC,
    checked_at_utc: str = DEFAULT_CHECKED_AT_UTC,
) -> dict[str, Any]:
    return {
        "freshness_policy_id": "trial-onboarding-app-freshness",
        "source_app_id": "trial-onboarding-streamlit-app",
        "source_snapshot_utc": source_snapshot_utc,
        "checked_at_utc": checked_at_utc,
        "timezone": "UTC",
        "max_input_age_seconds": 3600,
        "data_cache_ttl_seconds": 900,
        "resource_cache_ttl_seconds": 3600,
        "data_cache_max_entries": 16,
        "resource_cache_max_entries": 4,
        "block_on_stale": True,
        "input_digest_algorithm": "sha256",
        "tracked_files": TRACKED_INPUT_FILES,
    }


def normalize_cache_state_contract(contract: dict[str, Any] | None) -> dict[str, Any]:
    return default_cache_state_contract() if contract is None else dict(contract)


def normalize_freshness_policy(
    policy: dict[str, Any] | None,
    *,
    source_snapshot_utc: str | None = None,
    checked_at_utc: str | None = None,
) -> dict[str, Any]:
    normalized = default_freshness_policy(
        source_snapshot_utc=source_snapshot_utc or DEFAULT_SOURCE_SNAPSHOT_UTC,
        checked_at_utc=checked_at_utc or DEFAULT_CHECKED_AT_UTC,
    )
    if policy is not None:
        normalized.update(policy)
    if source_snapshot_utc is not None:
        normalized["source_snapshot_utc"] = source_snapshot_utc
    if checked_at_utc is not None:
        normalized["checked_at_utc"] = checked_at_utc
    return normalized


def parse_utc(value: str) -> datetime | None:
    try:
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def seconds_between(start: str, end: str) -> int | None:
    start_dt = parse_utc(start)
    end_dt = parse_utc(end)
    if start_dt is None or end_dt is None:
        return None
    return int((end_dt - start_dt).total_seconds())


def load_streamlit_builder():
    current = Path(__file__).resolve()
    builder_path = current.parents[2] / "06-streamlit" / "outputs" / "streamlit_stakeholder_app.py"
    spec = importlib.util.spec_from_file_location("streamlit_builder_for_cache_state", builder_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load Streamlit app builder: {builder_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_sample_cache_state_inputs(root: str | Path) -> dict[str, Path]:
    root_path = Path(root).resolve()
    root_path.mkdir(parents=True, exist_ok=True)
    streamlit_builder = load_streamlit_builder()
    sample = streamlit_builder.write_sample_app_inputs(root_path / "app-inputs")
    app = streamlit_builder.build_streamlit_app(
        interactive_dir=sample["interactive_dir"],
        app_contract_path=sample["app_contract_path"],
        output_dir=root_path / "streamlit-app",
    )
    contract_path = root_path / "cache_state_contract.json"
    policy_path = root_path / "freshness_policy.json"
    write_json(contract_path, default_cache_state_contract())
    write_json(policy_path, default_freshness_policy())
    return {
        "app_dir": app.output_dir,
        "cache_state_contract_path": contract_path,
        "freshness_policy_path": policy_path,
        "interactive_dir": sample["interactive_dir"],
    }


def copy_app_bundle(app_dir: str | Path, output_dir: str | Path) -> None:
    source = Path(app_dir)
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    for relative in REQUIRED_APP_FILES + ["app_runbook.md"]:
        source_path = source / relative
        target_path = destination / relative
        if source_path.is_file():
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_path, target_path)


def tracked_file_inventory(app_dir: str | Path, policy: dict[str, Any]) -> list[dict[str, Any]]:
    root = Path(app_dir)
    rows: list[dict[str, Any]] = []
    for relative in policy.get("tracked_files", TRACKED_INPUT_FILES):
        path = root / relative
        rows.append(
            {
                "path": relative,
                "sha256": sha256_file(path) if path.is_file() else "",
                "bytes": path.stat().st_size if path.is_file() else 0,
                "missing": not path.is_file(),
            }
        )
    return rows


def input_digest(inventory: list[dict[str, Any]]) -> str:
    payload = [
        {"path": row["path"], "sha256": row.get("sha256", ""), "missing": bool(row.get("missing"))}
        for row in sorted(inventory, key=lambda item: item["path"])
    ]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def build_freshness_report(app_dir: str | Path, policy: dict[str, Any]) -> dict[str, Any]:
    inventory = tracked_file_inventory(app_dir, policy)
    age_seconds = seconds_between(policy.get("source_snapshot_utc", ""), policy.get("checked_at_utc", ""))
    max_age = int(policy.get("max_input_age_seconds", 0) or 0)
    missing_inputs = sorted(row["path"] for row in inventory if row.get("missing"))
    stale_reasons: list[str] = []
    if age_seconds is None:
        stale_reasons.append("invalid_freshness_timestamps")
    elif age_seconds < 0:
        stale_reasons.append("checked_at_before_source_snapshot")
    elif max_age <= 0:
        stale_reasons.append("invalid_max_input_age_seconds")
    elif age_seconds > max_age:
        stale_reasons.append("input_age_exceeds_policy")
    if missing_inputs:
        stale_reasons.append("tracked_input_missing")
    stale = bool(stale_reasons)
    return {
        "version": CACHE_STATE_VERSION,
        "freshness_policy_id": policy.get("freshness_policy_id"),
        "valid": not stale,
        "stale": stale,
        "stale_reasons": stale_reasons,
        "missing_inputs": missing_inputs,
        "source_snapshot_utc": policy.get("source_snapshot_utc", ""),
        "checked_at_utc": policy.get("checked_at_utc", ""),
        "input_age_seconds": age_seconds,
        "max_input_age_seconds": max_age,
        "cache_policy": {
            "data_cache_ttl_seconds": policy.get("data_cache_ttl_seconds"),
            "resource_cache_ttl_seconds": policy.get("resource_cache_ttl_seconds"),
            "data_cache_max_entries": policy.get("data_cache_max_entries"),
            "resource_cache_max_entries": policy.get("resource_cache_max_entries"),
            "block_on_stale": policy.get("block_on_stale"),
        },
        "input_digest": input_digest(inventory),
        "tracked_files": inventory,
    }


def render_cache_state_app_source() -> str:
    return '''from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st


APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "app_data"
DOWNLOAD_DIR = APP_DIR / "downloads"


def load_json_uncached(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


FRESHNESS_REPORT = load_json_uncached(APP_DIR / "freshness_report.json")
DATA_CACHE_TTL_SECONDS = int(FRESHNESS_REPORT["cache_policy"]["data_cache_ttl_seconds"])
RESOURCE_CACHE_TTL_SECONDS = int(FRESHNESS_REPORT["cache_policy"]["resource_cache_ttl_seconds"])
DATA_CACHE_MAX_ENTRIES = int(FRESHNESS_REPORT["cache_policy"]["data_cache_max_entries"])
RESOURCE_CACHE_MAX_ENTRIES = int(FRESHNESS_REPORT["cache_policy"]["resource_cache_max_entries"])


def checksum_for(freshness_report: dict, relative_path: str) -> str:
    for item in freshness_report["tracked_files"]:
        if item["path"] == relative_path:
            return item["sha256"]
    raise KeyError(relative_path)


@st.cache_data(ttl=DATA_CACHE_TTL_SECONDS, max_entries=DATA_CACHE_MAX_ENTRIES, show_spinner=False)
def load_json_cached(path_text: str, checksum: str) -> dict:
    return json.loads(Path(path_text).read_text(encoding="utf-8"))


@st.cache_data(ttl=DATA_CACHE_TTL_SECONDS, max_entries=DATA_CACHE_MAX_ENTRIES, show_spinner="Loading app data")
def load_csv_cached(path_text: str, checksum: str) -> pd.DataFrame:
    return pd.read_csv(Path(path_text))


def validate_figure_resource(resource: dict) -> bool:
    return isinstance(resource, dict) and "payload" in resource and "checksum" in resource


@st.cache_resource(
    ttl=RESOURCE_CACHE_TTL_SECONDS,
    max_entries=RESOURCE_CACHE_MAX_ENTRIES,
    validate=validate_figure_resource,
    show_spinner=False,
)
def load_figure_resource(path_text: str, checksum: str) -> dict:
    payload = load_json_uncached(Path(path_text))
    payload.pop("lesson_metadata", None)
    return {"payload": payload, "checksum": checksum}


def clear_cached_loaders() -> None:
    load_csv_cached.clear()
    load_json_cached.clear()
    load_figure_resource.clear()
    st.session_state.manual_refresh_count = st.session_state.get("manual_refresh_count", 0) + 1


def initialize_session_state(contract: dict, freshness_report: dict) -> None:
    input_digest_value = freshness_report["input_digest"]
    if st.session_state.get("last_seen_input_digest") != input_digest_value:
        st.session_state.last_seen_input_digest = input_digest_value
        st.session_state.selected_statuses = list(contract["default_status_filter"])
        st.session_state.decision_view = contract["required_views"][0]
        st.session_state.manual_refresh_count = 0
    st.session_state.setdefault("selected_statuses", list(contract["default_status_filter"]))
    st.session_state.setdefault("decision_view", contract["required_views"][0])
    st.session_state.setdefault("manual_refresh_count", 0)


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


def show_freshness_panel(freshness_report: dict) -> None:
    st.sidebar.subheader("Freshness")
    age_minutes = round((freshness_report.get("input_age_seconds") or 0) / 60, 1)
    st.sidebar.metric("Input age, min", age_minutes)
    st.sidebar.caption("Input digest: " + freshness_report["input_digest"][:12])
    st.sidebar.caption("Manual cache refreshes: " + str(st.session_state.manual_refresh_count))
    if freshness_report["stale"]:
        st.sidebar.warning("Inputs are stale: " + ", ".join(freshness_report["stale_reasons"]))
    else:
        st.sidebar.success("Inputs are fresh")


def figure_from_resource(resource: dict) -> go.Figure:
    return go.Figure(resource["payload"])


def main() -> None:
    st.set_page_config(page_title="Trial onboarding decision app", layout="wide")
    freshness_report = load_json_uncached(APP_DIR / "freshness_report.json")
    contract = load_json_cached(
        str(APP_DIR / "app_contract.json"),
        checksum_for(freshness_report, "app_contract.json"),
    )
    initialize_session_state(contract, freshness_report)
    interaction_audit = load_json_cached(
        str(DATA_DIR / "interaction_audit.json"),
        checksum_for(freshness_report, "app_data/interaction_audit.json"),
    )
    metrics = load_csv_cached(
        str(DATA_DIR / "metric_summary.csv"),
        checksum_for(freshness_report, "app_data/metric_summary.csv"),
    )
    evidence = load_csv_cached(
        str(DATA_DIR / "claim_evidence_matrix.csv"),
        checksum_for(freshness_report, "app_data/claim_evidence_matrix.csv"),
    )
    source_links = load_csv_cached(
        str(DATA_DIR / "source_table_links.csv"),
        checksum_for(freshness_report, "app_data/source_table_links.csv"),
    )

    st.title("Trial onboarding decision app")
    st.caption(contract["audience_task"])
    show_quality_gate(interaction_audit)
    show_freshness_panel(freshness_report)
    st.sidebar.button("Refresh cached data", on_click=clear_cached_loaders)

    selected_statuses = st.sidebar.multiselect(
        "Metric status",
        options=contract["status_filters"],
        key="selected_statuses",
    )
    view = st.sidebar.radio("Decision view", options=contract["required_views"], key="decision_view")
    filtered_metrics = filter_metrics(metrics, selected_statuses)
    metric_ids = filtered_metrics["metric_id"].tolist()
    filtered_evidence = filter_evidence(evidence, metric_ids)

    if filtered_metrics.empty:
        st.warning("No metrics match the selected filters.")
    if freshness_report["stale"]:
        st.error("This app is using stale inputs. Rebuild the delivery package before making a decision.")

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
        resource = load_figure_resource(
            str(DATA_DIR / "plotly_figure_spec.json"),
            checksum_for(freshness_report, "app_data/plotly_figure_spec.json"),
        )
        st.plotly_chart(figure_from_resource(resource), use_container_width=True)
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
            disabled=freshness_report["stale"],
        )
        st.dataframe(source_links, use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()
'''


def cache_state_runbook() -> str:
    return """# Streamlit cache/state/freshness app

Run locally:

```bash
streamlit run streamlit_app.py
```

The app uses `st.cache_data` for public CSV/JSON data, `st.cache_resource` for the
Plotly figure payload, and `st.session_state` only for per-session UI selections.
Checksum parameters invalidate cached loaders when app inputs change. Rebuild the
package when `freshness_report.json` marks inputs as stale.
"""


def cache_functions_by_name(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item.get("name", ""): item for item in contract.get("cache_functions", [])}


def required_cache_function_errors(contract: dict[str, Any]) -> list[dict[str, Any]]:
    by_name = cache_functions_by_name(contract)
    errors: list[dict[str, Any]] = []
    for name, expected in REQUIRED_CACHE_FUNCTIONS.items():
        item = by_name.get(name)
        if item is None:
            errors.append({"name": name, "error": "missing"})
            continue
        if item.get("decorator") != expected["decorator"] or item.get("kind") != expected["kind"]:
            errors.append(
                {
                    "name": name,
                    "decorator": item.get("decorator"),
                    "kind": item.get("kind"),
                    "expected": expected,
                }
            )
        if sorted(item.get("hash_inputs", [])) != ["checksum", "path"]:
            errors.append({"name": name, "hash_inputs": item.get("hash_inputs", [])})
    return errors


def session_state_errors(contract: dict[str, Any]) -> list[dict[str, Any]]:
    keys = contract.get("session_state_keys", [])
    by_key = {item.get("key", ""): item for item in keys}
    errors: list[dict[str, Any]] = []
    for key in REQUIRED_SESSION_STATE_KEYS:
        item = by_key.get(key)
        if item is None:
            errors.append({"key": key, "error": "missing"})
            continue
        if item.get("scope") != "session" or item.get("contains_sensitive_data") is not False:
            errors.append({"key": key, "scope": item.get("scope"), "sensitive": item.get("contains_sensitive_data")})
    sensitive_names = sorted(key for key in by_key if SENSITIVE_STATE_RE.search(key))
    if sensitive_names:
        errors.append({"sensitive_key_names": sensitive_names})
    return errors


def freshness_policy_errors(policy: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    data_ttl = int(policy.get("data_cache_ttl_seconds", 0) or 0)
    resource_ttl = int(policy.get("resource_cache_ttl_seconds", 0) or 0)
    max_age = int(policy.get("max_input_age_seconds", 0) or 0)
    data_entries = int(policy.get("data_cache_max_entries", 0) or 0)
    resource_entries = int(policy.get("resource_cache_max_entries", 0) or 0)
    if data_ttl <= 0:
        errors.append("data_cache_ttl_seconds_must_be_positive")
    if resource_ttl <= 0:
        errors.append("resource_cache_ttl_seconds_must_be_positive")
    if max_age <= 0:
        errors.append("max_input_age_seconds_must_be_positive")
    if data_ttl > max_age:
        errors.append("data_cache_ttl_cannot_exceed_freshness_window")
    if data_entries <= 0 or resource_entries <= 0:
        errors.append("cache_max_entries_must_be_positive")
    if policy.get("block_on_stale") is not True:
        errors.append("block_on_stale_must_be_true")
    if set(policy.get("tracked_files", [])) != set(TRACKED_INPUT_FILES):
        errors.append("tracked_files_must_match_app_inputs")
    if seconds_between(policy.get("source_snapshot_utc", ""), policy.get("checked_at_utc", "")) is None:
        errors.append("freshness_timestamps_must_be_iso_utc")
    return sorted(errors)


def audit_cache_state_package(
    *,
    output_dir: str | Path,
    cache_state_contract: dict[str, Any] | None = None,
    freshness_policy: dict[str, Any] | None = None,
    output_entries: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    output_path = Path(output_dir)
    contract = normalize_cache_state_contract(
        cache_state_contract if cache_state_contract is not None else read_json(output_path / "cache_state_contract.json")
    )
    policy = normalize_freshness_policy(
        freshness_policy if freshness_policy is not None else read_json(output_path / "freshness_policy.json")
    )
    checks: list[dict[str, Any]] = []

    missing_app_files = sorted(relative for relative in REQUIRED_APP_FILES if not (output_path / relative).is_file())
    checks.append(
        check(
            "source_streamlit_app_bundle_is_complete",
            not missing_app_files,
            observed=missing_app_files,
            expected=REQUIRED_APP_FILES,
            message="Cache/state layer must wrap the checked Streamlit app bundle from 17/06.",
        )
    )

    app_audit = read_json(output_path / "app_audit.json") if (output_path / "app_audit.json").is_file() else {}
    checks.append(
        check(
            "upstream_app_audit_is_valid",
            bool(app_audit.get("valid")),
            observed=app_audit.get("summary", {}).get("blocking_errors", []),
            expected=[],
            message="Do not add cache/state behavior to a blocked app package.",
        )
    )

    cache_errors = required_cache_function_errors(contract)
    invalidation = contract.get("invalidation_policy", {})
    freshness_panel = contract.get("freshness_panel", {})
    checks.append(
        check(
            "cache_state_contract_declares_data_resource_session_and_invalidation",
            not cache_errors
            and freshness_panel.get("required") is True
            and freshness_panel.get("disable_download_when_stale") is True
            and invalidation.get("checksum_invalidation_required") is True
            and invalidation.get("manual_cache_clear_required") is True
            and invalidation.get("reset_session_state_on_input_digest_change") is True,
            observed={"cache_errors": cache_errors, "freshness_panel": freshness_panel, "invalidation": invalidation},
            expected="data cache, resource cache, session state, checksum invalidation and manual clear",
            message="Cache/state behavior is part of the delivery contract, not an implementation detail.",
        )
    )

    state_errors = session_state_errors(contract)
    checks.append(
        check(
            "session_state_keys_are_session_scoped_and_non_sensitive",
            not state_errors,
            observed=state_errors,
            expected=REQUIRED_SESSION_STATE_KEYS,
            message="Session state should store only per-session UI choices and input digest markers.",
        )
    )

    policy_errors = freshness_policy_errors(policy)
    checks.append(
        check(
            "freshness_policy_defines_ttl_max_entries_and_stale_gate",
            not policy_errors,
            observed=policy_errors,
            expected="positive TTLs, bounded entries, tracked files and stale gate",
            message="TTL and freshness windows must be explicit and machine-checkable.",
        )
    )

    report_path = output_path / "freshness_report.json"
    freshness_report = read_json(report_path) if report_path.is_file() else {}
    current_report = build_freshness_report(output_path, policy)
    checks.append(
        check(
            "freshness_report_matches_current_input_checksums",
            freshness_report.get("input_digest") == current_report["input_digest"]
            and not current_report.get("missing_inputs"),
            observed={
                "stored": freshness_report.get("input_digest"),
                "current": current_report["input_digest"],
                "missing_inputs": current_report.get("missing_inputs", []),
            },
            expected="freshness report digest over current tracked app inputs",
            message="Checksum parameters should invalidate cache when app inputs change.",
        )
    )
    checks.append(
        check(
            "freshness_report_is_not_stale",
            bool(freshness_report.get("valid")) and not freshness_report.get("stale"),
            observed=freshness_report.get("stale_reasons", []),
            expected=[],
            message="A stale app can show diagnostics, but it is not ready for decision delivery.",
        )
    )

    app_path = output_path / "streamlit_app.py"
    app_source = app_path.read_text(encoding="utf-8") if app_path.is_file() else ""
    missing_markers = [marker for marker in REQUIRED_SOURCE_MARKERS if marker not in app_source]
    checks.append(
        check(
            "generated_app_uses_streamlit_cache_state_and_freshness_panel",
            app_path.is_file() and not missing_markers,
            observed=missing_markers,
            expected=REQUIRED_SOURCE_MARKERS,
            message="The app must expose cache, session state, manual refresh and stale-download behavior.",
        )
    )

    checksum_markers = [
        "def load_csv_cached(path_text: str, checksum: str)",
        "def load_json_cached(path_text: str, checksum: str)",
        "def load_figure_resource(path_text: str, checksum: str)",
        "checksum_for(freshness_report, \"app_data/metric_summary.csv\")",
        "checksum_for(freshness_report, \"app_data/plotly_figure_spec.json\")",
    ]
    missing_checksum_markers = [marker for marker in checksum_markers if marker not in app_source]
    checks.append(
        check(
            "cached_loaders_use_checksum_parameters_for_invalidation",
            not missing_checksum_markers,
            observed=missing_checksum_markers,
            expected=checksum_markers,
            message="Cache keys must include file checksums, not only file paths.",
        )
    )

    stale_markers = [
        "st.sidebar.warning",
        "st.error(\"This app is using stale inputs",
        "disabled=freshness_report[\"stale\"]",
    ]
    missing_stale_markers = [marker for marker in stale_markers if marker not in app_source]
    checks.append(
        check(
            "stale_outputs_warn_and_disable_downloads",
            not missing_stale_markers,
            observed=missing_stale_markers,
            expected=stale_markers,
            message="Stale inputs should be visible and should not ship a fresh-looking download.",
        )
    )

    forbidden_patterns = [pattern for pattern in FORBIDDEN_APP_PATTERNS if pattern in app_source]
    checks.append(
        check(
            "cached_app_source_avoids_forbidden_runtime_patterns",
            not forbidden_patterns,
            observed=forbidden_patterns,
            expected=[],
            message="Freshness lesson still avoids network, secrets, SQL recompute and disk-persisted caches.",
        )
    )

    if output_entries is not None:
        missing_hashes = sorted(key for key, value in output_entries.items() if len(value.get("sha256", "")) != 64)
    else:
        missing_hashes = ["not_provided"]
    checks.append(
        check(
            "manifest_hashes_cache_state_outputs",
            not missing_hashes,
            observed=missing_hashes,
            expected=[],
            message="The enhanced app, cache contract, freshness report and audit need checksums.",
        )
    )

    blockers = [item["id"] for item in checks if not item["valid"] and item["severity"] == "block"]
    warnings = [item["id"] for item in checks if not item["valid"] and item["severity"] == "warn"]
    return {
        "version": CACHE_STATE_VERSION,
        "cache_state_id": contract.get("cache_state_id"),
        "valid": not blockers,
        "readiness_status": "blocked" if blockers else ("ready_with_warnings" if warnings else "ready"),
        "summary": {
            "blocking_errors": blockers,
            "warnings": warnings,
            "check_count": len(checks),
        },
        "checks": checks,
    }


def build_cache_state_package(
    *,
    app_dir: str | Path,
    output_dir: str | Path,
    cache_state_contract_path: str | Path | None = None,
    freshness_policy_path: str | Path | None = None,
    source_snapshot_utc: str | None = None,
    checked_at_utc: str | None = None,
) -> CacheStateBuildResult:
    source_app_dir = Path(app_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    copy_app_bundle(source_app_dir, output_path)

    contract = normalize_cache_state_contract(read_json(cache_state_contract_path) if cache_state_contract_path else None)
    policy = normalize_freshness_policy(
        read_json(freshness_policy_path) if freshness_policy_path else None,
        source_snapshot_utc=source_snapshot_utc,
        checked_at_utc=checked_at_utc,
    )

    app_path = output_path / "streamlit_app.py"
    contract_path = output_path / "cache_state_contract.json"
    policy_path = output_path / "freshness_policy.json"
    report_path = output_path / "freshness_report.json"
    runbook_path = output_path / "cache_state_runbook.md"
    audit_path = output_path / "cache_state_audit.json"
    manifest_path = output_path / "cache_state_manifest.json"

    write_json(contract_path, contract)
    write_json(policy_path, policy)
    write_json(report_path, build_freshness_report(output_path, policy))
    app_path.write_text(render_cache_state_app_source(), encoding="utf-8")
    runbook_path.write_text(cache_state_runbook(), encoding="utf-8")

    output_entries = {
        "streamlit_app": manifest_entry(app_path, start=output_path),
        "cache_state_contract": manifest_entry(contract_path, start=output_path),
        "freshness_policy": manifest_entry(policy_path, start=output_path),
        "freshness_report": manifest_entry(report_path, start=output_path),
        "cache_state_runbook": manifest_entry(runbook_path, start=output_path),
        **{
            f"app_{relative.replace('/', '_').replace('.', '_')}": optional_manifest_entry(
                output_path / relative,
                start=output_path,
            )
            for relative in REQUIRED_APP_FILES
        },
    }
    audit = audit_cache_state_package(
        output_dir=output_path,
        cache_state_contract=contract,
        freshness_policy=policy,
        output_entries=output_entries,
    )
    write_json(audit_path, audit)
    output_entries["cache_state_audit"] = manifest_entry(audit_path, start=output_path)

    manifest = {
        "version": CACHE_STATE_VERSION,
        "cache_state_id": contract.get("cache_state_id"),
        "hash_algorithm": "sha256",
        "renderer_used": "streamlit_cache_state_auditor",
        "streamlit_version": streamlit.__version__,
        "source_app_dir": relpath(source_app_dir, start=output_path),
        "inputs": {
            "source_app_manifest": optional_manifest_entry(source_app_dir / "app_manifest.json", start=output_path),
            "source_app_audit": optional_manifest_entry(source_app_dir / "app_audit.json", start=output_path),
            "cache_state_contract_input": optional_manifest_entry(Path(cache_state_contract_path), start=output_path)
            if cache_state_contract_path
            else manifest_entry(contract_path, start=output_path),
            "freshness_policy_input": optional_manifest_entry(Path(freshness_policy_path), start=output_path)
            if freshness_policy_path
            else manifest_entry(policy_path, start=output_path),
        },
        "outputs": output_entries,
    }
    write_json(manifest_path, manifest)

    return CacheStateBuildResult(
        output_dir=output_path,
        app_path=app_path,
        cache_state_contract_path=contract_path,
        freshness_policy_path=policy_path,
        freshness_report_path=report_path,
        audit_path=audit_path,
        manifest_path=manifest_path,
        audit=audit,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Add cache/state/freshness checks to a 17/06 Streamlit app bundle.")
    parser.add_argument("--app-dir", type=Path, help="Path to the 17/06 Streamlit app bundle.")
    parser.add_argument("--cache-state-contract", type=Path, help="Optional cache_state_contract.json.")
    parser.add_argument("--freshness-policy", type=Path, help="Optional freshness_policy.json.")
    parser.add_argument("--output-dir", type=Path, required=True, help="Directory for the enhanced app bundle.")
    parser.add_argument("--write-example", type=Path, help="Write a sample 17/06 app before adding cache/state.")
    parser.add_argument("--source-snapshot-at", help="Override source snapshot UTC timestamp.")
    parser.add_argument("--checked-at", help="Override freshness check UTC timestamp.")
    parser.add_argument("--fail-on-invalid", action="store_true", help="Return exit code 2 when cache/state audit blocks delivery.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    app_dir = args.app_dir
    contract_path = args.cache_state_contract
    policy_path = args.freshness_policy
    if args.write_example:
        sample = write_sample_cache_state_inputs(args.write_example)
        app_dir = sample["app_dir"]
        if contract_path is None:
            contract_path = sample["cache_state_contract_path"]
        if policy_path is None:
            policy_path = sample["freshness_policy_path"]
    if app_dir is None:
        raise SystemExit("missing required argument: --app-dir or --write-example")

    result = build_cache_state_package(
        app_dir=app_dir,
        output_dir=args.output_dir,
        cache_state_contract_path=contract_path,
        freshness_policy_path=policy_path,
        source_snapshot_utc=args.source_snapshot_at,
        checked_at_utc=args.checked_at,
    )
    response = {
        "valid": result.audit["valid"],
        "readiness_status": result.audit["readiness_status"],
        "blocking_errors": result.audit["summary"]["blocking_errors"],
        "app": str(result.app_path),
        "freshness_report": str(result.freshness_report_path),
        "manifest": str(result.manifest_path),
    }
    print(json.dumps(response, ensure_ascii=False, indent=2, sort_keys=True))
    if args.fail_on_invalid and not result.audit["valid"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
