from __future__ import annotations

import argparse
import fnmatch
import hashlib
import importlib.util
import json
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DOCKER_AUDIT_VERSION = "1.0.0"
DEFAULT_PACKAGE_NAME = "docker-delivery-package"
DEFAULT_IMAGE_TAG = "trial-onboarding-delivery-api:local"
DOCKER_EXIT_CODE_POLICY = {
    "success": 0,
    "container_contract_block": 2,
    "upstream_package_block": 10,
    "system_error": 30,
}
REQUIRED_API_PACKAGE_FILES = [
    "api.py",
    "api_contract.json",
    "openapi_schema.json",
    "api_contract_tests.json",
    "api_audit.json",
    "api_manifest.json",
    "cli_fallback.md",
]
REQUIRED_DOCKERFILE_MARKERS = [
    "# syntax=docker/dockerfile:1",
    "FROM python:3.12-slim",
    "ENV PYTHONDONTWRITEBYTECODE=1",
    "WORKDIR /app",
    "COPY app/ /app/",
    "python -m pip install --no-cache-dir",
    "fastapi>=0.139.0,<0.140",
    "uvicorn>=0.50.1,<0.51",
    "USER appuser",
    "EXPOSE 8000",
    'CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]',
]
FORBIDDEN_DOCKERFILE_MARKERS = [
    "COPY . .",
    "ADD ",
    "USER root",
    "ARG TOKEN",
    "ARG SECRET",
    "ARG PASSWORD",
    "ENV TOKEN",
    "ENV SECRET",
    "ENV PASSWORD",
    "docker push",
    "curl http",
    "wget http",
]
REQUIRED_DOCKERIGNORE_PATTERNS = [
    ".git",
    ".venv",
    "__pycache__/",
    "**/__pycache__/",
    "*.pyc",
    "**/*.pyc",
    ".pytest_cache/",
    ".mypy_cache/",
    ".env",
    "*.env",
    "secrets/",
    "credentials/",
    "*.pem",
    "*.key",
    "data/raw/",
    "raw/",
    "*.parquet",
    "*.xlsx",
    "node_modules/",
    ".DS_Store",
]
GENERATED_METADATA_IGNORE_PATTERNS = [
    "docker_audit.json",
    "docker_manifest.json",
    "docker_build_context_report.json",
    "docker_run_manifest.json",
    "docker_contract_tests.json",
    "container_contract.json",
    "docker_runbook.md",
]
FORBIDDEN_CONTEXT_PATTERNS = [
    ".env",
    "*.env",
    "*.pem",
    "*.key",
    "secrets/",
    "credentials/",
    "__pycache__/",
    "**/__pycache__/",
    "*.pyc",
    "**/*.pyc",
    ".git",
    ".venv",
    "data/raw/",
    "raw/",
    "*.parquet",
    "*.xlsx",
]
ALLOWED_CONTEXT_TOP_LEVEL = {".dockerignore", "Dockerfile", "app"}


@dataclass(frozen=True)
class DockerPackagingResult:
    status: str
    valid: bool
    output_dir: Path
    package_dir: Path
    dockerfile_path: Path
    dockerignore_path: Path
    context_report_path: Path
    run_manifest_path: Path
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


