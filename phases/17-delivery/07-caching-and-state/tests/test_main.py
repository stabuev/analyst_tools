from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "streamlit_cache_state_auditor.py"
CODE = ROOT / "code" / "main.py"
SPEC = importlib.util.spec_from_file_location("streamlit_cache_state_auditor", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
BUILDER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BUILDER
SPEC.loader.exec_module(BUILDER)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_sample(root: Path):
    sample = BUILDER.write_sample_cache_state_inputs(root / "sample")
    result = BUILDER.build_cache_state_package(
        app_dir=sample["app_dir"],
        cache_state_contract_path=sample["cache_state_contract_path"],
        freshness_policy_path=sample["freshness_policy_path"],
        output_dir=root / "cache-state-app",
    )
    return sample, result


def build_with_policy(root: Path, policy_update: dict):
    sample = BUILDER.write_sample_cache_state_inputs(root / "sample")
    policy = read_json(sample["freshness_policy_path"])
    policy.update(policy_update)
    write_json(sample["freshness_policy_path"], policy)
    result = BUILDER.build_cache_state_package(
        app_dir=sample["app_dir"],
        cache_state_contract_path=sample["cache_state_contract_path"],
        freshness_policy_path=sample["freshness_policy_path"],
        output_dir=root / "cache-state-app",
    )
    return sample, result


def build_with_contract(root: Path, mutate):
    sample = BUILDER.write_sample_cache_state_inputs(root / "sample")
    contract = read_json(sample["cache_state_contract_path"])
    mutate(contract)
    write_json(sample["cache_state_contract_path"], contract)
    result = BUILDER.build_cache_state_package(
        app_dir=sample["app_dir"],
        cache_state_contract_path=sample["cache_state_contract_path"],
        freshness_policy_path=sample["freshness_policy_path"],
        output_dir=root / "cache-state-app",
    )
    return sample, result


def check_by_id(audit: dict, check_id: str) -> dict:
    return next(check for check in audit["checks"] if check["id"] == check_id)


def re_audit(result) -> dict:
    manifest = read_json(result.manifest_path)
    return BUILDER.audit_cache_state_package(
        output_dir=result.output_dir,
        cache_state_contract=read_json(result.cache_state_contract_path),
        freshness_policy=read_json(result.freshness_policy_path),
        output_entries=manifest["outputs"],
    )


class StreamlitCacheStateAuditorTest(unittest.TestCase):
    def test_sample_cache_state_package_is_valid_and_writes_files(self) -> None:
        with TemporaryDirectory() as directory:
            _sample, result = build_sample(Path(directory))

            self.assertTrue(result.audit["valid"])
            self.assertEqual(result.audit["readiness_status"], "ready")
            for path in [
                result.app_path,
                result.cache_state_contract_path,
                result.freshness_policy_path,
                result.freshness_report_path,
                result.audit_path,
                result.manifest_path,
                result.output_dir / "cache_state_runbook.md",
                result.output_dir / "app_contract.json",
                result.output_dir / "app_data" / "metric_summary.csv",
                result.output_dir / "app_data" / "claim_evidence_matrix.csv",
                result.output_dir / "app_data" / "plotly_figure_spec.json",
                result.output_dir / "downloads" / "stakeholder_app_bundle.zip",
            ]:
                self.assertTrue(path.is_file(), path)

    def test_generated_app_uses_streamlit_cache_state_and_compiles(self) -> None:
        with TemporaryDirectory() as directory:
            _sample, result = build_sample(Path(directory))
            app_source = result.app_path.read_text(encoding="utf-8")

            for marker in BUILDER.REQUIRED_SOURCE_MARKERS:
                self.assertIn(marker, app_source)
            process = subprocess.run(
                [sys.executable, "-m", "py_compile", str(result.app_path)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(process.returncode, 0, process.stderr)

    def test_cache_state_contract_separates_data_resource_session_and_invalidation(self) -> None:
        with TemporaryDirectory() as directory:
            _sample, result = build_sample(Path(directory))
            contract = read_json(result.cache_state_contract_path)
            functions = {item["name"]: item for item in contract["cache_functions"]}

            self.assertEqual(functions["load_csv_cached"]["decorator"], "st.cache_data")
            self.assertEqual(functions["load_json_cached"]["decorator"], "st.cache_data")
            self.assertEqual(functions["load_figure_resource"]["decorator"], "st.cache_resource")
            self.assertEqual(functions["load_figure_resource"]["kind"], "resource")
            self.assertEqual(sorted(functions["load_csv_cached"]["hash_inputs"]), ["checksum", "path"])
            self.assertTrue(contract["freshness_panel"]["disable_download_when_stale"])
            self.assertTrue(contract["invalidation_policy"]["checksum_invalidation_required"])
            self.assertTrue(contract["invalidation_policy"]["manual_cache_clear_required"])
            self.assertEqual(
                {item["key"] for item in contract["session_state_keys"]},
                set(BUILDER.REQUIRED_SESSION_STATE_KEYS),
            )

    def test_freshness_report_tracks_current_input_checksums(self) -> None:
        with TemporaryDirectory() as directory:
            _sample, result = build_sample(Path(directory))
            policy = read_json(result.freshness_policy_path)
            report = read_json(result.freshness_report_path)
            inventory = BUILDER.tracked_file_inventory(result.output_dir, policy)

            self.assertEqual(report["input_digest"], BUILDER.input_digest(inventory))
            self.assertEqual(len(report["tracked_files"]), len(BUILDER.TRACKED_INPUT_FILES))
            self.assertTrue(all(len(row["sha256"]) == 64 and not row["missing"] for row in report["tracked_files"]))

    def test_changed_app_input_after_build_blocks_checksum_freshness(self) -> None:
        with TemporaryDirectory() as directory:
            _sample, result = build_sample(Path(directory))
            metric_path = result.output_dir / "app_data" / "metric_summary.csv"
            metric_path.write_text(metric_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")

            audit = re_audit(result)

            self.assertFalse(audit["valid"])
            self.assertFalse(check_by_id(audit, "freshness_report_matches_current_input_checksums")["valid"])

    def test_stale_input_window_blocks_delivery(self) -> None:
        with TemporaryDirectory() as directory:
            _sample, result = build_with_policy(
                Path(directory),
                {"source_snapshot_utc": "2026-01-01T00:00:00Z", "checked_at_utc": "2026-01-01T02:00:00Z"},
            )

            self.assertFalse(result.audit["valid"])
            check = check_by_id(result.audit, "freshness_report_is_not_stale")
            self.assertFalse(check["valid"])
            self.assertEqual(check["observed"], ["input_age_exceeds_policy"])

    def test_missing_data_cache_ttl_blocks_policy(self) -> None:
        with TemporaryDirectory() as directory:
            _sample, result = build_with_policy(Path(directory), {"data_cache_ttl_seconds": 0})

            self.assertFalse(result.audit["valid"])
            check = check_by_id(result.audit, "freshness_policy_defines_ttl_max_entries_and_stale_gate")
            self.assertIn("data_cache_ttl_seconds_must_be_positive", check["observed"])

    def test_data_cache_ttl_cannot_exceed_freshness_window(self) -> None:
        with TemporaryDirectory() as directory:
            _sample, result = build_with_policy(
                Path(directory),
                {"max_input_age_seconds": 300, "data_cache_ttl_seconds": 900},
            )

            self.assertFalse(result.audit["valid"])
            check = check_by_id(result.audit, "freshness_policy_defines_ttl_max_entries_and_stale_gate")
            self.assertIn("data_cache_ttl_cannot_exceed_freshness_window", check["observed"])

    def test_missing_resource_cache_function_blocks_contract(self) -> None:
        def mutate(contract: dict) -> None:
            contract["cache_functions"] = [
                item for item in contract["cache_functions"] if item["name"] != "load_figure_resource"
            ]

        with TemporaryDirectory() as directory:
            _sample, result = build_with_contract(Path(directory), mutate)

            self.assertFalse(result.audit["valid"])
            check = check_by_id(result.audit, "cache_state_contract_declares_data_resource_session_and_invalidation")
            self.assertEqual(check["observed"]["cache_errors"], [{"name": "load_figure_resource", "error": "missing"}])

    def test_wrong_cache_decorator_blocks_contract(self) -> None:
        def mutate(contract: dict) -> None:
            for item in contract["cache_functions"]:
                if item["name"] == "load_figure_resource":
                    item["decorator"] = "st.cache_data"

        with TemporaryDirectory() as directory:
            _sample, result = build_with_contract(Path(directory), mutate)

            self.assertFalse(result.audit["valid"])
            check = check_by_id(result.audit, "cache_state_contract_declares_data_resource_session_and_invalidation")
            self.assertEqual(check["observed"]["cache_errors"][0]["name"], "load_figure_resource")

    def test_missing_session_state_key_blocks_contract(self) -> None:
        def mutate(contract: dict) -> None:
            contract["session_state_keys"] = [
                item for item in contract["session_state_keys"] if item["key"] != "manual_refresh_count"
            ]

        with TemporaryDirectory() as directory:
            _sample, result = build_with_contract(Path(directory), mutate)

            self.assertFalse(result.audit["valid"])
            check = check_by_id(result.audit, "session_state_keys_are_session_scoped_and_non_sensitive")
            self.assertEqual(check["observed"], [{"key": "manual_refresh_count", "error": "missing"}])

    def test_sensitive_session_state_name_blocks_contract(self) -> None:
        def mutate(contract: dict) -> None:
            contract["session_state_keys"].append(
                {
                    "key": "user_email",
                    "scope": "session",
                    "purpose": "Unsafe user-specific field.",
                    "contains_sensitive_data": False,
                }
            )

        with TemporaryDirectory() as directory:
            _sample, result = build_with_contract(Path(directory), mutate)

            self.assertFalse(result.audit["valid"])
            check = check_by_id(result.audit, "session_state_keys_are_session_scoped_and_non_sensitive")
            self.assertEqual(check["observed"], [{"sensitive_key_names": ["user_email"]}])

    def test_app_without_manual_cache_clear_marker_blocks_delivery(self) -> None:
        with TemporaryDirectory() as directory:
            _sample, result = build_sample(Path(directory))
            source = result.app_path.read_text(encoding="utf-8")
            result.app_path.write_text(source.replace("load_csv_cached.clear()", "# load_csv_cached clear removed"), encoding="utf-8")

            audit = re_audit(result)

            self.assertFalse(audit["valid"])
            check = check_by_id(audit, "generated_app_uses_streamlit_cache_state_and_freshness_panel")
            self.assertIn("load_csv_cached.clear()", check["observed"])

    def test_cached_loaders_must_include_checksum_parameters(self) -> None:
        with TemporaryDirectory() as directory:
            _sample, result = build_sample(Path(directory))
            source = result.app_path.read_text(encoding="utf-8")
            result.app_path.write_text(
                source.replace('checksum_for(freshness_report, "app_data/metric_summary.csv")', '"fixed-metric-cache-key"'),
                encoding="utf-8",
            )

            audit = re_audit(result)

            self.assertFalse(audit["valid"])
            check = check_by_id(audit, "cached_loaders_use_checksum_parameters_for_invalidation")
            self.assertIn('checksum_for(freshness_report, "app_data/metric_summary.csv")', check["observed"])

    def test_forbidden_disk_persist_or_secrets_pattern_blocks_app_source(self) -> None:
        with TemporaryDirectory() as directory:
            _sample, result = build_sample(Path(directory))
            source = result.app_path.read_text(encoding="utf-8")
            result.app_path.write_text(source + '\n# forbidden example: persist="disk"\n', encoding="utf-8")

            audit = re_audit(result)

            self.assertFalse(audit["valid"])
            check = check_by_id(audit, "cached_app_source_avoids_forbidden_runtime_patterns")
            self.assertEqual(check["observed"], ['persist="disk"'])

    def test_stale_warning_and_download_disable_are_in_generated_app(self) -> None:
        with TemporaryDirectory() as directory:
            _sample, result = build_sample(Path(directory))
            app_source = result.app_path.read_text(encoding="utf-8")

            self.assertIn("st.sidebar.warning", app_source)
            self.assertIn('st.error("This app is using stale inputs', app_source)
            self.assertIn('disabled=freshness_report["stale"]', app_source)
            self.assertTrue(check_by_id(result.audit, "stale_outputs_warn_and_disable_downloads")["valid"])

    def test_invalid_upstream_app_audit_blocks_cache_state_layer(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            sample = BUILDER.write_sample_cache_state_inputs(root / "sample")
            app_audit_path = sample["app_dir"] / "app_audit.json"
            app_audit = read_json(app_audit_path)
            app_audit["valid"] = False
            app_audit["summary"]["blocking_errors"] = ["app_contract_tampered"]
            write_json(app_audit_path, app_audit)

            result = BUILDER.build_cache_state_package(
                app_dir=sample["app_dir"],
                cache_state_contract_path=sample["cache_state_contract_path"],
                freshness_policy_path=sample["freshness_policy_path"],
                output_dir=root / "cache-state-app",
            )

            self.assertFalse(result.audit["valid"])
            self.assertFalse(check_by_id(result.audit, "upstream_app_audit_is_valid")["valid"])

    def test_missing_required_app_file_blocks_cache_state_layer(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            sample = BUILDER.write_sample_cache_state_inputs(root / "sample")
            (sample["app_dir"] / "app_data" / "metric_summary.csv").unlink()

            result = BUILDER.build_cache_state_package(
                app_dir=sample["app_dir"],
                cache_state_contract_path=sample["cache_state_contract_path"],
                freshness_policy_path=sample["freshness_policy_path"],
                output_dir=root / "cache-state-app",
            )

            self.assertFalse(result.audit["valid"])
            self.assertFalse(check_by_id(result.audit, "source_streamlit_app_bundle_is_complete")["valid"])
            self.assertFalse(check_by_id(result.audit, "freshness_report_matches_current_input_checksums")["valid"])

    def test_manifest_records_streamlit_version_and_output_hashes(self) -> None:
        with TemporaryDirectory() as directory:
            _sample, result = build_sample(Path(directory))
            manifest = read_json(result.manifest_path)

            self.assertEqual(manifest["renderer_used"], "streamlit_cache_state_auditor")
            self.assertEqual(manifest["hash_algorithm"], "sha256")
            self.assertTrue(manifest["streamlit_version"])
            for key in [
                "streamlit_app",
                "cache_state_contract",
                "freshness_policy",
                "freshness_report",
                "cache_state_runbook",
                "cache_state_audit",
            ]:
                self.assertEqual(len(manifest["outputs"][key]["sha256"]), 64)

    def test_cli_write_example_builds_ready_package(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            process = subprocess.run(
                [
                    sys.executable,
                    str(ARTIFACT),
                    "--write-example",
                    str(root / "sample"),
                    "--output-dir",
                    str(root / "out"),
                    "--fail-on-invalid",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            payload = json.loads(process.stdout)

            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertTrue(payload["valid"])
            self.assertEqual(payload["readiness_status"], "ready")
            self.assertTrue((root / "out" / "cache_state_manifest.json").is_file())

    def test_cli_fail_on_invalid_returns_two_for_stale_inputs(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            process = subprocess.run(
                [
                    sys.executable,
                    str(ARTIFACT),
                    "--write-example",
                    str(root / "sample"),
                    "--output-dir",
                    str(root / "out"),
                    "--checked-at",
                    "2026-01-01T02:00:00Z",
                    "--fail-on-invalid",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            payload = json.loads(process.stdout)

            self.assertEqual(process.returncode, 2, process.stderr)
            self.assertFalse(payload["valid"])
            self.assertIn("freshness_report_is_not_stale", payload["blocking_errors"])

    def test_code_example_runs_and_reports_cache_state_summary(self) -> None:
        process = subprocess.run(
            [sys.executable, str(CODE)],
            check=False,
            capture_output=True,
            text=True,
        )
        payload = json.loads(process.stdout)

        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertTrue(payload["valid"])
        self.assertFalse(payload["stale"])
        self.assertEqual(payload["renderer_used"], "streamlit_cache_state_auditor")
        self.assertIn("freshness_report.json", payload["files"])


if __name__ == "__main__":
    unittest.main()
