from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "stakeholder_delivery_package.py"
CODE = ROOT / "code" / "main.py"
SPEC = importlib.util.spec_from_file_location("stakeholder_delivery_package", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
HANDOFF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = HANDOFF
SPEC.loader.exec_module(HANDOFF)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_sample(root: Path):
    sample = HANDOFF.write_sample_handoff_inputs(root / "sample")
    result = HANDOFF.build_stakeholder_delivery_package(
        source_root=sample["source_root"],
        docker_package_dir=sample["docker_package_dir"],
        workbook_package_dir=sample["workbook_package_dir"],
        handoff_contract_path=sample["handoff_contract_path"],
        output_dir=root / "handoff-package",
    )
    return sample, result


class StakeholderDeliveryPackageTest(unittest.TestCase):
    def test_sample_handoff_package_writes_required_tree_and_audit(self) -> None:
        with TemporaryDirectory() as directory:
            _sample, result = build_sample(Path(directory))

            self.assertTrue(result.valid)
            self.assertEqual(result.status, "success")
            self.assertIn(result.decision_status, HANDOFF.ALLOWED_DECISION_STATUSES)
            for relative in HANDOFF.REQUIRED_PACKAGE_FILES:
                self.assertTrue((result.package_dir / relative).is_file(), relative)

    def test_default_contract_names_owner_backup_formats_support_and_retirement(self) -> None:
        contract = HANDOFF.default_handoff_contract()

        self.assertEqual(HANDOFF.handoff_contract_errors(contract), [])
        self.assertNotEqual(contract["owner"]["primary"], contract["owner"]["backup"])
        self.assertEqual(set(contract["consumer_formats"]), HANDOFF.REQUIRED_CONSUMER_FORMATS)
        self.assertEqual(set(contract["optional_interfaces"]), HANDOFF.OPTIONAL_INTERFACE_FORMATS)
        self.assertGreaterEqual(len(contract["support_policy"]["retirement_triggers"]), 2)
        self.assertIn("stakeholder_delivery_package.py", contract["rerun_command"])

    def test_quality_gate_summary_covers_all_delivery_layers_and_optional_interfaces(self) -> None:
        with TemporaryDirectory() as directory:
            _sample, result = build_sample(Path(directory))
            quality = read_json(result.quality_summary_path)

            layers = {gate["layer"] for gate in quality["gates"]}
            self.assertEqual(
                layers,
                {"memo", "workbook", "report", "interactive", "app", "automation", "optional_api", "optional_container"},
            )
            self.assertTrue(quality["all_quality_gates_valid"])
            self.assertEqual(quality["freshness_state"], "fresh")
            self.assertEqual(quality["blocking_layers"], [])
            self.assertIn(quality["decision_status"], HANDOFF.ALLOWED_DECISION_STATUSES)

    def test_manifest_hashes_every_package_file_except_manifest_itself(self) -> None:
        with TemporaryDirectory() as directory:
            _sample, result = build_sample(Path(directory))
            manifest = read_json(result.manifest_path)
            paths = {entry["path"] for entry in manifest["outputs"].values()}

            self.assertEqual(manifest["renderer_used"], "stakeholder_delivery_package")
            self.assertEqual(manifest["hash_algorithm"], "sha256")
            self.assertNotIn("manifest.json", paths)
            for relative in [
                "memo/executive-memo.md",
                "workbook/stakeholder-workbook.xlsx",
                "report/report.pdf",
                "report/report.docx",
                "app/downloads/stakeholder_app_bundle.zip",
                "handoff/handoff_audit.json",
            ]:
                self.assertIn(relative, paths)
            self.assertTrue(all(len(entry["sha256"]) == 64 for entry in manifest["outputs"].values()))

    def test_evidence_index_links_layers_to_files_hashes_and_owner(self) -> None:
        with TemporaryDirectory() as directory:
            _sample, result = build_sample(Path(directory))
            rows = HANDOFF.read_csv(result.package_dir / "input" / "evidence-index.csv")

            self.assertGreaterEqual(len(rows), 8)
            self.assertIn("memo", {row["layer"] for row in rows})
            self.assertIn("optional-container", {row["layer"] for row in rows})
            self.assertTrue(all(row["owner"] == "support-analytics-owner" for row in rows))
            self.assertTrue(all(len(row["sha256"]) == 64 for row in rows))

    def test_handoff_docs_name_rerun_owner_backup_escalation_limitations_and_retirement(self) -> None:
        with TemporaryDirectory() as directory:
            _sample, result = build_sample(Path(directory))
            runbook = (result.package_dir / "handoff" / "runbook.md").read_text(encoding="utf-8")
            support = (result.package_dir / "handoff" / "support-policy.md").read_text(encoding="utf-8")

            combined = runbook + support
            self.assertIn("support-analytics-owner", combined)
            self.assertIn("product-analytics-backup", combined)
            self.assertIn("#trial-onboarding-delivery", combined)
            self.assertIn("stakeholder_delivery_package.py", combined)
            self.assertIn("Known Limitations", runbook)
            self.assertIn("When To Retire This Artifact", support)

    def test_changelog_and_stakeholder_email_are_human_readable(self) -> None:
        with TemporaryDirectory() as directory:
            _sample, result = build_sample(Path(directory))
            changelog = (result.package_dir / "handoff" / "changelog.md").read_text(encoding="utf-8")
            email = (result.package_dir / "handoff" / "stakeholder-email.md").read_text(encoding="utf-8")

            self.assertIn("## [1.0.0] - 2026-01-05", changelog)
            self.assertIn("### Added", changelog)
            self.assertIn("### Security", changelog)
            self.assertIn("Subject:", email)
            self.assertIn("Decision status:", email)
            self.assertIn("Freshness state:", email)

    def test_optional_api_and_container_contracts_are_preserved(self) -> None:
        with TemporaryDirectory() as directory:
            _sample, result = build_sample(Path(directory))
            api_audit = read_json(result.package_dir / "optional-api" / "api_audit.json")
            docker_audit = read_json(result.package_dir / "optional-container" / "docker_audit.json")
            docker_run = read_json(result.package_dir / "optional-container" / "docker_run_manifest.json")

            self.assertTrue(api_audit["valid"])
            self.assertTrue(docker_audit["valid"])
            self.assertEqual(api_audit["status"], "success")
            self.assertEqual(docker_audit["status"], "success")
            self.assertTrue(docker_run["equivalence"]["hashes_match"])
            self.assertTrue((result.package_dir / "optional-api" / "openapi-schema.json").is_file())

    def test_bad_handoff_contract_blocks_package(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            sample = HANDOFF.write_sample_handoff_inputs(root / "sample")
            contract = HANDOFF.default_handoff_contract()
            contract["decision_status"] = "definitely_ship"
            contract["owner"]["backup"] = contract["owner"]["primary"]
            contract["support_policy"]["retirement_triggers"] = []
            bad_contract_path = root / "bad_handoff_contract.json"
            write_json(bad_contract_path, contract)

            result = HANDOFF.build_stakeholder_delivery_package(
                source_root=sample["source_root"],
                docker_package_dir=sample["docker_package_dir"],
                workbook_package_dir=sample["workbook_package_dir"],
                handoff_contract_path=bad_contract_path,
                output_dir=root / "handoff-package",
            )
            audit = read_json(result.audit_path)

            self.assertFalse(result.valid)
            self.assertEqual(result.status, "handoff_contract_block")
            self.assertIn("decision_status_must_be_allowed", audit["summary"]["contract_errors"])
            self.assertIn("backup_owner_must_differ_from_primary", audit["summary"]["contract_errors"])
            self.assertIn("retirement_triggers_must_have_at_least_two_items", audit["summary"]["contract_errors"])

    def test_missing_required_source_file_blocks_as_upstream_package_error(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            sample = HANDOFF.write_sample_handoff_inputs(root / "sample")
            (sample["docker_package_dir"] / "docker_audit.json").unlink()

            result = HANDOFF.build_stakeholder_delivery_package(
                source_root=sample["source_root"],
                docker_package_dir=sample["docker_package_dir"],
                workbook_package_dir=sample["workbook_package_dir"],
                handoff_contract_path=sample["handoff_contract_path"],
                output_dir=root / "handoff-package",
            )
            audit = read_json(result.audit_path)

            self.assertFalse(result.valid)
            self.assertEqual(result.status, "upstream_package_block")
            self.assertIn("optional-container/docker_audit.json", audit["summary"]["missing_sources"])

    def test_invalid_optional_container_quality_gate_blocks_handoff(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            sample = HANDOFF.write_sample_handoff_inputs(root / "sample")
            docker_audit_path = sample["docker_package_dir"] / "docker_audit.json"
            docker_audit = read_json(docker_audit_path)
            docker_audit["valid"] = False
            docker_audit["status"] = "container_contract_block"
            docker_audit["summary"]["blocking_errors"] = ["tampered_for_handoff_test"]
            write_json(docker_audit_path, docker_audit)

            result = HANDOFF.build_stakeholder_delivery_package(
                source_root=sample["source_root"],
                docker_package_dir=sample["docker_package_dir"],
                workbook_package_dir=sample["workbook_package_dir"],
                handoff_contract_path=sample["handoff_contract_path"],
                output_dir=root / "handoff-package",
            )
            quality = read_json(result.quality_summary_path)

            self.assertFalse(result.valid)
            self.assertEqual(result.status, "upstream_package_block")
            self.assertIn("optional_container", quality["blocking_layers"])
            self.assertEqual(quality["decision_status"], "blocked_by_quality_gate")

    def test_secret_marker_in_public_text_artifact_blocks_handoff(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            sample = HANDOFF.write_sample_handoff_inputs(root / "sample")
            api_fallback = sample["source_root"] / "fastapi-package" / "fastapi-delivery-api" / "cli_fallback.md"
            api_fallback.write_text(api_fallback.read_text(encoding="utf-8") + "\nTOKEN=do-not-ship\n", encoding="utf-8")

            result = HANDOFF.build_stakeholder_delivery_package(
                source_root=sample["source_root"],
                docker_package_dir=sample["docker_package_dir"],
                workbook_package_dir=sample["workbook_package_dir"],
                handoff_contract_path=sample["handoff_contract_path"],
                output_dir=root / "handoff-package",
            )
            audit = read_json(result.audit_path)

            self.assertFalse(result.valid)
            self.assertEqual(result.status, "handoff_contract_block")
            self.assertIn("public_artifacts_have_no_secret_or_private_key_markers", audit["summary"]["blocking_errors"])
            self.assertEqual(audit["summary"]["secret_findings"][0]["marker"], "TOKEN=")

    def test_contract_error_helper_catches_missing_support_policy_fields(self) -> None:
        contract = HANDOFF.default_handoff_contract()
        contract["owner"]["primary"] = "same-owner"
        contract["owner"]["backup"] = "same-owner"
        contract["support_policy"]["escalation_path"] = ["#only-one-step"]
        contract["support_policy"]["retirement_triggers"] = []

        errors = HANDOFF.handoff_contract_errors(contract)

        self.assertIn("backup_owner_must_differ_from_primary", errors)
        self.assertIn("support_escalation_path_must_have_two_steps", errors)
        self.assertIn("retirement_triggers_must_have_at_least_two_items", errors)

    def test_source_layout_points_to_transitive_phase_17_packages(self) -> None:
        root = Path("/tmp/example-source")
        resolved = root.resolve()
        layout = HANDOFF.source_layout(root)

        self.assertEqual(layout["scheduled_package"], resolved / "fastapi-inputs" / "scheduled-package")
        self.assertEqual(layout["api_package"], resolved / "fastapi-package" / "fastapi-delivery-api")
        self.assertIn("plotly-inputs", layout["multi_format_report"].as_posix())
        self.assertIn("interactive-appendix", layout["interactive_appendix"].as_posix())

    def test_cli_help_names_handoff_arguments(self) -> None:
        process = subprocess.run(
            [sys.executable, str(ARTIFACT), "--help"],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(process.returncode, 0)
        self.assertIn("--source-root", process.stdout)
        self.assertIn("--docker-package-dir", process.stdout)
        self.assertIn("--workbook-package-dir", process.stdout)
        self.assertIn("--write-example", process.stdout)

    def test_cli_write_example_builds_valid_handoff_package(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            process = subprocess.run(
                [
                    sys.executable,
                    str(ARTIFACT),
                    "--write-example",
                    str(root / "sample"),
                    "--output-dir",
                    str(root / "handoff-package"),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            payload = json.loads(process.stdout)

            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertTrue(payload["valid"])
            self.assertEqual(payload["status"], "success")
            self.assertTrue((root / "handoff-package" / "stakeholder-delivery-package" / "manifest.json").is_file())
            self.assertTrue((root / "handoff-package" / "stakeholder-delivery-package" / "handoff" / "runbook.md").is_file())

    def test_cli_fail_on_invalid_returns_handoff_contract_block_code(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            sample = HANDOFF.write_sample_handoff_inputs(root / "sample")
            contract = HANDOFF.default_handoff_contract()
            contract["decision_status"] = "not-a-status"
            bad_contract_path = root / "bad_handoff_contract.json"
            write_json(bad_contract_path, contract)

            process = subprocess.run(
                [
                    sys.executable,
                    str(ARTIFACT),
                    "--source-root",
                    str(sample["source_root"]),
                    "--docker-package-dir",
                    str(sample["docker_package_dir"]),
                    "--workbook-package-dir",
                    str(sample["workbook_package_dir"]),
                    "--handoff-contract",
                    str(bad_contract_path),
                    "--output-dir",
                    str(root / "handoff-package"),
                    "--fail-on-invalid",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            payload = json.loads(process.stdout)

            self.assertEqual(process.returncode, HANDOFF.HANDOFF_EXIT_CODE_POLICY["handoff_contract_block"])
            self.assertFalse(payload["valid"])
            self.assertEqual(payload["status"], "handoff_contract_block")

    def test_code_example_runs_and_reports_handoff_summary(self) -> None:
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
        self.assertGreaterEqual(payload["quality_gate_count"], 8)
        self.assertEqual(payload["blocking_layers"], [])
        self.assertGreater(payload["manifest_output_count"], 30)
        self.assertTrue(payload["runbook_exists"])
        self.assertTrue(payload["support_policy_exists"])


if __name__ == "__main__":
    unittest.main()
