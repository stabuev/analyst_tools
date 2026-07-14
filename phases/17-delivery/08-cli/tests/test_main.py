from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "delivery_cli_runner.py"
CODE = ROOT / "code" / "main.py"
SPEC = importlib.util.spec_from_file_location("delivery_cli_runner", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
RUNNER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = RUNNER
SPEC.loader.exec_module(RUNNER)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_sample(root: Path):
    sample = RUNNER.write_sample_cli_inputs(root / "sample")
    result = RUNNER.run_delivery_cli(
        app_dir=sample["app_dir"],
        cache_state_contract_path=sample["cache_state_contract_path"],
        freshness_policy_path=sample["freshness_policy_path"],
        cli_contract_path=sample["cli_contract_path"],
        output_dir=root / "published",
        argv=["test"],
    )
    return sample, result


class DeliveryCliRunnerTest(unittest.TestCase):
    def test_sample_cli_publishes_valid_package_and_required_files(self) -> None:
        with TemporaryDirectory() as directory:
            _sample, result = build_sample(Path(directory))

            self.assertEqual(result.status, "success")
            self.assertEqual(result.exit_code, RUNNER.EXIT_CODE_POLICY["success"])
            self.assertTrue(result.published)
            for relative in [
                "cli_run_report.json",
                "cli_publish_manifest.json",
                "delivery_cli_contract.json",
                "cache_state_manifest.json",
                "cache_state_audit.json",
                "freshness_report.json",
                "streamlit_app.py",
                "downloads/stakeholder_app_bundle.zip",
            ]:
                self.assertTrue((result.output_dir / relative).is_file(), relative)

    def test_check_mode_validates_without_publishing_output_dir(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            sample = RUNNER.write_sample_cli_inputs(root / "sample")
            output_dir = root / "would-be-published"

            result = RUNNER.run_delivery_cli(
                app_dir=sample["app_dir"],
                cache_state_contract_path=sample["cache_state_contract_path"],
                freshness_policy_path=sample["freshness_policy_path"],
                cli_contract_path=sample["cli_contract_path"],
                output_dir=output_dir,
                check_mode=True,
                argv=["--check"],
            )

            self.assertEqual(result.status, "success")
            self.assertFalse(result.published)
            self.assertFalse(output_dir.exists())
            self.assertIsNone(result.manifest_path)

    def test_cli_contract_declares_paths_modes_atomic_publish_and_exit_codes(self) -> None:
        contract = RUNNER.default_cli_contract()

        self.assertEqual(RUNNER.cli_contract_errors(contract), [])
        self.assertEqual(set(contract["supported_modes"]), {"check", "publish"})
        self.assertTrue(contract["path_policy"]["explicit_input_paths_required"])
        self.assertTrue(contract["path_policy"]["no_implicit_cwd_inputs"])
        self.assertTrue(contract["publish_policy"]["build_in_staging_directory"])
        self.assertTrue(contract["publish_policy"]["atomic_replace_required"])
        self.assertEqual(contract["exit_code_policy"], RUNNER.EXIT_CODE_POLICY)

    def test_generated_cli_uses_argparse_check_mode_and_compiles(self) -> None:
        source = ARTIFACT.read_text(encoding="utf-8")

        for marker in RUNNER.REQUIRED_CLI_SOURCE_MARKERS:
            self.assertIn(marker, source)
        for pattern in RUNNER.FORBIDDEN_CLI_PATTERNS:
            self.assertNotIn(pattern, source)
        process = subprocess.run(
            [sys.executable, "-m", "py_compile", str(ARTIFACT)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(process.returncode, 0, process.stderr)

    def test_publish_manifest_records_inputs_outputs_hashes_and_atomic_strategy(self) -> None:
        with TemporaryDirectory() as directory:
            _sample, result = build_sample(Path(directory))
            manifest = read_json(result.manifest_path)

            self.assertEqual(manifest["renderer_used"], "delivery_cli_runner")
            self.assertEqual(manifest["hash_algorithm"], "sha256")
            self.assertEqual(manifest["atomic_publish"]["strategy"], "stage_then_os_replace")
            self.assertTrue(manifest["atomic_publish"]["staging_directory_used"])
            self.assertIn("app_dir_app_manifest", manifest["inputs"])
            for key in [
                "cli_run_report_json",
                "delivery_cli_contract_json",
                "cache_state_manifest_json",
                "freshness_report_json",
                "streamlit_app_py",
            ]:
                self.assertEqual(len(manifest["outputs"][key]["sha256"]), 64)

    def test_report_applies_exit_policy_and_reuses_cache_state_audit(self) -> None:
        with TemporaryDirectory() as directory:
            _sample, result = build_sample(Path(directory))
            report = read_json(result.report_path)

            self.assertEqual(report["status"], "success")
            self.assertEqual(report["exit_code"], RUNNER.EXIT_CODE_POLICY["success"])
            self.assertTrue(report["cache_state_audit"]["valid"])
            self.assertTrue(all(check["valid"] for check in report["checks"]))
            self.assertEqual(report["summary"]["blocking_errors"], [])

    def test_existing_output_requires_overwrite_and_keeps_existing_package(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            sample, result = build_sample(root)
            sentinel = result.output_dir / "sentinel.txt"
            sentinel.write_text("keep me", encoding="utf-8")

            process = subprocess.run(
                [
                    sys.executable,
                    str(ARTIFACT),
                    "--app-dir",
                    str(sample["app_dir"]),
                    "--cache-state-contract",
                    str(sample["cache_state_contract_path"]),
                    "--freshness-policy",
                    str(sample["freshness_policy_path"]),
                    "--cli-contract",
                    str(sample["cli_contract_path"]),
                    "--output-dir",
                    str(result.output_dir),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            payload = json.loads(process.stdout)

            self.assertEqual(process.returncode, RUNNER.EXIT_CODE_POLICY["system_error"], process.stderr)
            self.assertEqual(payload["status"], "system_error")
            self.assertTrue(sentinel.is_file())
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep me")

    def test_overwrite_replaces_existing_output_after_successful_staged_build(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            sample = RUNNER.write_sample_cli_inputs(root / "sample")
            output_dir = root / "published"
            output_dir.mkdir()
            (output_dir / "old.txt").write_text("old", encoding="utf-8")

            result = RUNNER.run_delivery_cli(
                app_dir=sample["app_dir"],
                cache_state_contract_path=sample["cache_state_contract_path"],
                freshness_policy_path=sample["freshness_policy_path"],
                cli_contract_path=sample["cli_contract_path"],
                output_dir=output_dir,
                overwrite=True,
                argv=["--overwrite"],
            )

            self.assertTrue(result.published)
            self.assertFalse((output_dir / "old.txt").exists())
            self.assertTrue((output_dir / "cli_publish_manifest.json").is_file())

    def test_data_quality_block_does_not_publish_or_replace_existing_output(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            sample, first = build_sample(root)
            sentinel = first.output_dir / "sentinel.txt"
            sentinel.write_text("still here", encoding="utf-8")
            app_audit_path = sample["app_dir"] / "app_audit.json"
            app_audit = read_json(app_audit_path)
            app_audit["valid"] = False
            app_audit["summary"]["blocking_errors"] = ["app_contract_tampered"]
            write_json(app_audit_path, app_audit)

            result = RUNNER.run_delivery_cli(
                app_dir=sample["app_dir"],
                cache_state_contract_path=sample["cache_state_contract_path"],
                freshness_policy_path=sample["freshness_policy_path"],
                cli_contract_path=sample["cli_contract_path"],
                output_dir=first.output_dir,
                overwrite=True,
                argv=["invalid"],
            )

            self.assertEqual(result.status, "data_quality_block")
            self.assertEqual(result.exit_code, RUNNER.EXIT_CODE_POLICY["data_quality_block"])
            self.assertFalse(result.published)
            self.assertTrue(sentinel.is_file())
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "still here")

    def test_stale_inputs_return_freshness_warning_without_publish_by_default(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            sample = RUNNER.write_sample_cli_inputs(root / "sample")
            output_dir = root / "published"

            result = RUNNER.run_delivery_cli(
                app_dir=sample["app_dir"],
                cache_state_contract_path=sample["cache_state_contract_path"],
                freshness_policy_path=sample["freshness_policy_path"],
                cli_contract_path=sample["cli_contract_path"],
                output_dir=output_dir,
                checked_at_utc="2026-01-01T02:00:00Z",
                argv=["stale"],
            )

            self.assertEqual(result.status, "freshness_warning")
            self.assertEqual(result.exit_code, RUNNER.EXIT_CODE_POLICY["freshness_warning"])
            self.assertFalse(result.published)
            self.assertFalse(output_dir.exists())
            self.assertEqual(result.report["cache_state_audit"]["blocking_errors"], ["freshness_report_is_not_stale"])

    def test_stale_inputs_can_be_explicitly_published_with_warning_exit_code(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            sample = RUNNER.write_sample_cli_inputs(root / "sample")

            result = RUNNER.run_delivery_cli(
                app_dir=sample["app_dir"],
                cache_state_contract_path=sample["cache_state_contract_path"],
                freshness_policy_path=sample["freshness_policy_path"],
                cli_contract_path=sample["cli_contract_path"],
                output_dir=root / "published",
                checked_at_utc="2026-01-01T02:00:00Z",
                allow_freshness_warning=True,
                argv=["--allow-freshness-warning"],
            )
            manifest = read_json(result.manifest_path)
            freshness = read_json(result.output_dir / "freshness_report.json")

            self.assertEqual(result.status, "freshness_warning")
            self.assertEqual(result.exit_code, RUNNER.EXIT_CODE_POLICY["freshness_warning"])
            self.assertTrue(result.published)
            self.assertEqual(manifest["status"], "freshness_warning")
            self.assertTrue(freshness["stale"])

    def test_missing_explicit_input_path_returns_system_error_report(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            result = RUNNER.run_delivery_cli(
                app_dir=root / "missing-app",
                output_dir=root / "published",
                argv=["missing"],
            )

            self.assertEqual(result.status, "system_error")
            self.assertEqual(result.exit_code, RUNNER.EXIT_CODE_POLICY["system_error"])
            self.assertFalse(result.published)
            self.assertEqual(result.report["error"]["code"], "missing_explicit_input_path")
            self.assertFalse((root / "published").exists())

    def test_cli_missing_app_dir_prints_json_without_traceback(self) -> None:
        with TemporaryDirectory() as directory:
            process = subprocess.run(
                [sys.executable, str(ARTIFACT), "--output-dir", str(Path(directory) / "out")],
                check=False,
                capture_output=True,
                text=True,
            )
            payload = json.loads(process.stdout)

            self.assertEqual(process.returncode, RUNNER.EXIT_CODE_POLICY["system_error"])
            self.assertEqual(payload["status"], "system_error")
            self.assertEqual(payload["error"]["code"], "missing_app_dir")
            self.assertNotIn("Traceback", process.stderr)

    def test_cli_help_names_check_publish_and_path_arguments(self) -> None:
        process = subprocess.run(
            [sys.executable, str(ARTIFACT), "--help"],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(process.returncode, 0)
        self.assertIn("--check", process.stdout)
        self.assertIn("--app-dir", process.stdout)
        self.assertIn("--output-dir", process.stdout)
        self.assertIn("--allow-freshness-warning", process.stdout)

    def test_check_mode_can_write_report_path_without_publishing(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            sample = RUNNER.write_sample_cli_inputs(root / "sample")
            report_path = root / "reports" / "check-report.json"
            output_dir = root / "published"

            result = RUNNER.run_delivery_cli(
                app_dir=sample["app_dir"],
                cache_state_contract_path=sample["cache_state_contract_path"],
                freshness_policy_path=sample["freshness_policy_path"],
                cli_contract_path=sample["cli_contract_path"],
                output_dir=output_dir,
                check_mode=True,
                report_path=report_path,
                argv=["--check", "--report"],
            )
            report = read_json(report_path)

            self.assertEqual(result.status, "success")
            self.assertFalse(result.published)
            self.assertTrue(report_path.is_file())
            self.assertFalse(output_dir.exists())
            self.assertTrue(report["check_mode"])

    def test_cli_write_example_publishes_ready_package(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            process = subprocess.run(
                [
                    sys.executable,
                    str(ARTIFACT),
                    "--write-example",
                    str(root / "sample"),
                    "--output-dir",
                    str(root / "published"),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            payload = json.loads(process.stdout)

            self.assertEqual(process.returncode, RUNNER.EXIT_CODE_POLICY["success"], process.stderr)
            self.assertEqual(payload["status"], "success")
            self.assertTrue(payload["published"])
            self.assertTrue((root / "published" / "cli_publish_manifest.json").is_file())

    def test_timestamp_overrides_reach_freshness_report(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            sample = RUNNER.write_sample_cli_inputs(root / "sample")

            result = RUNNER.run_delivery_cli(
                app_dir=sample["app_dir"],
                cache_state_contract_path=sample["cache_state_contract_path"],
                freshness_policy_path=sample["freshness_policy_path"],
                cli_contract_path=sample["cli_contract_path"],
                output_dir=root / "published",
                source_snapshot_utc="2026-01-01T00:00:00Z",
                checked_at_utc="2026-01-01T00:30:00Z",
                argv=["override"],
            )
            freshness = read_json(result.output_dir / "freshness_report.json")

            self.assertEqual(result.status, "success")
            self.assertEqual(freshness["input_age_seconds"], 1800)
            self.assertFalse(freshness["stale"])

    def test_code_example_runs_and_reports_cli_summary(self) -> None:
        process = subprocess.run(
            [sys.executable, str(CODE)],
            check=False,
            capture_output=True,
            text=True,
        )
        payload = json.loads(process.stdout)

        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(payload["check_status"], "success")
        self.assertFalse(payload["check_published"])
        self.assertEqual(payload["publish_status"], "success")
        self.assertTrue(payload["publish_published"])
        self.assertEqual(payload["renderer_used"], "delivery_cli_runner")
        self.assertEqual(payload["atomic_strategy"], "stage_then_os_replace")


if __name__ == "__main__":
    unittest.main()
