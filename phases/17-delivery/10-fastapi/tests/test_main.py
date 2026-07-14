from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "fastapi_delivery_endpoint.py"
CODE = ROOT / "code" / "main.py"
SPEC = importlib.util.spec_from_file_location("fastapi_delivery_endpoint", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
ENDPOINT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ENDPOINT
SPEC.loader.exec_module(ENDPOINT)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_sample(root: Path):
    sample = ENDPOINT.write_sample_api_inputs(root / "sample")
    result = ENDPOINT.build_fastapi_delivery_endpoint(
        scheduled_package_dir=sample["scheduled_package_dir"],
        api_contract_path=sample["api_contract_path"],
        output_dir=root / "api-package",
    )
    return sample, result


class FastAPIDeliveryEndpointTest(unittest.TestCase):
    def test_sample_api_package_writes_required_files_and_audit(self) -> None:
        with TemporaryDirectory() as directory:
            _sample, result = build_sample(Path(directory))

            self.assertTrue(result.valid)
            self.assertEqual(result.status, "success")
            for relative in [
                "api.py",
                "api_contract.json",
                "openapi_schema.json",
                "api_contract_tests.json",
                "api_audit.json",
                "api_manifest.json",
                "cli_fallback.md",
                "api_data/schedule_run_report.json",
                "api_data/run_history.csv",
                "api_data/last_success_marker.json",
            ]:
                self.assertTrue((result.package_dir / relative).is_file(), relative)

    def test_default_contract_is_get_only_and_keeps_cli_fallback(self) -> None:
        contract = ENDPOINT.default_api_contract()

        self.assertEqual(ENDPOINT.api_contract_errors(contract), [])
        self.assertEqual(contract["read_only_boundary"]["allowed_methods"], ["GET"])
        self.assertTrue(contract["read_only_boundary"]["cli_fallback_required"])
        self.assertEqual(
            sorted(route["path"] for route in contract["routes"]),
            sorted(ENDPOINT.REQUIRED_ROUTE_PATHS),
        )
        self.assertIn("scheduled_delivery_workflow.py", contract["cli_fallback"]["command"])

    def test_generated_source_uses_fastapi_pydantic_response_models_and_no_mutation(self) -> None:
        with TemporaryDirectory() as directory:
            _sample, result = build_sample(Path(directory))
            source = result.api_path.read_text(encoding="utf-8")

            self.assertEqual(ENDPOINT.source_marker_errors(source), [])
            self.assertEqual(ENDPOINT.forbidden_source_markers(source), [])
            self.assertIn("response_model=HealthResponse", source)
            self.assertIn("response_model=list[RunHistoryRow]", source)
            self.assertNotIn("@app.post", source)
            self.assertNotIn(".write_text(", source)

    def test_openapi_schema_exposes_get_paths_and_pydantic_models(self) -> None:
        with TemporaryDirectory() as directory:
            _sample, result = build_sample(Path(directory))
            schema = read_json(result.openapi_schema_path)

            self.assertEqual(ENDPOINT.openapi_schema_errors(schema), [])
            for path in ENDPOINT.REQUIRED_ROUTE_PATHS:
                self.assertIn("get", schema["paths"][path])
            for method_map in schema["paths"].values():
                self.assertNotIn("post", method_map)
                self.assertNotIn("put", method_map)
                self.assertNotIn("patch", method_map)
                self.assertNotIn("delete", method_map)
            for model in ENDPOINT.REQUIRED_RESPONSE_MODELS:
                self.assertIn(model, schema["components"]["schemas"])

    def test_generated_app_serves_health_summary_runs_and_manifest(self) -> None:
        with TemporaryDirectory() as directory:
            _sample, result = build_sample(Path(directory))
            module = ENDPOINT.load_generated_api(result.api_path)
            client = TestClient(module.app)

            health = client.get("/health")
            summary = client.get("/summary")
            runs = client.get("/runs")
            manifest = client.get("/artifacts/manifest")
            run_id = runs.json()[0]["run_id"]
            run_detail = client.get(f"/runs/{run_id}")

            self.assertEqual(health.status_code, 200)
            self.assertEqual(health.json()["freshness_state"], "fresh")
            self.assertEqual(summary.status_code, 200)
            self.assertEqual(summary.json()["delivery_status"], "success")
            self.assertEqual(runs.status_code, 200)
            self.assertGreaterEqual(len(runs.json()), 1)
            self.assertEqual(run_detail.status_code, 200)
            self.assertEqual(run_detail.json()["run_id"], run_id)
            self.assertEqual(manifest.status_code, 200)
            self.assertEqual(manifest.json()["renderer_used"], "scheduled_delivery_workflow")

    def test_invalid_inputs_return_clear_404_and_422(self) -> None:
        with TemporaryDirectory() as directory:
            _sample, result = build_sample(Path(directory))
            module = ENDPOINT.load_generated_api(result.api_path)
            client = TestClient(module.app)

            unknown = client.get("/runs/not-a-real-run-id")
            invalid_query = client.get("/runs", params={"status": "not-a-status"})

            self.assertEqual(unknown.status_code, 404)
            self.assertIn("run_id not found", unknown.json()["detail"])
            self.assertEqual(invalid_query.status_code, 422)

    def test_contract_with_mutating_route_blocks_api(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            sample = ENDPOINT.write_sample_api_inputs(root / "sample")
            contract = ENDPOINT.default_api_contract()
            contract["routes"][0]["method"] = "POST"
            bad_contract_path = root / "bad_api_contract.json"
            write_json(bad_contract_path, contract)

            result = ENDPOINT.build_fastapi_delivery_endpoint(
                scheduled_package_dir=sample["scheduled_package_dir"],
                api_contract_path=bad_contract_path,
                output_dir=root / "api-package",
            )
            audit = read_json(result.audit_path)

            self.assertFalse(result.valid)
            self.assertEqual(result.status, "api_contract_block")
            self.assertIn("api_contract_declares_read_only_routes_and_cli_fallback", audit["summary"]["blocking_errors"])
            self.assertIn("route_method_must_be_get:/health", audit["summary"]["contract_errors"])

    def test_missing_run_history_blocks_upstream_package(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            sample = ENDPOINT.write_sample_api_inputs(root / "sample")
            (sample["scheduled_package_dir"] / "run_history.csv").unlink()

            result = ENDPOINT.build_fastapi_delivery_endpoint(
                scheduled_package_dir=sample["scheduled_package_dir"],
                api_contract_path=sample["api_contract_path"],
                output_dir=root / "api-package",
            )
            audit = read_json(result.audit_path)

            self.assertFalse(result.valid)
            self.assertEqual(result.status, "upstream_package_block")
            self.assertIn("run_history_must_have_at_least_one_attempt", audit["summary"]["scheduled_package_errors"])

    def test_non_success_schedule_report_blocks_api_even_if_files_exist(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            sample = ENDPOINT.write_sample_api_inputs(root / "sample")
            run_report_path = sample["scheduled_package_dir"] / "schedule_run_report.json"
            run_report = read_json(run_report_path)
            run_report["status"] = "data_quality_block"
            run_report["summary"]["blocking_errors"] = ["tampered_for_api_test"]
            write_json(run_report_path, run_report)

            result = ENDPOINT.build_fastapi_delivery_endpoint(
                scheduled_package_dir=sample["scheduled_package_dir"],
                api_contract_path=sample["api_contract_path"],
                output_dir=root / "api-package",
            )
            audit = read_json(result.audit_path)

            self.assertFalse(result.valid)
            self.assertEqual(result.status, "upstream_package_block")
            self.assertIn("scheduled_run_status_must_be_success", audit["summary"]["scheduled_package_errors"])
            self.assertIn("scheduled_run_report_has_blocking_errors", audit["summary"]["scheduled_package_errors"])

    def test_forbidden_source_marker_checker_catches_mutation_network_and_env_patterns(self) -> None:
        source = """
@app.post("/runs")
def mutate():
    requests.get("https://example.com")
    value = os.environ["TOKEN"]
    Path("x").write_text("bad")
"""

        markers = ENDPOINT.forbidden_source_markers(source)

        self.assertIn("@app.post", markers)
        self.assertIn("requests.", markers)
        self.assertIn("os.environ", markers)
        self.assertIn(".write_text(", markers)

    def test_contract_tests_and_cli_fallback_document_named_expectations(self) -> None:
        with TemporaryDirectory() as directory:
            _sample, result = build_sample(Path(directory))
            contract_tests = read_json(result.contract_tests_path)
            fallback = (result.package_dir / "cli_fallback.md").read_text(encoding="utf-8")

            self.assertGreaterEqual(len(contract_tests["tests"]), 5)
            self.assertIn("openapi_schema_matches_contract", {item["id"] for item in contract_tests["tests"]})
            self.assertIn("scheduled_delivery_workflow.py", fallback)
            self.assertIn("--output-dir", fallback)

    def test_manifest_hashes_api_source_openapi_audit_and_data_files(self) -> None:
        with TemporaryDirectory() as directory:
            _sample, result = build_sample(Path(directory))
            manifest = read_json(result.manifest_path)

            outputs = manifest["outputs"]
            self.assertEqual(manifest["renderer_used"], "fastapi_delivery_endpoint")
            self.assertEqual(manifest["hash_algorithm"], "sha256")
            self.assertEqual(len(outputs["api_py"]["sha256"]), 64)
            self.assertEqual(len(outputs["openapi_schema_json"]["sha256"]), 64)
            self.assertEqual(len(outputs["api_audit_json"]["sha256"]), 64)
            self.assertEqual(len(outputs["api_data_run_history_csv"]["sha256"]), 64)

    def test_cli_help_names_api_arguments(self) -> None:
        process = subprocess.run(
            [sys.executable, str(ARTIFACT), "--help"],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(process.returncode, 0)
        self.assertIn("--scheduled-package-dir", process.stdout)
        self.assertIn("--api-contract", process.stdout)
        self.assertIn("--fail-on-invalid", process.stdout)
        self.assertIn("--write-example", process.stdout)

    def test_cli_write_example_builds_valid_api_package(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            process = subprocess.run(
                [
                    sys.executable,
                    str(ARTIFACT),
                    "--write-example",
                    str(root / "sample"),
                    "--output-dir",
                    str(root / "api-package"),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            payload = json.loads(process.stdout)

            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertTrue(payload["valid"])
            self.assertTrue((root / "api-package" / "fastapi-delivery-api" / "api.py").is_file())
            self.assertTrue((root / "api-package" / "fastapi-delivery-api" / "openapi_schema.json").is_file())

    def test_cli_fail_on_invalid_returns_upstream_block_exit_code(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            sample = ENDPOINT.write_sample_api_inputs(root / "sample")
            (sample["scheduled_package_dir"] / "run_history.csv").unlink()
            process = subprocess.run(
                [
                    sys.executable,
                    str(ARTIFACT),
                    "--scheduled-package-dir",
                    str(sample["scheduled_package_dir"]),
                    "--api-contract",
                    str(sample["api_contract_path"]),
                    "--output-dir",
                    str(root / "api-package"),
                    "--fail-on-invalid",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            payload = json.loads(process.stdout)

            self.assertEqual(process.returncode, ENDPOINT.API_EXIT_CODE_POLICY["upstream_package_block"])
            self.assertFalse(payload["valid"])
            self.assertEqual(payload["status"], "upstream_package_block")

    def test_code_example_runs_and_reports_fastapi_summary(self) -> None:
        process = subprocess.run(
            [sys.executable, str(CODE)],
            check=False,
            capture_output=True,
            text=True,
        )
        payload = json.loads(process.stdout)

        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertTrue(payload["valid"])
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["health_status_code"], 200)
        self.assertEqual(payload["health_freshness_state"], "fresh")
        self.assertGreaterEqual(payload["run_count"], 1)
        self.assertEqual(payload["unknown_run_status_code"], 404)
        self.assertEqual(payload["audit_blocking_errors"], [])


if __name__ == "__main__":
    unittest.main()
