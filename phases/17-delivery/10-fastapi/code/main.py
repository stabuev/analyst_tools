from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "fastapi_delivery_endpoint.py"


def load_endpoint_builder():
    spec = importlib.util.spec_from_file_location("fastapi_delivery_endpoint", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    builder = load_endpoint_builder()
    with TemporaryDirectory() as directory:
        root = Path(directory)
        sample = builder.write_sample_api_inputs(root / "sample")
        result = builder.build_fastapi_delivery_endpoint(
            scheduled_package_dir=sample["scheduled_package_dir"],
            api_contract_path=sample["api_contract_path"],
            output_dir=root / "api-package",
        )
        api_module = builder.load_generated_api(result.api_path)
        client = TestClient(api_module.app)
        health = client.get("/health")
        runs = client.get("/runs")
        unknown = client.get("/runs/not-a-real-run-id")
        openapi_schema = builder.read_json(result.openapi_schema_path)
        audit = builder.read_json(result.audit_path)
        payload = {
            "status": result.status,
            "valid": result.valid,
            "health_status_code": health.status_code,
            "health_freshness_state": health.json()["freshness_state"],
            "run_count": len(runs.json()),
            "unknown_run_status_code": unknown.status_code,
            "openapi_path_count": len(openapi_schema["paths"]),
            "audit_blocking_errors": audit["summary"]["blocking_errors"],
            "package_files": [
                "api.py",
                "openapi_schema.json",
                "api_contract_tests.json",
                "cli_fallback.md",
                "api_audit.json",
                "api_manifest.json",
            ],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
