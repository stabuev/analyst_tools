from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


API_VERSION = "1.0.0"
DEFAULT_PACKAGE_NAME = "fastapi-delivery-api"
API_EXIT_CODE_POLICY = {
    "success": 0,
    "api_contract_block": 2,
    "upstream_package_block": 10,
    "system_error": 30,
}
REQUIRED_ROUTE_PATHS = ["/health", "/summary", "/runs", "/runs/{run_id}", "/artifacts/manifest"]
REQUIRED_RESPONSE_MODELS = [
    "HealthResponse",
    "SummaryResponse",
    "RunHistoryRow",
    "ManifestSummary",
]
REQUIRED_SOURCE_MARKERS = [
    "from fastapi import FastAPI, HTTPException, Path as PathParam, Query",
    "from pydantic import BaseModel, ConfigDict, Field",
    "app = FastAPI(",
    "@app.get(\"/health\", response_model=HealthResponse)",
    "@app.get(\"/summary\", response_model=SummaryResponse)",
    "@app.get(\"/runs\", response_model=list[RunHistoryRow])",
    "@app.get(\"/runs/{run_id}\", response_model=RunHistoryRow)",
    "@app.get(\"/artifacts/manifest\", response_model=ManifestSummary)",
    "API_DATA_DIR = Path(__file__).with_name(\"api_data\")",
]
FORBIDDEN_SOURCE_MARKERS = [
    "@app.post",
    "@app.put",
    "@app.patch",
    "@app.delete",
    "BackgroundTasks",
    "requests.",
    "urllib.",
    "subprocess",
    "os.environ",
    ".write_text(",
    ".write_bytes(",
    ".unlink(",
    ".mkdir(",
]
REQUIRED_SCHEDULED_PACKAGE_FILES = {
    "schedule_run_report.json": "schedule_run_report.json",
    "schedule_freshness_report.json": "schedule_freshness_report.json",
    "run_history.csv": "run_history.csv",
    "last_success_marker.json": "last_success_marker.json",
    "scheduled_publish_manifest.json": "scheduled_publish_manifest.json",
    "published-delivery/cli_run_report.json": "delivery_cli_run_report.json",
    "published-delivery/cli_publish_manifest.json": "delivery_cli_publish_manifest.json",
    "published-delivery/freshness_report.json": "delivery_freshness_report.json",
}


@dataclass(frozen=True)
class FastAPIEndpointResult:
    status: str
    valid: bool
    output_dir: Path
    package_dir: Path
    api_path: Path
    contract_path: Path
    openapi_schema_path: Path
    contract_tests_path: Path
    audit_path: Path
    manifest_path: Path
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


