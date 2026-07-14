from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "docker_packaging_audit.py"
CODE = ROOT / "code" / "main.py"
SPEC = importlib.util.spec_from_file_location("docker_packaging_audit", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
DOCKER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = DOCKER
SPEC.loader.exec_module(DOCKER)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_sample(root: Path):
    sample = DOCKER.write_sample_docker_inputs(root / "sample")
    result = DOCKER.build_docker_packaging_audit(
        api_package_dir=sample["api_package_dir"],
        container_contract_path=sample["container_contract_path"],
        output_dir=root / "docker-package",
    )
    return sample, result


class DockerPackagingAuditTest(unittest.TestCase):
    def test_sample_docker_package_writes_required_files_and_audit(self) -> None:
        with TemporaryDirectory() as directory:
            _sample, result = build_sample(Path(directory))

            self.assertTrue(result.valid)
            self.assertEqual(result.status, "success")
            for relative in [
                "Dockerfile",
                ".dockerignore",
                "container_contract.json",
                "docker_contract_tests.json",
                "docker_build_context_report.json",
                "docker_run_manifest.json",
                "docker_audit.json",
                "docker_manifest.json",
                "docker_runbook.md",
                "app/api.py",
                "app/api_manifest.json",
                "app/api_data/run_history.csv",
            ]:
                self.assertTrue((result.package_dir / relative).is_file(), relative)

    def test_default_contract_declares_local_only_runtime_and_context_policy(self) -> None:
        contract = DOCKER.default_container_contract()

        self.assertEqual(DOCKER.container_contract_errors(contract), [])
        self.assertEqual(contract["base_image"], "python:3.12-slim")
        self.assertEqual(contract["runtime"]["working_dir"], "/app")
        self.assertEqual(contract["runtime"]["port"], 8000)
        self.assertEqual(contract["runtime"]["user"], "appuser")
        self.assertTrue(contract["image_claim_boundary"]["local_only"])
        self.assertTrue(contract["image_claim_boundary"]["no_registry_push"])
        for pattern in DOCKER.REQUIRED_DOCKERIGNORE_PATTERNS:
            self.assertIn(pattern, contract["build_context"]["exclude_required"])

    def test_dockerfile_uses_slim_python_non_root_user_and_uvicorn_command(self) -> None:
        with TemporaryDirectory() as directory:
            _sample, result = build_sample(Path(directory))
            dockerfile = result.dockerfile_path.read_text(encoding="utf-8")

            self.assertEqual(DOCKER.dockerfile_marker_errors(dockerfile), [])
            self.assertEqual(DOCKER.forbidden_dockerfile_markers(dockerfile), [])
            self.assertIn("FROM python:3.12-slim", dockerfile)
            self.assertIn("USER appuser", dockerfile)
            self.assertIn('CMD ["uvicorn", "api:app"', dockerfile)
            self.assertNotIn("COPY . .", dockerfile)
            self.assertNotIn("ARG TOKEN", dockerfile)

    def test_dockerignore_blocks_credentials_caches_raw_data_and_metadata(self) -> None:
        with TemporaryDirectory() as directory:
            _sample, result = build_sample(Path(directory))
            dockerignore = result.dockerignore_path.read_text(encoding="utf-8")

            self.assertEqual(DOCKER.dockerignore_pattern_errors(dockerignore), [])
            for pattern in [".env", "*.pem", "*.key", "secrets/", "__pycache__/", "*.pyc", "data/raw/", "*.parquet", "*.xlsx"]:
                self.assertIn(pattern, dockerignore)
            self.assertIn("docker_audit.json", dockerignore)
            self.assertIn("container_contract.json", dockerignore)

    def test_context_report_is_minimal_small_and_forbidden_free(self) -> None:
        with TemporaryDirectory() as directory:
            _sample, result = build_sample(Path(directory))
            context_report = read_json(result.context_report_path)

            self.assertEqual(DOCKER.context_report_errors(context_report, DOCKER.default_container_contract()), [])
            self.assertEqual(set(context_report["included_top_level"]), {".dockerignore", "Dockerfile", "app"})
            self.assertEqual(context_report["forbidden_included_paths"], [])
            self.assertLess(context_report["included_total_bytes"], DOCKER.default_container_contract()["build_context"]["max_context_bytes"])
            self.assertNotIn("docker_audit.json", {item["path"] for item in context_report["included"]})

    def test_source_secret_candidates_are_not_copied_into_build_context(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            sample = DOCKER.write_sample_docker_inputs(root / "sample")
            (sample["api_package_dir"] / ".env").write_text("TOKEN=do-not-copy\n", encoding="utf-8")
            (sample["api_package_dir"] / "secret.key").write_text("not-a-real-key\n", encoding="utf-8")

            result = DOCKER.build_docker_packaging_audit(
                api_package_dir=sample["api_package_dir"],
                container_contract_path=sample["container_contract_path"],
                output_dir=root / "docker-package",
            )
            context_report = read_json(result.context_report_path)

            self.assertTrue(result.valid)
            self.assertIn(".env", context_report["source_forbidden_candidates"])
            self.assertIn("secret.key", context_report["source_forbidden_candidates"])
            self.assertEqual(context_report["forbidden_included_paths"], [])
            self.assertFalse((result.package_dir / "app" / ".env").exists())

    def test_run_manifest_preserves_local_fastapi_manifest_hash(self) -> None:
        with TemporaryDirectory() as directory:
            sample, result = build_sample(Path(directory))
            run_manifest = read_json(result.run_manifest_path)

            source_hash = DOCKER.sha256_file(sample["api_package_dir"] / "api_manifest.json")
            packaged_hash = DOCKER.sha256_file(result.package_dir / "app" / "api_manifest.json")
            self.assertEqual(source_hash, packaged_hash)
            self.assertTrue(run_manifest["equivalence"]["hashes_match"])
            self.assertEqual(run_manifest["equivalence"]["expected_container_manifest_sha256"], source_hash)
            self.assertEqual(run_manifest["equivalence"]["packaged_manifest_sha256"], packaged_hash)

    def test_run_manifest_is_local_only_and_has_no_push_command(self) -> None:
        with TemporaryDirectory() as directory:
            _sample, result = build_sample(Path(directory))
            run_manifest = read_json(result.run_manifest_path)
            command_text = " ".join(run_manifest["build_command"] + run_manifest["run_command"])

            self.assertEqual(run_manifest["build_command"][:2], ["docker", "build"])
            self.assertEqual(run_manifest["run_command"][:2], ["docker", "run"])
            self.assertTrue(run_manifest["boundary"]["local_only"])
            self.assertTrue(run_manifest["boundary"]["no_registry_push"])
            self.assertNotIn("push", command_text)
            self.assertIn("trial-onboarding-delivery-api:local", command_text)

    def test_invalid_upstream_fastapi_package_blocks_docker_packaging(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            sample = DOCKER.write_sample_docker_inputs(root / "sample")
            api_audit_path = sample["api_package_dir"] / "api_audit.json"
            api_audit = read_json(api_audit_path)
            api_audit["valid"] = False
            api_audit["status"] = "api_contract_block"
            api_audit["summary"]["blocking_errors"] = ["tampered_for_docker_test"]
            write_json(api_audit_path, api_audit)

            result = DOCKER.build_docker_packaging_audit(
                api_package_dir=sample["api_package_dir"],
                container_contract_path=sample["container_contract_path"],
                output_dir=root / "docker-package",
            )
            audit = read_json(result.audit_path)

            self.assertFalse(result.valid)
            self.assertEqual(result.status, "upstream_package_block")
            self.assertIn("api_audit_status_must_be_success", audit["summary"]["api_package_errors"])
            self.assertIn("upstream_fastapi_package_is_valid_before_container_packaging", audit["summary"]["blocking_errors"])

    def test_missing_fastapi_manifest_blocks_docker_packaging(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            sample = DOCKER.write_sample_docker_inputs(root / "sample")
            (sample["api_package_dir"] / "api_manifest.json").unlink()

            result = DOCKER.build_docker_packaging_audit(
                api_package_dir=sample["api_package_dir"],
                container_contract_path=sample["container_contract_path"],
                output_dir=root / "docker-package",
            )

            self.assertFalse(result.valid)
            self.assertEqual(result.status, "upstream_package_block")
            self.assertIn("missing_api_package_file:api_manifest.json", read_json(result.audit_path)["summary"]["api_package_errors"])

    def test_bad_container_contract_blocks_before_claiming_success(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            sample = DOCKER.write_sample_docker_inputs(root / "sample")
            contract = DOCKER.default_container_contract()
            contract["base_image"] = "python:latest"
            contract["image_claim_boundary"]["no_registry_push"] = False
            bad_contract_path = root / "bad_container_contract.json"
            write_json(bad_contract_path, contract)

            result = DOCKER.build_docker_packaging_audit(
                api_package_dir=sample["api_package_dir"],
                container_contract_path=bad_contract_path,
                output_dir=root / "docker-package",
            )
            audit = read_json(result.audit_path)

            self.assertFalse(result.valid)
            self.assertEqual(result.status, "container_contract_block")
            self.assertIn("base_image_must_pin_python_3_12_slim", audit["summary"]["container_contract_errors"])
            self.assertIn("image_boundary_no_registry_push_required", audit["summary"]["container_contract_errors"])

    def test_dockerfile_checker_catches_broad_copy_root_and_secret_patterns(self) -> None:
        source = """
FROM python:latest
WORKDIR /app
COPY . .
ARG TOKEN
USER root
CMD ["python", "server.py"]
"""

        self.assertIn("FROM python:3.12-slim", DOCKER.dockerfile_marker_errors(source))
        forbidden = DOCKER.forbidden_dockerfile_markers(source)
        self.assertIn("COPY . .", forbidden)
        self.assertIn("USER root", forbidden)
        self.assertIn("ARG TOKEN", forbidden)

    def test_dockerignore_checker_catches_missing_secret_and_cache_patterns(self) -> None:
        dockerignore = "Dockerfile\napp/\n"

        errors = DOCKER.dockerignore_pattern_errors(dockerignore)

        self.assertIn(".env", errors)
        self.assertIn("*.pem", errors)
        self.assertIn("__pycache__/", errors)
        self.assertIn("data/raw/", errors)

    def test_context_matcher_handles_nested_cache_secret_and_raw_data_patterns(self) -> None:
        self.assertTrue(DOCKER.pattern_matches("app/__pycache__/api.pyc", "**/__pycache__/"))
        self.assertTrue(DOCKER.pattern_matches("app/api.pyc", "*.pyc"))
        self.assertTrue(DOCKER.pattern_matches("secrets/token.txt", "secrets/"))
        self.assertTrue(DOCKER.pattern_matches("data/raw/export.parquet", "data/raw/"))
        self.assertTrue(DOCKER.pattern_matches("data/raw/export.parquet", "*.parquet"))

    def test_contract_tests_and_runbook_name_review_expectations(self) -> None:
        with TemporaryDirectory() as directory:
            _sample, result = build_sample(Path(directory))
            contract_tests = read_json(result.package_dir / "docker_contract_tests.json")
            runbook = (result.package_dir / "docker_runbook.md").read_text(encoding="utf-8")

            self.assertGreaterEqual(len(contract_tests["tests"]), 6)
            self.assertIn("build_context_is_minimal", {item["id"] for item in contract_tests["tests"]})
            self.assertIn("docker build --pull", runbook)
            self.assertIn("docker run --rm", runbook)
            self.assertIn("Do not add runtime secrets", runbook)

    def test_manifest_hashes_dockerfile_context_run_manifest_audit_and_app(self) -> None:
        with TemporaryDirectory() as directory:
            _sample, result = build_sample(Path(directory))
            manifest = read_json(result.manifest_path)

            outputs = manifest["outputs"]
            self.assertEqual(manifest["renderer_used"], "docker_packaging_audit")
            self.assertEqual(manifest["hash_algorithm"], "sha256")
            self.assertEqual(len(outputs["Dockerfile"]["sha256"]), 64)
            self.assertEqual(len(outputs["docker_build_context_report_json"]["sha256"]), 64)
            self.assertEqual(len(outputs["docker_run_manifest_json"]["sha256"]), 64)
            self.assertEqual(len(outputs["docker_audit_json"]["sha256"]), 64)
            self.assertEqual(len(outputs["app_api_manifest_json"]["sha256"]), 64)

    def test_cli_help_names_docker_arguments(self) -> None:
        process = subprocess.run(
            [sys.executable, str(ARTIFACT), "--help"],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(process.returncode, 0)
        self.assertIn("--api-package-dir", process.stdout)
        self.assertIn("--container-contract", process.stdout)
        self.assertIn("--fail-on-invalid", process.stdout)
        self.assertIn("--write-example", process.stdout)

    def test_cli_write_example_builds_valid_docker_package(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            process = subprocess.run(
                [
                    sys.executable,
                    str(ARTIFACT),
                    "--write-example",
                    str(root / "sample"),
                    "--output-dir",
                    str(root / "docker-package"),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            payload = json.loads(process.stdout)

            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertTrue(payload["valid"])
            self.assertTrue((root / "docker-package" / "docker-delivery-package" / "Dockerfile").is_file())
            self.assertTrue((root / "docker-package" / "docker-delivery-package" / "docker_run_manifest.json").is_file())

    def test_cli_fail_on_invalid_returns_upstream_block_exit_code(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            sample = DOCKER.write_sample_docker_inputs(root / "sample")
            (sample["api_package_dir"] / "api_manifest.json").unlink()
            process = subprocess.run(
                [
                    sys.executable,
                    str(ARTIFACT),
                    "--api-package-dir",
                    str(sample["api_package_dir"]),
                    "--container-contract",
                    str(sample["container_contract_path"]),
                    "--output-dir",
                    str(root / "docker-package"),
                    "--fail-on-invalid",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            payload = json.loads(process.stdout)

            self.assertEqual(process.returncode, DOCKER.DOCKER_EXIT_CODE_POLICY["upstream_package_block"])
            self.assertFalse(payload["valid"])
            self.assertEqual(payload["status"], "upstream_package_block")

    def test_code_example_runs_and_reports_docker_packaging_summary(self) -> None:
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
        self.assertEqual(set(payload["context_top_level"]), {".dockerignore", "Dockerfile", "app"})
        self.assertTrue(payload["manifest_hashes_match"])
        self.assertIn("docker build --pull", payload["build_command"])
        self.assertEqual(payload["audit_blocking_errors"], [])


if __name__ == "__main__":
    unittest.main()
