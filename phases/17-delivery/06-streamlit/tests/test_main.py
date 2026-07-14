from __future__ import annotations

import csv
import importlib.util
import json
import subprocess
import sys
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "streamlit_stakeholder_app.py"
CODE = ROOT / "code" / "main.py"
SPEC = importlib.util.spec_from_file_location("streamlit_stakeholder_app", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
BUILDER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BUILDER
SPEC.loader.exec_module(BUILDER)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def build_sample(root: Path):
    sample = BUILDER.write_sample_app_inputs(root / "sample")
    result = BUILDER.build_streamlit_app(
        interactive_dir=sample["interactive_dir"],
        app_contract_path=sample["app_contract_path"],
        output_dir=root / "streamlit-app",
    )
    return sample, result


def build_sensitive_sample(root: Path):
    plotly_builder = BUILDER.load_plotly_builder()
    sample = plotly_builder.write_sample_delivery_package(root / "plotly-inputs")
    source_info = plotly_builder.resolve_source_tables(sample["delivery_dir"])
    metric_path = source_info["tables"]["metric_summary"]["path"]
    rows = read_csv(metric_path)
    for row in rows:
        row["user_email"] = "customer@example.com"
    write_csv(metric_path, rows, list(rows[0].keys()))
    appendix = plotly_builder.build_interactive_appendix(
        delivery_dir=sample["delivery_dir"],
        interactive_spec_path=sample["interactive_spec_path"],
        output_dir=root / "interactive-appendix",
    )
    contract_path = root / "app_contract.json"
    BUILDER.write_json(contract_path, BUILDER.default_app_contract())
    result = BUILDER.build_streamlit_app(
        interactive_dir=appendix.output_dir,
        app_contract_path=contract_path,
        output_dir=root / "streamlit-app",
    )
    return sample, appendix, result


def check_by_id(audit: dict, check_id: str) -> dict:
    return next(check for check in audit["checks"] if check["id"] == check_id)


class StreamlitStakeholderAppTest(unittest.TestCase):
    def test_sample_streamlit_app_bundle_is_valid_and_writes_files(self) -> None:
        with TemporaryDirectory() as directory:
            _sample, result = build_sample(Path(directory))

            self.assertTrue(result.audit["valid"])
            self.assertEqual(result.audit["readiness_status"], "ready")
            for path in [
                result.app_path,
                result.contract_path,
                result.filters_audit_path,
                result.download_manifest_path,
                result.download_bundle_path,
                result.audit_path,
                result.manifest_path,
                result.output_dir / "app_runbook.md",
                result.output_dir / "app_data" / "metric_summary.csv",
                result.output_dir / "app_data" / "claim_evidence_matrix.csv",
                result.output_dir / "app_data" / "plotly_figure_spec.json",
                result.output_dir / "app_data" / "static-fallbacks" / "metric_status.svg",
            ]:
                self.assertTrue(path.is_file(), path)

    def test_generated_streamlit_app_uses_required_ui_api_and_compiles(self) -> None:
        with TemporaryDirectory() as directory:
            _sample, result = build_sample(Path(directory))
            app_source = result.app_path.read_text(encoding="utf-8")

            for marker in BUILDER.REQUIRED_STREAMLIT_MARKERS:
                self.assertIn(marker, app_source)
            process = subprocess.run(
                [sys.executable, "-m", "py_compile", str(result.app_path)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(process.returncode, 0, process.stderr)

    def test_app_data_comes_from_precomputed_appendix_without_runtime_recompute(self) -> None:
        with TemporaryDirectory() as directory:
            _sample, result = build_sample(Path(directory))
            manifest = read_json(result.manifest_path)
            contract = read_json(result.contract_path)
            app_source = result.app_path.read_text(encoding="utf-8")

            self.assertEqual(contract["input_policy"]["source_of_truth"], "17-delivery/05-interactive-plotly")
            self.assertTrue(contract["input_policy"]["precomputed_only"])
            self.assertTrue(contract["input_policy"]["forbid_ad_hoc_recompute"])
            self.assertIn("appendix_plotly_figure_spec_json", manifest["inputs"])
            self.assertIn("appendix_interaction_audit_json", manifest["inputs"])
            for pattern in BUILDER.FORBIDDEN_APP_PATTERNS:
                self.assertNotIn(pattern, app_source)

    def test_filters_audit_covers_statuses_and_default_rows(self) -> None:
        with TemporaryDirectory() as directory:
            _sample, result = build_sample(Path(directory))
            audit = read_json(result.filters_audit_path)

            self.assertTrue(audit["valid"])
            self.assertEqual(audit["allowed_filters"], ["all", "ok", "watch", "breached"])
            self.assertEqual(audit["default_status_filter"], ["breached", "watch"])
            self.assertGreater(audit["default_result_rows"], 0)
            self.assertEqual(set(audit["status_values"]), {"breached", "watch"})

    def test_download_bundle_contains_declared_files_with_hashes(self) -> None:
        with TemporaryDirectory() as directory:
            _sample, result = build_sample(Path(directory))
            manifest = read_json(result.download_manifest_path)

            expected_names = sorted(row["path"] for row in manifest["files"])
            with zipfile.ZipFile(result.download_bundle_path) as archive:
                zip_names = sorted(archive.namelist())
            self.assertEqual(zip_names, expected_names)
            self.assertTrue(all(len(row["sha256"]) == 64 and row["bytes"] > 0 for row in manifest["files"]))

    def test_source_links_are_sanitized_and_carry_source_hashes(self) -> None:
        with TemporaryDirectory() as directory:
            _sample, result = build_sample(Path(directory))
            rows = read_csv(result.output_dir / "app_data" / "source_table_links.csv")

            self.assertEqual({row["source_id"] for row in rows}, {"metric_summary", "claim_evidence_matrix"})
            self.assertEqual({row["path"] for row in rows}, {"app_data/metric_summary.csv", "app_data/claim_evidence_matrix.csv"})
            self.assertTrue(all(len(row["source_sha256"]) == 64 for row in rows))
            self.assertFalse(any("/tmp/" in row["path"] or row["path"].startswith("..") for row in rows))

    def test_invalid_upstream_interaction_audit_blocks_app(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            sample = BUILDER.write_sample_app_inputs(root / "sample")
            audit_path = sample["interactive_dir"] / "interaction_audit.json"
            audit = read_json(audit_path)
            audit["valid"] = False
            audit["summary"]["blocking_errors"] = ["interaction_bundle_tampered"]
            write_json(audit_path, audit)

            result = BUILDER.build_streamlit_app(
                interactive_dir=sample["interactive_dir"],
                app_contract_path=sample["app_contract_path"],
                output_dir=root / "streamlit-app",
            )

            self.assertFalse(result.audit["valid"])
            self.assertFalse(check_by_id(result.audit, "upstream_interaction_audit_is_valid")["valid"])

    def test_missing_required_appendix_file_blocks_app(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            sample = BUILDER.write_sample_app_inputs(root / "sample")
            (sample["interactive_dir"] / "static-fallbacks" / "metric_status.svg").unlink()

            result = BUILDER.build_streamlit_app(
                interactive_dir=sample["interactive_dir"],
                app_contract_path=sample["app_contract_path"],
                output_dir=root / "streamlit-app",
            )

            self.assertFalse(result.audit["valid"])
            check = check_by_id(result.audit, "interactive_appendix_package_is_complete")
            self.assertFalse(check["valid"])
            self.assertEqual(check["observed"], ["static-fallbacks/metric_status.svg"])

    def test_changed_source_table_after_appendix_build_blocks_app(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            sample = BUILDER.write_sample_app_inputs(root / "sample")
            metric_path = BUILDER.load_appendix_tables(sample["interactive_dir"])["tables"]["metric_summary"]["path"]
            rows = read_csv(metric_path)
            rows[0]["current"] = "0.999"
            write_csv(metric_path, rows, list(rows[0].keys()))

            result = BUILDER.build_streamlit_app(
                interactive_dir=sample["interactive_dir"],
                app_contract_path=sample["app_contract_path"],
                output_dir=root / "streamlit-app",
            )

            self.assertFalse(result.audit["valid"])
            self.assertFalse(check_by_id(result.audit, "appendix_source_table_hashes_match_links")["valid"])

    def test_missing_decision_view_blocks_app_contract(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            sample = BUILDER.write_sample_app_inputs(root / "sample")
            contract = read_json(sample["app_contract_path"])
            contract["required_views"].remove("downloads")
            write_json(sample["app_contract_path"], contract)

            result = BUILDER.build_streamlit_app(
                interactive_dir=sample["interactive_dir"],
                app_contract_path=sample["app_contract_path"],
                output_dir=root / "streamlit-app",
            )

            self.assertFalse(result.audit["valid"])
            self.assertFalse(check_by_id(result.audit, "app_contract_declares_views_filters_downloads_and_quality_policy")["valid"])

    def test_missing_download_action_blocks_app_contract(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            sample = BUILDER.write_sample_app_inputs(root / "sample")
            contract = read_json(sample["app_contract_path"])
            contract["download_artifacts"] = [
                item for item in contract["download_artifacts"] if item["id"] != "interaction_audit"
            ]
            write_json(sample["app_contract_path"], contract)

            result = BUILDER.build_streamlit_app(
                interactive_dir=sample["interactive_dir"],
                app_contract_path=sample["app_contract_path"],
                output_dir=root / "streamlit-app",
            )

            self.assertFalse(result.audit["valid"])
            self.assertFalse(check_by_id(result.audit, "app_contract_declares_views_filters_downloads_and_quality_policy")["valid"])

    def test_unknown_default_filter_blocks_filters_audit(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            sample = BUILDER.write_sample_app_inputs(root / "sample")
            contract = read_json(sample["app_contract_path"])
            contract["default_status_filter"] = ["archived"]
            write_json(sample["app_contract_path"], contract)

            result = BUILDER.build_streamlit_app(
                interactive_dir=sample["interactive_dir"],
                app_contract_path=sample["app_contract_path"],
                output_dir=root / "streamlit-app",
            )

            self.assertFalse(result.audit["valid"])
            audit = read_json(result.filters_audit_path)
            self.assertEqual(audit["invalid_default_filter_values"], ["archived"])
            self.assertFalse(check_by_id(result.audit, "filters_audit_matches_metric_status_values")["valid"])

    def test_missing_status_filter_blocks_filters_audit(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            sample = BUILDER.write_sample_app_inputs(root / "sample")
            contract = read_json(sample["app_contract_path"])
            contract["status_filters"].remove("breached")
            write_json(sample["app_contract_path"], contract)

            result = BUILDER.build_streamlit_app(
                interactive_dir=sample["interactive_dir"],
                app_contract_path=sample["app_contract_path"],
                output_dir=root / "streamlit-app",
            )

            self.assertFalse(result.audit["valid"])
            audit = read_json(result.filters_audit_path)
            self.assertEqual(audit["missing_status_filters"], ["breached"])

    def test_forbidden_network_or_secret_pattern_blocks_after_tamper(self) -> None:
        with TemporaryDirectory() as directory:
            sample, result = build_sample(Path(directory))
            result.app_path.write_text(
                result.app_path.read_text(encoding="utf-8")
                + '\nimport requests\nrequests.get("https://example.com")\nst.secrets["token"]\n',
                encoding="utf-8",
            )

            audit = BUILDER.audit_streamlit_app(
                interactive_dir=sample["interactive_dir"],
                output_dir=result.output_dir,
                app_contract=read_json(result.contract_path),
                output_entries=read_json(result.manifest_path)["outputs"],
            )

            self.assertFalse(audit["valid"])
            forbidden = check_by_id(audit, "streamlit_app_source_avoids_forbidden_runtime_patterns")
            self.assertFalse(forbidden["valid"])
            self.assertEqual(forbidden["observed"], ["requests.", "st.secrets"])

    def test_cache_decorator_is_reserved_for_next_lesson(self) -> None:
        with TemporaryDirectory() as directory:
            sample, result = build_sample(Path(directory))
            result.app_path.write_text(
                result.app_path.read_text(encoding="utf-8") + "\n@st.cache_data\ndef stale_cache():\n    return 1\n",
                encoding="utf-8",
            )

            audit = BUILDER.audit_streamlit_app(
                interactive_dir=sample["interactive_dir"],
                output_dir=result.output_dir,
                app_contract=read_json(result.contract_path),
                output_entries=read_json(result.manifest_path)["outputs"],
            )

            self.assertFalse(audit["valid"])
            self.assertIn("@st.cache_data", check_by_id(audit, "streamlit_app_source_avoids_forbidden_runtime_patterns")["observed"])

    def test_sensitive_source_column_is_redacted_from_app_data_and_downloads(self) -> None:
        with TemporaryDirectory() as directory:
            _sample, _appendix, result = build_sensitive_sample(Path(directory))

            self.assertTrue(result.audit["valid"])
            metric_text = (result.output_dir / "app_data" / "metric_summary.csv").read_text(encoding="utf-8")
            with zipfile.ZipFile(result.download_bundle_path) as archive:
                zip_text = "\n".join(archive.read(name).decode("utf-8", errors="ignore") for name in archive.namelist())
            self.assertNotIn("customer@example.com", metric_text + zip_text)
            self.assertNotIn("user_email", metric_text + zip_text)

    def test_sensitive_leak_after_tamper_is_blocked(self) -> None:
        with TemporaryDirectory() as directory:
            sample, _appendix, result = build_sensitive_sample(Path(directory))
            metric_path = result.output_dir / "app_data" / "metric_summary.csv"
            rows = read_csv(metric_path)
            for row in rows:
                row["user_email"] = "customer@example.com"
            write_csv(metric_path, rows, list(rows[0].keys()))

            audit = BUILDER.audit_streamlit_app(
                interactive_dir=result.output_dir.parent / "interactive-appendix",
                output_dir=result.output_dir,
                app_contract=read_json(result.contract_path),
                output_entries=read_json(result.manifest_path)["outputs"],
                source_sensitive_values=["customer@example.com"],
                source_sensitive_columns=["user_email"],
            )

            self.assertFalse(audit["valid"])
            leak_check = check_by_id(audit, "downloads_and_app_data_exclude_sensitive_fields")
            self.assertFalse(leak_check["valid"])
            self.assertEqual(leak_check["observed"]["leaked_columns"], ["user_email"])
            self.assertEqual(sample["delivery_dir"].name, "multi-format-report")

    def test_cli_write_example_builds_streamlit_bundle(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            process = subprocess.run(
                [
                    sys.executable,
                    str(ARTIFACT),
                    "--write-example",
                    str(root / "sample"),
                    "--output-dir",
                    str(root / "streamlit-app"),
                    "--fail-on-invalid",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(process.returncode, 0, process.stderr)
            payload = json.loads(process.stdout)
            self.assertTrue(payload["valid"])
            self.assertEqual(payload["readiness_status"], "ready")

    def test_cli_fail_on_invalid_returns_two(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            sample = BUILDER.write_sample_app_inputs(root / "sample")
            contract = read_json(sample["app_contract_path"])
            contract["default_status_filter"] = ["archived"]
            write_json(sample["app_contract_path"], contract)

            process = subprocess.run(
                [
                    sys.executable,
                    str(ARTIFACT),
                    "--interactive-dir",
                    str(sample["interactive_dir"]),
                    "--app-contract",
                    str(sample["app_contract_path"]),
                    "--output-dir",
                    str(root / "streamlit-app"),
                    "--fail-on-invalid",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(process.returncode, 2, process.stderr)
            payload = json.loads(process.stdout)
            self.assertFalse(payload["valid"])
            self.assertIn("filters_audit_matches_metric_status_values", payload["blocking_errors"])

    def test_code_example_runs_without_external_files(self) -> None:
        process = subprocess.run(
            [sys.executable, str(CODE)],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(process.returncode, 0, process.stderr)
        payload = json.loads(process.stdout)
        self.assertTrue(payload["valid"])
        self.assertEqual(payload["renderer_used"], "streamlit_stakeholder_app_builder")
        self.assertIn("streamlit_app.py", payload["files"])
        self.assertIn("stakeholder_app_bundle.zip", payload["download_bundle"])

    def test_manifest_records_streamlit_version_hashes_and_renderer_boundary(self) -> None:
        with TemporaryDirectory() as directory:
            _sample, result = build_sample(Path(directory))
            manifest = read_json(result.manifest_path)

            self.assertEqual(manifest["hash_algorithm"], "sha256")
            self.assertEqual(manifest["renderer_used"], "streamlit_stakeholder_app_builder")
            self.assertEqual(manifest["streamlit_version"], BUILDER.streamlit.__version__)
            self.assertIn("streamlit_app", manifest["outputs"])
            self.assertIn("download_bundle", manifest["outputs"])
            hashes = [
                item["sha256"]
                for section in ("inputs", "outputs")
                for item in manifest[section].values()
                if not item.get("missing")
            ]
            self.assertTrue(all(len(value) == 64 for value in hashes))


if __name__ == "__main__":
    unittest.main()