def load_scheduled_workflow():
    current = Path(__file__).resolve()
    workflow_path = current.parents[2] / "09-scheduled-runs" / "outputs" / "scheduled_delivery_workflow.py"
    spec = importlib.util.spec_from_file_location("scheduled_delivery_workflow_for_fastapi", workflow_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load scheduled workflow: {workflow_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def default_api_contract() -> dict[str, Any]:
    return {
        "api_id": "trial-onboarding-delivery-read-only-api",
        "title": "Trial onboarding delivery read-only API",
        "version": API_VERSION,
        "description": "Optional read-only FastAPI wrapper for the scheduled delivery package.",
        "source_package": {
            "expected_renderer": "scheduled_delivery_workflow",
            "expected_status": "success",
            "required_files": sorted(REQUIRED_SCHEDULED_PACKAGE_FILES),
        },
        "read_only_boundary": {
            "allowed_methods": ["GET"],
            "forbidden_methods": ["POST", "PUT", "PATCH", "DELETE"],
            "no_source_mutation": True,
            "no_background_jobs": True,
            "no_network_calls": True,
            "cli_fallback_required": True,
        },
        "routes": [
            {
                "path": "/health",
                "method": "GET",
                "operation_id": "get_health",
                "response_model": "HealthResponse",
                "purpose": "Expose delivery status, freshness and last-success marker.",
            },
            {
                "path": "/summary",
                "method": "GET",
                "operation_id": "get_summary",
                "response_model": "SummaryResponse",
                "purpose": "Return the stakeholder-facing status summary from shipped artifacts.",
            },
            {
                "path": "/runs",
                "method": "GET",
                "operation_id": "list_runs",
                "query_parameters": [
                    {
                        "name": "status",
                        "type": "string",
                        "required": False,
                        "description": "Optional exact status filter for run history.",
                    }
                ],
                "response_model": "list[RunHistoryRow]",
                "purpose": "Return immutable scheduled run history rows.",
            },
            {
                "path": "/runs/{run_id}",
                "method": "GET",
                "operation_id": "get_run",
                "path_parameters": [
                    {"name": "run_id", "type": "string", "required": True, "min_length": 1}
                ],
                "response_model": "RunHistoryRow",
                "not_found_status": 404,
                "purpose": "Return one run row or a clear 404 if the run id is unknown.",
            },
            {
                "path": "/artifacts/manifest",
                "method": "GET",
                "operation_id": "get_manifest",
                "response_model": "ManifestSummary",
                "purpose": "Expose checksum manifest metadata without serving mutable files.",
            },
        ],
        "schemas": {
            "HealthResponse": ["api_id", "status", "schedule_id", "run_id", "freshness_state", "last_success_utc"],
            "SummaryResponse": ["schedule_id", "run_id", "status", "exit_code", "blocking_errors"],
            "RunHistoryRow": ["run_id", "scheduled_for_utc", "status", "exit_code", "published"],
            "ManifestSummary": ["renderer_used", "status", "input_count", "output_count", "hash_algorithm"],
        },
        "cli_fallback": {
            "required": True,
            "artifact": "scheduled-delivery-workflow",
            "command": (
                "uv run --locked python phases/17-delivery/09-scheduled-runs/outputs/"
                "scheduled_delivery_workflow.py --write-example /tmp/scheduled-delivery-example "
                "--output-dir /tmp/scheduled-delivery-package"
            ),
            "reason": "The API is an optional interface; report/workbook/CLI delivery remains reproducible.",
        },
    }


def normalize_api_contract(contract: dict[str, Any] | None) -> dict[str, Any]:
    normalized = default_api_contract()
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


def api_contract_errors(contract: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not contract.get("api_id"):
        errors.append("api_id_required")
    boundary = contract.get("read_only_boundary", {})
    if boundary.get("allowed_methods") != ["GET"]:
        errors.append("allowed_methods_must_be_get_only")
    if not boundary.get("no_source_mutation"):
        errors.append("no_source_mutation_required")
    if not boundary.get("no_background_jobs"):
        errors.append("no_background_jobs_required")
    if not boundary.get("no_network_calls"):
        errors.append("no_network_calls_required")
    if not boundary.get("cli_fallback_required"):
        errors.append("cli_fallback_required")
    routes = contract.get("routes", [])
    if not routes:
        errors.append("routes_required")
    paths = [route.get("path") for route in routes]
    if sorted(paths) != sorted(set(paths)):
        errors.append("route_paths_must_be_unique")
    for required_path in REQUIRED_ROUTE_PATHS:
        if required_path not in paths:
            errors.append(f"missing_required_route:{required_path}")
    for route in routes:
        if route.get("method") != "GET":
            errors.append(f"route_method_must_be_get:{route.get('path', '')}")
        if not route.get("response_model"):
            errors.append(f"response_model_required:{route.get('path', '')}")
    run_detail = next((route for route in routes if route.get("path") == "/runs/{run_id}"), {})
    path_parameters = run_detail.get("path_parameters", [])
    if not any(parameter.get("name") == "run_id" for parameter in path_parameters):
        errors.append("run_id_path_parameter_required")
    if run_detail.get("not_found_status") != 404:
        errors.append("run_detail_must_document_404")
    fallback = contract.get("cli_fallback", {})
    if not fallback.get("required"):
        errors.append("cli_fallback_required_flag_missing")
    command = fallback.get("command", "")
    if "scheduled_delivery_workflow.py" not in command or "--output-dir" not in command:
        errors.append("cli_fallback_must_reference_scheduled_workflow_and_output_dir")
    return errors


def source_marker_errors(source_text: str) -> list[str]:
    return [marker for marker in REQUIRED_SOURCE_MARKERS if marker not in source_text]


def forbidden_source_markers(source_text: str) -> list[str]:
    return [marker for marker in FORBIDDEN_SOURCE_MARKERS if marker in source_text]


def read_history_rows(history_path: Path) -> list[dict[str, str]]:
    if not history_path.is_file():
        return []
    with history_path.open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def scheduled_package_errors(scheduled_package_dir: str | Path) -> list[str]:
    package_dir = Path(scheduled_package_dir)
    errors: list[str] = []
    if not package_dir.is_dir():
        return ["scheduled_package_dir_missing"]
    for relative in REQUIRED_SCHEDULED_PACKAGE_FILES:
        if not (package_dir / relative).is_file():
            errors.append(f"missing_scheduled_package_file:{relative}")
    run_report_path = package_dir / "schedule_run_report.json"
    if run_report_path.is_file():
        report = read_json(run_report_path)
        if report.get("status") != "success":
            errors.append("scheduled_run_status_must_be_success")
        blocking = report.get("summary", {}).get("blocking_errors", [])
        if blocking:
            errors.append("scheduled_run_report_has_blocking_errors")
    manifest_path = package_dir / "scheduled_publish_manifest.json"
    if manifest_path.is_file():
        manifest = read_json(manifest_path)
        if manifest.get("renderer_used") != "scheduled_delivery_workflow":
            errors.append("scheduled_manifest_renderer_must_be_scheduled_delivery_workflow")
        if manifest.get("status") != "success":
            errors.append("scheduled_manifest_status_must_be_success")
    freshness_path = package_dir / "schedule_freshness_report.json"
    if freshness_path.is_file():
        freshness = read_json(freshness_path)
        if freshness.get("freshness_state") != "fresh":
            errors.append("schedule_freshness_state_must_be_fresh")
        if not freshness.get("last_success_marker_present"):
            errors.append("last_success_marker_must_be_present")
    history_rows = read_history_rows(package_dir / "run_history.csv")
    if not history_rows:
        errors.append("run_history_must_have_at_least_one_attempt")
    return errors


def copy_api_data(scheduled_package_dir: Path, api_data_dir: Path) -> dict[str, dict[str, Any]]:
    api_data_dir.mkdir(parents=True, exist_ok=True)
    copied: dict[str, dict[str, Any]] = {}
    for source_relative, destination_name in REQUIRED_SCHEDULED_PACKAGE_FILES.items():
        source = scheduled_package_dir / source_relative
        destination = api_data_dir / destination_name
        if source.is_file():
            shutil.copy2(source, destination)
            copied[destination_name] = {
                "source": source_relative,
                "path": destination.name,
                "sha256": sha256_file(destination),
                "bytes": destination.stat().st_size,
            }
        else:
            copied[destination_name] = {
                "source": source_relative,
                "path": destination.name,
                "missing": True,
                "sha256": "",
                "bytes": 0,
            }
    return copied


def build_api_source(contract: dict[str, Any]) -> str:
    title = contract.get("title", default_api_contract()["title"])
    description = contract.get("description", default_api_contract()["description"])
    api_id = contract.get("api_id", default_api_contract()["api_id"])
    fallback = contract.get("cli_fallback", default_api_contract()["cli_fallback"])
    fallback_command = fallback.get("command", "")
    return f'''from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Path as PathParam, Query
from pydantic import BaseModel, ConfigDict, Field


API_ID = {api_id!r}
API_VERSION = {API_VERSION!r}
CLI_FALLBACK_COMMAND = {fallback_command!r}
API_DATA_DIR = Path(__file__).with_name("api_data")

app = FastAPI(
    title={title!r},
    version=API_VERSION,
    description={description!r},
)


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_id: str = Field(description="Stable optional API identifier.")
    status: str = Field(description="Scheduled delivery status.")
    schedule_id: str = Field(description="Upstream schedule identifier.")
    run_id: str = Field(description="Current scheduled run id.")
    freshness_state: str = Field(description="Freshness state from the scheduled package.")
    last_success_utc: str | None = Field(default=None, description="Last fresh successful publish timestamp.")
    stale: bool = Field(description="Whether the shipped result is stale for API consumers.")
    cli_fallback: str = Field(description="Reproducible non-API delivery command.")


class SummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schedule_id: str
    run_id: str
    status: str
    exit_code: int
    freshness_state: str
    published: bool
    delivery_status: str
    delivery_published: bool
    blocking_errors: list[str]
    artifact_count: int
    cli_fallback: str


class RunHistoryRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    scheduled_for_utc: str
    started_at_utc: str
    finished_at_utc: str
    status: str
    exit_code: int
    published: bool
    freshness_state: str
    notification_sent: bool
    last_success_utc: str
    cli_report_path: str
    cli_manifest_path: str


class ManifestSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    renderer_used: str
    status: str
    input_count: int
    output_count: int
    hash_algorithm: str
    manifest_sha256: str


def read_json(name: str) -> dict[str, Any]:
    return json.loads((API_DATA_DIR / name).read_text(encoding="utf-8"))


def read_history_rows() -> list[dict[str, str]]:
    with (API_DATA_DIR / "run_history.csv").open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def parse_bool(value: Any) -> bool:
    return str(value).strip().lower() == "true"


def row_model(row: dict[str, str]) -> RunHistoryRow:
    return RunHistoryRow(
        run_id=row.get("run_id", ""),
        scheduled_for_utc=row.get("scheduled_for_utc", ""),
        started_at_utc=row.get("started_at_utc", ""),
        finished_at_utc=row.get("finished_at_utc", ""),
        status=row.get("status", ""),
        exit_code=int(row.get("exit_code") or 0),
        published=parse_bool(row.get("published")),
        freshness_state=row.get("freshness_state", ""),
        notification_sent=parse_bool(row.get("notification_sent")),
        last_success_utc=row.get("last_success_utc", ""),
        cli_report_path=row.get("cli_report_path", ""),
        cli_manifest_path=row.get("cli_manifest_path", ""),
    )


@app.get("/health", response_model=HealthResponse)
def get_health() -> HealthResponse:
    run_report = read_json("schedule_run_report.json")
    freshness = read_json("schedule_freshness_report.json")
    marker = read_json("last_success_marker.json")
    freshness_state = str(freshness.get("freshness_state", "unknown"))
    return HealthResponse(
        api_id=API_ID,
        status=str(run_report.get("status", "")),
        schedule_id=str(run_report.get("schedule_id", "")),
        run_id=str(run_report.get("run_id", "")),
        freshness_state=freshness_state,
        last_success_utc=marker.get("last_success_utc"),
        stale=freshness_state != "fresh",
        cli_fallback=CLI_FALLBACK_COMMAND,
    )


@app.get("/summary", response_model=SummaryResponse)
def get_summary() -> SummaryResponse:
    run_report = read_json("schedule_run_report.json")
    freshness = read_json("schedule_freshness_report.json")
    manifest = read_json("scheduled_publish_manifest.json")
    delivery = run_report.get("delivery_cli", {{}})
    return SummaryResponse(
        schedule_id=str(run_report.get("schedule_id", "")),
        run_id=str(run_report.get("run_id", "")),
        status=str(run_report.get("status", "")),
        exit_code=int(run_report.get("exit_code", 0)),
        freshness_state=str(freshness.get("freshness_state", "unknown")),
        published=bool(delivery.get("published")),
        delivery_status=str(delivery.get("status", "")),
        delivery_published=bool(delivery.get("published")),
        blocking_errors=list(run_report.get("summary", {{}}).get("blocking_errors", [])),
        artifact_count=len(manifest.get("outputs", {{}})),
        cli_fallback=CLI_FALLBACK_COMMAND,
    )


@app.get("/runs", response_model=list[RunHistoryRow])
def list_runs(
    status: str | None = Query(
        default=None,
        min_length=1,
        pattern="^(success|schedule_contract_block|data_quality_block|freshness_warning|system_error)$",
    ),
) -> list[RunHistoryRow]:
    rows = [row_model(row) for row in read_history_rows()]
    if status is not None:
        rows = [row for row in rows if row.status == status]
    return rows


@app.get("/runs/{{run_id}}", response_model=RunHistoryRow)
def get_run(run_id: str = PathParam(..., min_length=1)) -> RunHistoryRow:
    for row in read_history_rows():
        if row.get("run_id") == run_id:
            return row_model(row)
    raise HTTPException(status_code=404, detail=f"run_id not found: {{run_id}}")


@app.get("/artifacts/manifest", response_model=ManifestSummary)
def get_manifest() -> ManifestSummary:
    manifest_path = API_DATA_DIR / "scheduled_publish_manifest.json"
    manifest = read_json("scheduled_publish_manifest.json")
    return ManifestSummary(
        renderer_used=str(manifest.get("renderer_used", "")),
        status=str(manifest.get("status", "")),
        input_count=len(manifest.get("inputs", {{}})),
        output_count=len(manifest.get("outputs", {{}})),
        hash_algorithm=str(manifest.get("hash_algorithm", "")),
        manifest_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
    )
'''


def load_generated_api(api_path: Path):
    module_name = f"generated_fastapi_delivery_api_{hashlib.sha1(str(api_path).encode()).hexdigest()}"
    spec = importlib.util.spec_from_file_location(module_name, api_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load generated API: {api_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def openapi_schema_errors(openapi_schema: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    paths = openapi_schema.get("paths", {})
    for required_path in REQUIRED_ROUTE_PATHS:
        if required_path not in paths:
            errors.append(f"openapi_missing_path:{required_path}")
    for path, operations in paths.items():
        api_methods = [method for method in operations if method.lower() in {"get", "post", "put", "patch", "delete"}]
        for method in api_methods:
            if method.lower() != "get":
                errors.append(f"openapi_method_must_be_get:{path}:{method}")
    schemas = openapi_schema.get("components", {}).get("schemas", {})
    for model in REQUIRED_RESPONSE_MODELS:
        if model not in schemas:
            errors.append(f"openapi_missing_schema:{model}")
    run_detail_parameters = paths.get("/runs/{run_id}", {}).get("get", {}).get("parameters", [])
    if not any(parameter.get("name") == "run_id" and parameter.get("in") == "path" for parameter in run_detail_parameters):
        errors.append("openapi_run_id_path_parameter_required")
    return errors


def run_runtime_contract_tests(api_path: Path) -> list[dict[str, Any]]:
    try:
        from fastapi.testclient import TestClient

        module = load_generated_api(api_path)
        client = TestClient(module.app, raise_server_exceptions=False)
        health = client.get("/health")
        summary = client.get("/summary")
        runs = client.get("/runs")
        unknown = client.get("/runs/not-a-real-run-id")
        invalid_query = client.get("/runs", params={"status": "not-a-status"})
        run_detail_status = 404
        if runs.status_code == 200 and runs.json():
            run_id = runs.json()[0]["run_id"]
            run_detail_status = client.get(f"/runs/{run_id}").status_code
        return [
            check(
                "runtime_health_returns_200",
                health.status_code == 200 and health.json().get("freshness_state") == "fresh",
                observed={"status_code": health.status_code, "body": health.text[:300]},
                expected="GET /health returns fresh scheduled delivery status",
            ),
            check(
                "runtime_summary_returns_delivery_status",
                summary.status_code == 200 and summary.json().get("delivery_status") == "success",
                observed={"status_code": summary.status_code, "body": summary.text[:300]},
                expected="GET /summary returns success delivery status",
            ),
            check(
                "runtime_runs_returns_history_rows",
                runs.status_code == 200 and bool(runs.json()),
                observed={"status_code": runs.status_code, "body": runs.text[:300]},
                expected="GET /runs returns non-empty run history",
            ),
            check(
                "runtime_known_run_returns_200",
                run_detail_status == 200,
                observed=run_detail_status,
                expected="known run id returns one row",
            ),
            check(
                "runtime_unknown_run_returns_404",
                unknown.status_code == 404,
                observed={"status_code": unknown.status_code, "body": unknown.text[:300]},
                expected="unknown run id returns 404",
            ),
            check(
                "runtime_invalid_query_returns_validation_error",
                invalid_query.status_code == 422,
                observed={"status_code": invalid_query.status_code, "body": invalid_query.text[:300]},
                expected="empty status query is rejected by FastAPI validation",
            ),
        ]
    except Exception as error:
        return [
            check(
                "runtime_contract_tests_import_and_execute",
                False,
                observed=str(error),
                expected="generated FastAPI app imports and TestClient can call endpoints",
            )
        ]


def build_cli_fallback_doc(contract: dict[str, Any]) -> str:
    fallback = contract["cli_fallback"]
    return f"""# CLI fallback

This FastAPI interface is optional. The reproducible delivery path remains the scheduled
workflow and CLI package.

```bash
{fallback["command"]}
```

Use the API only as a read-only view over files already shipped by the delivery workflow.
If the API is unavailable, rerun the command above and hand over the package artifacts.
"""


def build_api_contract_tests(contract: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": API_VERSION,
        "api_id": contract["api_id"],
        "tests": [
            {
                "id": "contract_all_routes_are_get",
                "expected": "Every declared route uses GET and maps to a response model.",
                "source": "api_contract.json",
            },
            {
                "id": "openapi_schema_matches_contract",
                "expected": "OpenAPI contains required paths and Pydantic schemas.",
                "source": "openapi_schema.json",
            },
            {
                "id": "runtime_invalid_inputs_are_visible",
                "expected": "Unknown run id returns 404; invalid query parameter returns 422.",
                "source": "fastapi.testclient",
            },
            {
                "id": "read_only_boundary_has_no_mutating_methods",
                "expected": "No POST/PUT/PATCH/DELETE decorators and no source mutation patterns.",
                "source": "api.py",
            },
            {
                "id": "cli_fallback_remains_reproducible",
                "expected": "CLI fallback document names scheduled_delivery_workflow.py and --output-dir.",
                "source": "cli_fallback.md",
            },
        ],
    }


def collect_output_entries(root: Path) -> dict[str, dict[str, Any]]:
    entries: dict[str, dict[str, Any]] = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = relpath(path, start=root)
        if relative == "api_manifest.json":
            continue
        key = relative.replace("/", "_").replace(".", "_").replace("-", "_")
        entries[key] = manifest_entry(path, start=root)
    return entries


def build_api_manifest(
    *,
    package_dir: Path,
    scheduled_package_dir: Path,
    api_contract_input_path: Path | None,
    status: str,
    valid: bool,
) -> dict[str, Any]:
    return {
        "version": API_VERSION,
        "renderer_used": "fastapi_delivery_endpoint",
        "status": status,
        "valid": valid,
        "hash_algorithm": "sha256",
        "inputs": {
            "scheduled_publish_manifest": optional_manifest_entry(
                scheduled_package_dir / "scheduled_publish_manifest.json",
                start=package_dir,
            ),
            "api_contract_input": optional_manifest_entry(api_contract_input_path, start=package_dir),
        },
        "outputs": collect_output_entries(package_dir),
    }


def build_fastapi_delivery_endpoint(
    *,
    scheduled_package_dir: str | Path,
    output_dir: str | Path,
    api_contract_path: str | Path | None = None,
    overwrite: bool = True,
) -> FastAPIEndpointResult:
    output_path = Path(output_dir).resolve()
    package_dir = output_path / DEFAULT_PACKAGE_NAME
    if package_dir.exists() and overwrite:
        shutil.rmtree(package_dir)
    if package_dir.exists():
        raise FileExistsError(f"output package already exists: {package_dir}")
    package_dir.mkdir(parents=True, exist_ok=True)
    api_data_dir = package_dir / "api_data"

    scheduled_path = Path(scheduled_package_dir).resolve()
    input_contract_path = Path(api_contract_path).resolve() if api_contract_path else None
    contract = normalize_api_contract(read_json(input_contract_path) if input_contract_path else None)
    contract_errors = api_contract_errors(contract)
    package_errors = scheduled_package_errors(scheduled_path)

    copied_data = copy_api_data(scheduled_path, api_data_dir)
    api_path = package_dir / "api.py"
    contract_path = package_dir / "api_contract.json"
    openapi_path = package_dir / "openapi_schema.json"
    contract_tests_path = package_dir / "api_contract_tests.json"
    audit_path = package_dir / "api_audit.json"
    manifest_path = package_dir / "api_manifest.json"
    fallback_path = package_dir / "cli_fallback.md"

    write_json(contract_path, contract)
    write_text(api_path, build_api_source(contract))
    write_text(fallback_path, build_cli_fallback_doc(contract))
    write_json(contract_tests_path, build_api_contract_tests(contract))

    source_text = api_path.read_text(encoding="utf-8")
    marker_errors = source_marker_errors(source_text)
    forbidden_markers = forbidden_source_markers(source_text)
    try:
        openapi_schema = load_generated_api(api_path).app.openapi()
        write_json(openapi_path, openapi_schema)
        openapi_errors = openapi_schema_errors(openapi_schema)
    except Exception as error:
        openapi_schema = {}
        write_json(openapi_path, {"error": str(error)})
        openapi_errors = [f"openapi_generation_failed:{error}"]

    runtime_tests = run_runtime_contract_tests(api_path)
    fallback_text = fallback_path.read_text(encoding="utf-8")
    data_missing = [name for name, payload in copied_data.items() if payload.get("missing")]
    checks = [
        check(
            "scheduled_package_has_successful_run_and_required_files",
            not package_errors and not data_missing,
            observed={"package_errors": package_errors, "missing_api_data": data_missing},
            expected="success scheduled package with run report, freshness, history, marker and manifests",
            message="The API must be a view over a shipped package, not a substitute for the delivery workflow.",
        ),
        check(
            "api_contract_declares_read_only_routes_and_cli_fallback",
            not contract_errors,
            observed=contract_errors,
            expected="GET-only routes, response models and scheduled workflow CLI fallback",
            message="FastAPI is optional delivery surface; mutation and server-only delivery are out of scope.",
        ),
        check(
            "generated_api_uses_fastapi_pydantic_and_response_models",
            not marker_errors,
            observed=marker_errors,
            expected=REQUIRED_SOURCE_MARKERS,
            message="The endpoint should use FastAPI decorators and Pydantic response models explicitly.",
        ),
        check(
            "read_only_source_boundary_has_no_mutating_or_secret_network_patterns",
            not forbidden_markers,
            observed=forbidden_markers,
            expected="no mutating decorators, writes, background tasks, network calls or env access",
            message="A read-only API should not become a hidden ETL job or secret-dependent service.",
        ),
        check(
            "openapi_schema_has_required_get_paths_and_models",
            not openapi_errors,
            observed=openapi_errors,
            expected={"paths": REQUIRED_ROUTE_PATHS, "schemas": REQUIRED_RESPONSE_MODELS},
            message="OpenAPI is the API contract that clients and reviewers can inspect.",
        ),
        check(
            "cli_fallback_document_is_present_and_reproducible",
            "scheduled_delivery_workflow.py" in fallback_text and "--output-dir" in fallback_text,
            observed=fallback_text,
            expected="fallback command references scheduled_delivery_workflow.py and --output-dir",
            message="The API must never be the only way to reproduce the delivery.",
        ),
        check(
            "contract_tests_file_names_openapi_runtime_read_only_and_fallback_checks",
            len(build_api_contract_tests(contract)["tests"]) >= 5,
            observed=build_api_contract_tests(contract),
            expected="contract tests cover schema, validation, read-only boundary and CLI fallback",
            message="A generated API needs executable expectations, not only source code.",
        ),
    ]
    checks.extend(runtime_tests)

    blocking_errors = [item["id"] for item in checks if not item["valid"] and item["severity"] == "block"]
    if contract_errors or marker_errors or forbidden_markers or openapi_errors:
        status = "api_contract_block"
    elif package_errors or data_missing:
        status = "upstream_package_block"
    elif blocking_errors:
        status = "api_contract_block"
    else:
        status = "success"
    valid = not blocking_errors
    audit = {
        "version": API_VERSION,
        "api_id": contract.get("api_id"),
        "status": status,
        "valid": valid,
        "scheduled_package_dir": str(scheduled_path),
        "package_dir": str(package_dir),
        "copied_data": copied_data,
        "checks": checks,
        "summary": {
            "blocking_errors": blocking_errors,
            "contract_errors": contract_errors,
            "scheduled_package_errors": package_errors,
            "source_marker_errors": marker_errors,
            "forbidden_source_markers": forbidden_markers,
            "openapi_errors": openapi_errors,
            "check_count": len(checks),
        },
    }
    write_json(audit_path, audit)

    manifest = build_api_manifest(
        package_dir=package_dir,
        scheduled_package_dir=scheduled_path,
        api_contract_input_path=input_contract_path,
        status=status,
        valid=valid,
    )
    write_json(manifest_path, manifest)

    return FastAPIEndpointResult(
        status=status,
        valid=valid,
        output_dir=output_path,
        package_dir=package_dir,
        api_path=api_path,
        contract_path=contract_path,
        openapi_schema_path=openapi_path,
        contract_tests_path=contract_tests_path,
        audit_path=audit_path,
        manifest_path=manifest_path,
        report=audit,
    )


def write_sample_api_inputs(root: str | Path) -> dict[str, Path]:
    root_path = Path(root).resolve()
    root_path.mkdir(parents=True, exist_ok=True)
    workflow = load_scheduled_workflow()
    sample = workflow.write_sample_schedule_inputs(root_path / "schedule-inputs")
    scheduled = workflow.run_scheduled_delivery(
        app_dir=sample["app_dir"],
        cache_state_contract_path=sample["cache_state_contract_path"],
        freshness_policy_path=sample["freshness_policy_path"],
        cli_contract_path=sample["cli_contract_path"],
        schedule_contract_path=sample["schedule_contract_path"],
        output_dir=root_path / "scheduled-package",
        argv=["fastapi-example"],
    )
    api_contract_path = root_path / "api_contract.json"
    write_json(api_contract_path, default_api_contract())
    return {
        "scheduled_package_dir": scheduled.output_dir,
        "api_contract_path": api_contract_path,
    }


def system_error_report(
    *,
    message: str,
    code: str,
    output_dir: Path,
    argv: list[str],
) -> dict[str, Any]:
    return {
        "version": API_VERSION,
        "status": "system_error",
        "valid": False,
        "exit_code": API_EXIT_CODE_POLICY["system_error"],
        "output_dir": str(output_dir),
        "command": {"program": "fastapi_delivery_endpoint.py", "arguments": argv},
        "error": {"code": code, "message": message},
        "summary": {"blocking_errors": [code], "warnings": [], "check_count": 0},
        "checks": [],
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build an optional read-only FastAPI endpoint around a scheduled delivery package.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--scheduled-package-dir", type=Path, help="Input package produced by lesson 17/09.")
    parser.add_argument("--api-contract", type=Path, help="Optional api_contract.json path.")
    parser.add_argument("--output-dir", type=Path, required=True, help="Output directory for the FastAPI package.")
    parser.add_argument("--write-example", type=Path, help="Write sample scheduled package and API contract before building.")
    parser.add_argument("--no-overwrite", action="store_true", help="Do not replace an existing FastAPI package directory.")
    parser.add_argument("--fail-on-invalid", action="store_true", help="Return a non-zero code when contract checks fail.")
    parser.add_argument("--report", type=Path, help="Optional copy of api_audit.json.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    parsed = parse_args(argv)
    scheduled_package_dir = parsed.scheduled_package_dir
    api_contract = parsed.api_contract
    if parsed.write_example:
        sample = write_sample_api_inputs(parsed.write_example)
        scheduled_package_dir = scheduled_package_dir or sample["scheduled_package_dir"]
        api_contract = api_contract or sample["api_contract_path"]
    if scheduled_package_dir is None:
        report = system_error_report(
            message="missing required argument: --scheduled-package-dir or --write-example",
            code="missing_scheduled_package_dir",
            output_dir=parsed.output_dir.resolve(),
            argv=argv or sys.argv[1:],
        )
        if parsed.report:
            write_json(parsed.report, report)
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return API_EXIT_CODE_POLICY["system_error"]
    try:
        result = build_fastapi_delivery_endpoint(
            scheduled_package_dir=scheduled_package_dir,
            api_contract_path=api_contract,
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
        return API_EXIT_CODE_POLICY["system_error"]
    if parsed.report:
        write_json(parsed.report, result.report)
    response = {
        "status": result.status,
        "valid": result.valid,
        "output_dir": str(result.output_dir),
        "package_dir": str(result.package_dir),
        "api": str(result.api_path),
        "openapi_schema": str(result.openapi_schema_path),
        "contract_tests": str(result.contract_tests_path),
        "audit": str(result.audit_path),
        "manifest": str(result.manifest_path),
    }
    print(json.dumps(response, ensure_ascii=False, indent=2, sort_keys=True))
    if result.valid:
        return API_EXIT_CODE_POLICY["success"]
    if parsed.fail_on_invalid:
        return API_EXIT_CODE_POLICY.get(result.status, API_EXIT_CODE_POLICY["api_contract_block"])
    return API_EXIT_CODE_POLICY["success"]


if __name__ == "__main__":
    raise SystemExit(main())