def load_fastapi_builder():
    current = Path(__file__).resolve()
    builder_path = current.parents[2] / "10-fastapi" / "outputs" / "fastapi_delivery_endpoint.py"
    spec = importlib.util.spec_from_file_location("fastapi_delivery_endpoint_for_docker", builder_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load FastAPI builder: {builder_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def default_container_contract() -> dict[str, Any]:
    return {
        "container_id": "trial-onboarding-delivery-container",
        "version": DOCKER_AUDIT_VERSION,
        "image_tag": DEFAULT_IMAGE_TAG,
        "base_image": "python:3.12-slim",
        "runtime": {
            "python_version": "3.12",
            "working_dir": "/app",
            "port": 8000,
            "user": "appuser",
            "entrypoint": ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"],
            "healthcheck_url": "http://127.0.0.1:8000/health",
        },
        "build_context": {
            "include": ["Dockerfile", ".dockerignore", "app/"],
            "exclude_required": REQUIRED_DOCKERIGNORE_PATTERNS,
            "max_context_bytes": 500_000,
            "minimal_context_required": True,
        },
        "equivalence": {
            "local_manifest_path": "api_manifest.json",
            "container_manifest_expected": "/app/api_manifest.json",
            "compare_hashes": True,
        },
        "image_claim_boundary": {
            "local_only": True,
            "not_cloud_deployment": True,
            "no_registry_push": True,
            "no_runtime_secrets": True,
            "docker_daemon_optional_for_audit": True,
        },
    }


def normalize_container_contract(contract: dict[str, Any] | None) -> dict[str, Any]:
    normalized = default_container_contract()
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


def container_contract_errors(contract: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not contract.get("container_id"):
        errors.append("container_id_required")
    if contract.get("base_image") != "python:3.12-slim":
        errors.append("base_image_must_pin_python_3_12_slim")
    runtime = contract.get("runtime", {})
    if runtime.get("working_dir") != "/app":
        errors.append("runtime_workdir_must_be_app")
    if runtime.get("port") != 8000:
        errors.append("runtime_port_must_be_8000")
    if runtime.get("user") != "appuser":
        errors.append("runtime_user_must_be_non_root_appuser")
    if runtime.get("entrypoint") != ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]:
        errors.append("runtime_entrypoint_must_start_uvicorn_api")
    context = contract.get("build_context", {})
    include = set(context.get("include", []))
    for required in ["Dockerfile", ".dockerignore", "app/"]:
        if required not in include:
            errors.append(f"build_context_missing_include:{required}")
    exclude_required = set(context.get("exclude_required", []))
    for pattern in REQUIRED_DOCKERIGNORE_PATTERNS:
        if pattern not in exclude_required:
            errors.append(f"build_context_missing_required_exclude:{pattern}")
    if not context.get("minimal_context_required"):
        errors.append("minimal_build_context_required")
    if int(context.get("max_context_bytes", 0) or 0) <= 0:
        errors.append("max_context_bytes_must_be_positive")
    equivalence = contract.get("equivalence", {})
    if equivalence.get("local_manifest_path") != "api_manifest.json":
        errors.append("equivalence_local_manifest_must_be_api_manifest")
    if equivalence.get("container_manifest_expected") != "/app/api_manifest.json":
        errors.append("equivalence_container_manifest_must_be_app_api_manifest")
    if not equivalence.get("compare_hashes"):
        errors.append("equivalence_compare_hashes_required")
    boundary = contract.get("image_claim_boundary", {})
    for key in ["local_only", "not_cloud_deployment", "no_registry_push", "no_runtime_secrets"]:
        if not boundary.get(key):
            errors.append(f"image_boundary_{key}_required")
    return errors


def build_dockerfile(contract: dict[str, Any]) -> str:
    runtime = contract["runtime"]
    entrypoint = json.dumps(runtime["entrypoint"])
    return f"""# syntax=docker/dockerfile:1
FROM {contract["base_image"]}

ENV PYTHONDONTWRITEBYTECODE=1 \\
    PYTHONUNBUFFERED=1

WORKDIR {runtime["working_dir"]}
RUN groupadd --system app && useradd --system --gid app {runtime["user"]}

COPY app/ /app/

RUN python -m pip install --no-cache-dir \\
    "fastapi>=0.139.0,<0.140" \\
    "uvicorn>=0.50.1,<0.51"

USER {runtime["user"]}
EXPOSE {runtime["port"]}
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('{runtime["healthcheck_url"]}', timeout=2).read()" || exit 1
CMD {entrypoint}
"""


def build_dockerignore() -> str:
    lines = [
        "# Secrets and local credentials",
        ".env",
        "*.env",
        "secrets/",
        "credentials/",
        "*.pem",
        "*.key",
        "",
        "# Local development state and caches",
        ".git",
        ".venv",
        "__pycache__/",
        "**/__pycache__/",
        "*.pyc",
        "**/*.pyc",
        ".pytest_cache/",
        ".mypy_cache/",
        "node_modules/",
        ".DS_Store",
        "",
        "# Heavy or raw data should not enter an image build",
        "data/raw/",
        "raw/",
        "*.parquet",
        "*.xlsx",
        "",
        "# Audit metadata is shipped with the lesson package, not copied into the image",
        *GENERATED_METADATA_IGNORE_PATTERNS,
    ]
    return "\n".join(lines) + "\n"


def dockerfile_marker_errors(source_text: str) -> list[str]:
    return [marker for marker in REQUIRED_DOCKERFILE_MARKERS if marker not in source_text]


def forbidden_dockerfile_markers(source_text: str) -> list[str]:
    return [marker for marker in FORBIDDEN_DOCKERFILE_MARKERS if marker in source_text]


def dockerignore_pattern_errors(dockerignore_text: str) -> list[str]:
    patterns = {
        line.strip()
        for line in dockerignore_text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    }
    return [pattern for pattern in REQUIRED_DOCKERIGNORE_PATTERNS if pattern not in patterns]


def pattern_matches(relative_path: str, pattern: str) -> bool:
    pattern = pattern.strip()
    if not pattern or pattern.startswith("#"):
        return False
    if pattern.startswith("!"):
        return False
    normalized = relative_path.replace(os.sep, "/")
    name = Path(normalized).name
    if pattern.endswith("/"):
        prefix = pattern.rstrip("/")
        if prefix.startswith("**/"):
            directory_name = prefix[3:]
            return directory_name in normalized.split("/")
        wrapped = f"/{normalized}/"
        return (
            normalized == prefix
            or normalized.startswith(f"{prefix}/")
            or f"/{prefix}/" in wrapped
            or any(part == prefix for part in normalized.split("/"))
        )
    if pattern.startswith("**/"):
        tail = pattern[3:]
        return fnmatch.fnmatch(normalized, pattern) or fnmatch.fnmatch(name, tail)
    return fnmatch.fnmatch(normalized, pattern) or fnmatch.fnmatch(name, pattern)


def ignore_reason(relative_path: str, patterns: list[str]) -> str | None:
    for pattern in patterns:
        if pattern_matches(relative_path, pattern):
            return pattern
    return None


def dockerignore_patterns(dockerignore_text: str) -> list[str]:
    return [
        line.strip()
        for line in dockerignore_text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def context_entry(path: Path, *, start: Path, reason: str | None = None) -> dict[str, Any]:
    payload = manifest_entry(path, start=start)
    if reason:
        payload["excluded_by"] = reason
    return payload


def build_context_report(package_dir: Path, dockerignore_text: str, source_api_package_dir: Path) -> dict[str, Any]:
    patterns = dockerignore_patterns(dockerignore_text)
    included: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for path in sorted(item for item in package_dir.rglob("*") if item.is_file()):
        relative = relpath(path, start=package_dir)
        reason = ignore_reason(relative, patterns)
        if reason:
            excluded.append(context_entry(path, start=package_dir, reason=reason))
        else:
            included.append(context_entry(path, start=package_dir))
    included_paths = [item["path"] for item in included]
    forbidden_included = [
        path
        for path in included_paths
        if ignore_reason(path, FORBIDDEN_CONTEXT_PATTERNS) is not None
    ]
    source_forbidden_candidates = [
        relpath(path, start=source_api_package_dir)
        for path in sorted(item for item in source_api_package_dir.rglob("*") if item.is_file())
        if ignore_reason(relpath(path, start=source_api_package_dir), FORBIDDEN_CONTEXT_PATTERNS) is not None
    ]
    top_level = sorted({path.split("/", 1)[0] for path in included_paths})
    total_bytes = sum(int(item["bytes"]) for item in included)
    return {
        "version": DOCKER_AUDIT_VERSION,
        "context_root": str(package_dir),
        "dockerignore_pattern_count": len(patterns),
        "included": included,
        "excluded": excluded,
        "included_count": len(included),
        "excluded_count": len(excluded),
        "included_total_bytes": total_bytes,
        "included_top_level": top_level,
        "allowed_top_level": sorted(ALLOWED_CONTEXT_TOP_LEVEL),
        "forbidden_included_paths": forbidden_included,
        "source_forbidden_candidates": source_forbidden_candidates,
    }


def fastapi_package_errors(api_package_dir: str | Path) -> list[str]:
    package_dir = Path(api_package_dir)
    errors: list[str] = []
    if not package_dir.is_dir():
        return ["api_package_dir_missing"]
    for relative in REQUIRED_API_PACKAGE_FILES:
        if not (package_dir / relative).is_file():
            errors.append(f"missing_api_package_file:{relative}")
    if not (package_dir / "api_data").is_dir():
        errors.append("missing_api_data_dir")
    audit_path = package_dir / "api_audit.json"
    if audit_path.is_file():
        audit = read_json(audit_path)
        if audit.get("status") != "success":
            errors.append("api_audit_status_must_be_success")
        if not audit.get("valid"):
            errors.append("api_audit_must_be_valid")
        if audit.get("summary", {}).get("blocking_errors"):
            errors.append("api_audit_must_not_have_blocking_errors")
    manifest_path = package_dir / "api_manifest.json"
    if manifest_path.is_file():
        manifest = read_json(manifest_path)
        if manifest.get("renderer_used") != "fastapi_delivery_endpoint":
            errors.append("api_manifest_renderer_must_be_fastapi_delivery_endpoint")
        if manifest.get("status") != "success":
            errors.append("api_manifest_status_must_be_success")
        if not manifest.get("valid"):
            errors.append("api_manifest_must_be_valid")
    return errors


def copy_fastapi_package(api_package_dir: Path, app_dir: Path) -> dict[str, dict[str, Any]]:
    app_dir.mkdir(parents=True, exist_ok=True)
    copied: dict[str, dict[str, Any]] = {}
    for relative in REQUIRED_API_PACKAGE_FILES:
        source = api_package_dir / relative
        destination = app_dir / relative
        if source.is_file():
            shutil.copy2(source, destination)
            copied[relative] = manifest_entry(destination, start=app_dir)
        else:
            copied[relative] = {"path": relative, "sha256": "", "bytes": 0, "missing": True}
    source_data = api_package_dir / "api_data"
    destination_data = app_dir / "api_data"
    if source_data.is_dir():
        shutil.copytree(source_data, destination_data)
        for path in sorted(item for item in destination_data.rglob("*") if item.is_file()):
            relative = relpath(path, start=app_dir)
            copied[relative] = manifest_entry(path, start=app_dir)
    else:
        copied["api_data"] = {"path": "api_data", "sha256": "", "bytes": 0, "missing": True}
    return copied


def build_docker_contract_tests(contract: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": DOCKER_AUDIT_VERSION,
        "container_id": contract["container_id"],
        "tests": [
            {
                "id": "dockerfile_uses_pinned_runtime_and_non_root_user",
                "expected": "Dockerfile uses python:3.12-slim, WORKDIR /app, USER appuser and uvicorn CMD.",
                "source": "Dockerfile",
            },
            {
                "id": "dockerignore_blocks_secrets_caches_raw_data",
                "expected": ".dockerignore names local credentials, caches, raw data and generated metadata.",
                "source": ".dockerignore",
            },
            {
                "id": "build_context_is_minimal",
                "expected": "Only Dockerfile, .dockerignore and app/ enter the planned Docker build context.",
                "source": "docker_build_context_report.json",
            },
            {
                "id": "container_manifest_matches_local_api_manifest",
                "expected": "The copied /app/api_manifest.json hash equals the local FastAPI package manifest hash.",
                "source": "docker_run_manifest.json",
            },
            {
                "id": "run_manifest_is_local_only",
                "expected": "Run commands build and run locally and do not push to a registry or claim cloud deployment.",
                "source": "docker_run_manifest.json",
            },
            {
                "id": "upstream_fastapi_package_remains_valid",
                "expected": "Docker packaging wraps a valid FastAPI package instead of fixing it inside the image.",
                "source": "app/api_audit.json",
            },
        ],
    }


def build_run_manifest(
    *,
    contract: dict[str, Any],
    package_dir: Path,
    source_api_package_dir: Path,
) -> dict[str, Any]:
    source_manifest = source_api_package_dir / "api_manifest.json"
    packaged_manifest = package_dir / "app" / "api_manifest.json"
    source_sha = sha256_file(source_manifest) if source_manifest.is_file() else ""
    packaged_sha = sha256_file(packaged_manifest) if packaged_manifest.is_file() else ""
    image_tag = contract.get("image_tag") or DEFAULT_IMAGE_TAG
    return {
        "version": DOCKER_AUDIT_VERSION,
        "image_tag": image_tag,
        "build_command": ["docker", "build", "--pull", "--tag", image_tag, "."],
        "run_command": ["docker", "run", "--rm", "-p", "8000:8000", image_tag],
        "healthcheck_url": contract["runtime"]["healthcheck_url"],
        "equivalence": {
            "local_manifest": optional_manifest_entry(source_manifest, start=source_api_package_dir),
            "container_manifest_path": contract["equivalence"]["container_manifest_expected"],
            "packaged_manifest": optional_manifest_entry(packaged_manifest, start=package_dir),
            "expected_container_manifest_sha256": source_sha,
            "packaged_manifest_sha256": packaged_sha,
            "hashes_match": bool(source_sha and packaged_sha and source_sha == packaged_sha),
            "check_command": [
                "docker",
                "run",
                "--rm",
                image_tag,
                "python",
                "-c",
                "import hashlib, pathlib; print(hashlib.sha256(pathlib.Path('/app/api_manifest.json').read_bytes()).hexdigest())",
            ],
        },
        "boundary": {
            "local_only": True,
            "not_cloud_deployment": True,
            "no_registry_push": True,
            "no_runtime_secrets": True,
            "docker_daemon_optional_for_audit": True,
        },
    }


def build_runbook(contract: dict[str, Any]) -> str:
    image_tag = contract.get("image_tag") or DEFAULT_IMAGE_TAG
    port = contract["runtime"]["port"]
    return f"""# Docker packaging runbook

This package is an optional local container wrapper around the generated FastAPI package.
It does not replace the CLI/report delivery path and does not claim cloud deployment.

```bash
docker build --pull --tag {image_tag} .
docker run --rm -p {port}:{port} {image_tag}
```

Verify the API locally:

```bash
curl http://127.0.0.1:{port}/health
curl http://127.0.0.1:{port}/artifacts/manifest
```

Do not add runtime secrets to the Dockerfile, do not push this image to a registry from
the lesson package, and keep raw data outside the build context.
"""


def context_report_errors(report: dict[str, Any], contract: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    max_bytes = int(contract["build_context"]["max_context_bytes"])
    if report["included_total_bytes"] > max_bytes:
        errors.append("build_context_exceeds_max_context_bytes")
    if report["forbidden_included_paths"]:
        errors.append("build_context_includes_forbidden_paths")
    if set(report["included_top_level"]) - ALLOWED_CONTEXT_TOP_LEVEL:
        errors.append("build_context_has_unexpected_top_level_files")
    included = set(report["included_top_level"])
    for required in ["Dockerfile", ".dockerignore", "app"]:
        if required not in included:
            errors.append(f"build_context_missing_required_top_level:{required}")
    return errors


def collect_output_entries(root: Path) -> dict[str, dict[str, Any]]:
    entries: dict[str, dict[str, Any]] = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = relpath(path, start=root)
        if relative == "docker_manifest.json":
            continue
        key = relative.replace("/", "_").replace(".", "_").replace("-", "_")
        entries[key] = manifest_entry(path, start=root)
    return entries


def build_docker_manifest(
    *,
    package_dir: Path,
    source_api_package_dir: Path,
    container_contract_input_path: Path | None,
    status: str,
    valid: bool,
) -> dict[str, Any]:
    return {
        "version": DOCKER_AUDIT_VERSION,
        "renderer_used": "docker_packaging_audit",
        "status": status,
        "valid": valid,
        "hash_algorithm": "sha256",
        "inputs": {
            "source_api_manifest": optional_manifest_entry(
                source_api_package_dir / "api_manifest.json",
                start=source_api_package_dir,
            ),
            "container_contract_input": optional_manifest_entry(container_contract_input_path, start=package_dir),
        },
        "outputs": collect_output_entries(package_dir),
    }


def build_docker_packaging_audit(
    *,
    api_package_dir: str | Path,
    output_dir: str | Path,
    container_contract_path: str | Path | None = None,
    overwrite: bool = True,
) -> DockerPackagingResult:
    output_path = Path(output_dir).resolve()
    package_dir = output_path / DEFAULT_PACKAGE_NAME
    if package_dir.exists() and overwrite:
        shutil.rmtree(package_dir)
    if package_dir.exists():
        raise FileExistsError(f"output package already exists: {package_dir}")
    package_dir.mkdir(parents=True, exist_ok=True)

    source_api_package_dir = Path(api_package_dir).resolve()
    input_contract_path = Path(container_contract_path).resolve() if container_contract_path else None
    contract = normalize_container_contract(read_json(input_contract_path) if input_contract_path else None)
    contract_errors = container_contract_errors(contract)
    api_errors = fastapi_package_errors(source_api_package_dir)

    app_dir = package_dir / "app"
    copied_api_files = copy_fastapi_package(source_api_package_dir, app_dir) if source_api_package_dir.exists() else {}

    dockerfile_path = package_dir / "Dockerfile"
    dockerignore_path = package_dir / ".dockerignore"
    contract_path = package_dir / "container_contract.json"
    contract_tests_path = package_dir / "docker_contract_tests.json"
    runbook_path = package_dir / "docker_runbook.md"
    run_manifest_path = package_dir / "docker_run_manifest.json"
    context_report_path = package_dir / "docker_build_context_report.json"
    audit_path = package_dir / "docker_audit.json"
    manifest_path = package_dir / "docker_manifest.json"

    dockerfile = build_dockerfile(contract)
    dockerignore = build_dockerignore()
    write_text(dockerfile_path, dockerfile)
    write_text(dockerignore_path, dockerignore)
    write_json(contract_path, contract)
    write_json(contract_tests_path, build_docker_contract_tests(contract))
    write_text(runbook_path, build_runbook(contract))
    run_manifest = build_run_manifest(
        contract=contract,
        package_dir=package_dir,
        source_api_package_dir=source_api_package_dir,
    )
    write_json(run_manifest_path, run_manifest)
    context_report = build_context_report(package_dir, dockerignore, source_api_package_dir)
    write_json(context_report_path, context_report)

    dockerfile_errors = dockerfile_marker_errors(dockerfile)
    dockerfile_forbidden = forbidden_dockerfile_markers(dockerfile)
    dockerignore_errors = dockerignore_pattern_errors(dockerignore)
    context_errors = context_report_errors(context_report, contract)
    missing_copies = [path for path, payload in copied_api_files.items() if payload.get("missing")]
    manifest_equivalence_valid = run_manifest["equivalence"]["hashes_match"]
    run_boundary = run_manifest["boundary"]
    run_commands = [*run_manifest["build_command"], *run_manifest["run_command"]]
    command_text = " ".join(run_commands)
    checks = [
        check(
            "upstream_fastapi_package_is_valid_before_container_packaging",
            not api_errors and not missing_copies,
            observed={"api_errors": api_errors, "missing_copies": missing_copies},
            expected="valid FastAPI delivery package with manifest, audit, OpenAPI and api_data",
            message="Docker must package a known-good interface, not hide upstream delivery defects.",
        ),
        check(
            "container_contract_declares_local_runtime_context_and_boundaries",
            not contract_errors,
            observed=contract_errors,
            expected="python:3.12-slim, /app, port 8000, non-root user, local-only boundary",
            message="The container contract defines the packaging promise reviewers can audit.",
        ),
        check(
            "dockerfile_uses_pinned_slim_runtime_non_root_user_and_uvicorn_cmd",
            not dockerfile_errors,
            observed=dockerfile_errors,
            expected=REQUIRED_DOCKERFILE_MARKERS,
            message="The Dockerfile should make runtime assumptions explicit and inspectable.",
        ),
        check(
            "dockerfile_has_no_broad_copy_root_user_or_secret_patterns",
            not dockerfile_forbidden,
            observed=dockerfile_forbidden,
            expected="no COPY . ., ADD, root runtime user, secrets, token args or push commands",
            message="Packaging should not smuggle credentials or local machine state into the image.",
        ),
        check(
            "dockerignore_excludes_secrets_caches_local_state_and_raw_data",
            not dockerignore_errors,
            observed=dockerignore_errors,
            expected=REQUIRED_DOCKERIGNORE_PATTERNS,
            message=".dockerignore is the guardrail between a reproducible image and a laptop dump.",
        ),
        check(
            "build_context_report_is_small_minimal_and_forbidden_free",
            not context_errors,
            observed=context_errors,
            expected={"allowed_top_level": sorted(ALLOWED_CONTEXT_TOP_LEVEL), "max_bytes": contract["build_context"]["max_context_bytes"]},
            message="Only the app runtime files and Docker control files should enter the build context.",
        ),
        check(
            "source_forbidden_candidates_are_not_copied_into_context",
            not context_report["forbidden_included_paths"],
            observed={
                "source_forbidden_candidates": context_report["source_forbidden_candidates"],
                "forbidden_included_paths": context_report["forbidden_included_paths"],
            },
            expected="secret/cache/raw candidates, if present in source, are excluded from context",
            message="The builder copies an allow-list from the API package and the context audit verifies it.",
        ),
        check(
            "container_run_manifest_preserves_local_api_manifest_hash",
            manifest_equivalence_valid,
            observed=run_manifest["equivalence"],
            expected="source api_manifest.json sha256 equals packaged /app/api_manifest.json sha256",
            message="Container execution should expose the same delivery manifest as local execution.",
        ),
        check(
            "container_run_manifest_is_local_only_and_has_no_registry_push",
            bool(run_boundary.get("local_only"))
            and bool(run_boundary.get("no_registry_push"))
            and "push" not in command_text
            and ":" in run_manifest["image_tag"],
            observed=run_manifest,
            expected="docker build and docker run commands only, no registry push or cloud deployment claim",
            message="This lesson packages for local reproducibility, not production deployment.",
        ),
        check(
            "docker_contract_tests_name_context_manifest_boundary_and_upstream_checks",
            len(build_docker_contract_tests(contract)["tests"]) >= 6,
            observed=build_docker_contract_tests(contract),
            expected="contract tests cover Dockerfile, .dockerignore, context, equivalence, boundary and upstream package",
            message="The package includes reviewable expectations alongside generated files.",
        ),
    ]
    blocking_errors = [item["id"] for item in checks if not item["valid"] and item["severity"] == "block"]
    if api_errors or missing_copies:
        status = "upstream_package_block"
    elif contract_errors or dockerfile_errors or dockerfile_forbidden or dockerignore_errors or context_errors or not manifest_equivalence_valid:
        status = "container_contract_block"
    elif blocking_errors:
        status = "container_contract_block"
    else:
        status = "success"
    valid = not blocking_errors
    audit = {
        "version": DOCKER_AUDIT_VERSION,
        "container_id": contract.get("container_id"),
        "status": status,
        "valid": valid,
        "source_api_package_dir": str(source_api_package_dir),
        "package_dir": str(package_dir),
        "checks": checks,
        "copied_api_files": copied_api_files,
        "summary": {
            "blocking_errors": blocking_errors,
            "api_package_errors": api_errors,
            "container_contract_errors": contract_errors,
            "dockerfile_marker_errors": dockerfile_errors,
            "forbidden_dockerfile_markers": dockerfile_forbidden,
            "dockerignore_errors": dockerignore_errors,
            "context_errors": context_errors,
            "check_count": len(checks),
        },
    }
    write_json(audit_path, audit)

    manifest = build_docker_manifest(
        package_dir=package_dir,
        source_api_package_dir=source_api_package_dir,
        container_contract_input_path=input_contract_path,
        status=status,
        valid=valid,
    )
    write_json(manifest_path, manifest)

    return DockerPackagingResult(
        status=status,
        valid=valid,
        output_dir=output_path,
        package_dir=package_dir,
        dockerfile_path=dockerfile_path,
        dockerignore_path=dockerignore_path,
        context_report_path=context_report_path,
        run_manifest_path=run_manifest_path,
        audit_path=audit_path,
        manifest_path=manifest_path,
        report=audit,
    )


def write_sample_docker_inputs(root: str | Path) -> dict[str, Path]:
    root_path = Path(root).resolve()
    root_path.mkdir(parents=True, exist_ok=True)
    builder = load_fastapi_builder()
    sample = builder.write_sample_api_inputs(root_path / "fastapi-inputs")
    api_result = builder.build_fastapi_delivery_endpoint(
        scheduled_package_dir=sample["scheduled_package_dir"],
        api_contract_path=sample["api_contract_path"],
        output_dir=root_path / "fastapi-package",
    )
    contract_path = root_path / "container_contract.json"
    write_json(contract_path, default_container_contract())
    return {
        "api_package_dir": api_result.package_dir,
        "container_contract_path": contract_path,
    }


def system_error_report(
    *,
    message: str,
    code: str,
    output_dir: Path,
    argv: list[str],
) -> dict[str, Any]:
    return {
        "version": DOCKER_AUDIT_VERSION,
        "status": "system_error",
        "valid": False,
        "exit_code": DOCKER_EXIT_CODE_POLICY["system_error"],
        "output_dir": str(output_dir),
        "command": {"program": "docker_packaging_audit.py", "arguments": argv},
        "error": {"code": code, "message": message},
        "summary": {"blocking_errors": [code], "warnings": [], "check_count": 0},
        "checks": [],
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build and audit an optional local Docker packaging contract for the FastAPI delivery package.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--api-package-dir", type=Path, help="Input package produced by lesson 17/10.")
    parser.add_argument("--container-contract", type=Path, help="Optional container_contract.json path.")
    parser.add_argument("--output-dir", type=Path, required=True, help="Output directory for the Docker package.")
    parser.add_argument("--write-example", type=Path, help="Write sample FastAPI package and container contract before auditing.")
    parser.add_argument("--no-overwrite", action="store_true", help="Do not replace an existing Docker package directory.")
    parser.add_argument("--fail-on-invalid", action="store_true", help="Return a non-zero code when Docker checks fail.")
    parser.add_argument("--report", type=Path, help="Optional copy of docker_audit.json.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    parsed = parse_args(argv)
    api_package_dir = parsed.api_package_dir
    container_contract = parsed.container_contract
    if parsed.write_example:
        sample = write_sample_docker_inputs(parsed.write_example)
        api_package_dir = api_package_dir or sample["api_package_dir"]
        container_contract = container_contract or sample["container_contract_path"]
    if api_package_dir is None:
        report = system_error_report(
            message="missing required argument: --api-package-dir or --write-example",
            code="missing_api_package_dir",
            output_dir=parsed.output_dir.resolve(),
            argv=argv or sys.argv[1:],
        )
        if parsed.report:
            write_json(parsed.report, report)
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return DOCKER_EXIT_CODE_POLICY["system_error"]
    try:
        result = build_docker_packaging_audit(
            api_package_dir=api_package_dir,
            container_contract_path=container_contract,
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
        return DOCKER_EXIT_CODE_POLICY["system_error"]
    if parsed.report:
        write_json(parsed.report, result.report)
    response = {
        "status": result.status,
        "valid": result.valid,
        "output_dir": str(result.output_dir),
        "package_dir": str(result.package_dir),
        "dockerfile": str(result.dockerfile_path),
        "dockerignore": str(result.dockerignore_path),
        "context_report": str(result.context_report_path),
        "run_manifest": str(result.run_manifest_path),
        "audit": str(result.audit_path),
        "manifest": str(result.manifest_path),
    }
    print(json.dumps(response, ensure_ascii=False, indent=2, sort_keys=True))
    if result.valid:
        return DOCKER_EXIT_CODE_POLICY["success"]
    if parsed.fail_on_invalid:
        return DOCKER_EXIT_CODE_POLICY.get(result.status, DOCKER_EXIT_CODE_POLICY["container_contract_block"])
    return DOCKER_EXIT_CODE_POLICY["success"]


if __name__ == "__main__":
    raise SystemExit(main())
