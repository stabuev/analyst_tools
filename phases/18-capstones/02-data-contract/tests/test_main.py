from __future__ import annotations

import copy
import csv
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

LESSON_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = LESSON_ROOT / "outputs" / "capstone_data_contract_auditor.py"
CODE = LESSON_ROOT / "code" / "main.py"
sys.path.insert(0, str(LESSON_ROOT / "outputs"))

import capstone_data_contract_auditor as DATA  # noqa: E402


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: dict) -> Path:
    DATA.write_json(path, value)
    return path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def find_check(report: dict, check_id: str) -> dict:
    return next(item for item in report["checks"] if item["id"] == check_id)


class CapstoneDataContractAuditorTest(TestCase):
    def inputs(self, root: Path) -> dict[str, Path]:
        return DATA.write_sample_inputs(root / "inputs")

    def audit(self, root: Path, mutate=None, mutate_source=None) -> tuple[dict, dict]:
        paths = self.inputs(root)
        contract = read_json(paths["data_contract_path"])
        if mutate is not None:
            mutate(contract)
            write_json(paths["data_contract_path"], contract)
        if mutate_source is not None:
            mutate_source(paths["source_root"], contract)
            manifest = DATA.build_dataset_manifest(contract, paths["source_root"])
            write_json(paths["dataset_manifest_path"], manifest)
        report, state, _loaded, public = DATA.audit_data_contract(
            upstream_brief_package=paths["upstream_brief_package"],
            data_contract_path=paths["data_contract_path"],
            dataset_manifest_path=paths["dataset_manifest_path"],
            source_root=paths["source_root"],
        )
        return {"report": report, "state": state, "public": public}, paths

    def test_reference_contract_is_data_ready_and_keeps_upstream_warning(self) -> None:
        with TemporaryDirectory() as directory:
            result, _paths = self.audit(Path(directory))

        report = result["report"]
        self.assertTrue(report["valid"])
        self.assertEqual(report["status"], "data_ready")
        self.assertEqual(report["summary"]["next_stage"], "baseline")
        self.assertEqual(report["summary"]["check_count"], 10)
        self.assertEqual(report["summary"]["source_count"], 3)
        self.assertEqual(report["summary"]["relationship_count"], 2)
        self.assertEqual(report["summary"]["public_sample_rows"], 2)
        self.assertEqual(
            report["summary"]["warnings"],
            ["reference_profile_is_not_portfolio_evidence"],
        )

    def test_code_example_writes_complete_package_without_raw_sources(self) -> None:
        result = subprocess.run([sys.executable, CODE], check=True, capture_output=True, text=True)
        payload = json.loads(result.stdout)

        self.assertTrue(payload["valid"])
        self.assertEqual(payload["status"], "data_ready")
        self.assertEqual(payload["source_count"], 3)
        self.assertEqual(payload["public_sample_rows"], 2)
        for name in (
            "data_contract.json",
            "dataset_manifest.json",
            "data_audit.json",
            "lineage_report.csv",
            "checksum_inventory.csv",
            "public_data_sample.csv",
            "capstone_state.json",
            "data_package_manifest.json",
        ):
            self.assertTrue((LESSON_ROOT / "outputs" / name).is_file(), name)
        self.assertFalse((LESSON_ROOT / "outputs" / "users.csv").exists())
        self.assertFalse((LESSON_ROOT / "outputs" / "user_week.csv").exists())

    def test_cli_write_example_and_help_expose_the_full_contract(self) -> None:
        help_result = subprocess.run(
            [sys.executable, ARTIFACT, "--help"],
            check=True,
            capture_output=True,
            text=True,
        )
        for option in (
            "--upstream-brief-package",
            "--data-contract",
            "--dataset-manifest",
            "--source-root",
            "--write-example",
            "--fail-on-invalid",
        ):
            self.assertIn(option, help_result.stdout)

        with TemporaryDirectory() as directory:
            root = Path(directory)
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--write-example",
                    root / "input",
                    "--output-dir",
                    root / "package",
                    "--fail-on-invalid",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "data_ready")
            self.assertTrue((root / "input" / "source-data" / "users.csv").is_file())
            self.assertTrue((root / "package" / "data_package_manifest.json").is_file())

    def test_upstream_state_checksum_tampering_blocks_data_stage(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.inputs(root)
            state_path = paths["upstream_brief_package"] / "capstone_state.json"
            state = read_json(state_path)
            state["decision_owner"] = "changed-after-approval"
            write_json(state_path, state)
            report, _state, _loaded, _public = DATA.audit_data_contract(
                upstream_brief_package=paths["upstream_brief_package"],
                data_contract_path=paths["data_contract_path"],
                dataset_manifest_path=paths["dataset_manifest_path"],
                source_root=paths["source_root"],
            )

        self.assertFalse(report["valid"])
        self.assertIn(
            "upstream_brief_is_ready_and_untampered",
            report["summary"]["blocking_errors"],
        )

    def test_contract_project_must_match_upstream_brief(self) -> None:
        with TemporaryDirectory() as directory:
            result, _paths = self.audit(
                Path(directory), lambda value: value.__setitem__("project_id", "another-project")
            )

        check = find_check(result["report"], "data_contract_structure_matches_upstream_project")
        self.assertFalse(check["valid"])
        self.assertEqual(check["observed"]["errors"][0]["field"], "project_id")

    def test_source_policy_requires_license_owner_usage_and_command(self) -> None:
        def mutate(contract: dict) -> None:
            contract["tables"][0]["owner"] = ""
            contract["tables"][0]["license"] = ""
            contract["tables"][0]["allowed_uses"] = []
            contract["tables"][0]["reproducibility"]["command"] = ""

        with TemporaryDirectory() as directory:
            result, _paths = self.audit(Path(directory), mutate)

        policy = find_check(
            result["report"],
            "sources_have_owner_origin_license_usage_and_reproducibility",
        )
        self.assertFalse(policy["valid"])
        self.assertEqual(len(policy["observed"]["errors"]), 4)

    def test_manifest_detects_changed_source_bytes(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.inputs(root)
            with (paths["source_root"] / "users.csv").open("a", encoding="utf-8") as output:
                output.write("u9,2025-12-10T09:00:00Z,RU,basic,false,2026-01-10T12:00:00Z\n")
            report, _state, _loaded, _public = DATA.audit_data_contract(
                upstream_brief_package=paths["upstream_brief_package"],
                data_contract_path=paths["data_contract_path"],
                dataset_manifest_path=paths["dataset_manifest_path"],
                source_root=paths["source_root"],
            )

        manifest = find_check(report, "dataset_manifest_matches_source_bytes")
        self.assertFalse(manifest["valid"])
        self.assertIn("sha256", {item["field"] for item in manifest["observed"]["errors"]})

    def test_schema_type_and_nullability_are_checked_against_rows(self) -> None:
        def mutate_source(root: Path, _contract: dict) -> None:
            rows, fields = DATA.read_csv(root / "user_week.csv")
            rows[0]["support_ticket_count"] = "many"
            DATA.write_csv(root / "user_week.csv", rows, fields)

        with TemporaryDirectory() as directory:
            result, _paths = self.audit(Path(directory), mutate_source=mutate_source)

        schema = find_check(result["report"], "schemas_types_nullability_and_grain_match_data")
        self.assertFalse(schema["valid"])
        self.assertEqual(schema["observed"]["errors"][0]["column"], "support_ticket_count")

    def test_duplicate_and_null_grain_keys_block_the_contract(self) -> None:
        def mutate_source(root: Path, _contract: dict) -> None:
            rows, fields = DATA.read_csv(root / "users.csv")
            rows[1]["user_id"] = rows[0]["user_id"]
            rows[2]["user_id"] = ""
            DATA.write_csv(root / "users.csv", rows, fields)

        with TemporaryDirectory() as directory:
            result, _paths = self.audit(Path(directory), mutate_source=mutate_source)

        errors = find_check(result["report"], "schemas_types_nullability_and_grain_match_data")[
            "observed"
        ]["errors"]
        reasons = {item["reason"] for item in errors}
        self.assertIn("duplicate key", reasons)
        self.assertIn("null key", reasons)

    def test_relationship_orphan_and_wrong_cardinality_are_visible(self) -> None:
        def mutate(contract: dict) -> None:
            contract["relationships"][0]["cardinality"] = "many_to_many"

        def mutate_source(root: Path, _contract: dict) -> None:
            rows, fields = DATA.read_csv(root / "user_week.csv")
            rows[0]["user_id"] = "missing-parent"
            DATA.write_csv(root / "user_week.csv", rows, fields)

        with TemporaryDirectory() as directory:
            result, _paths = self.audit(Path(directory), mutate, mutate_source)

        relationship = find_check(result["report"], "relationships_enforce_cardinality_and_orphans")
        reasons = {item.get("reason") for item in relationship["observed"]["errors"]}
        self.assertFalse(relationship["valid"])
        self.assertIn("orphan rows", reasons)
        self.assertIn(
            "many_to_one", {item.get("expected") for item in relationship["observed"]["errors"]}
        )

    def test_future_and_stale_source_availability_block_baseline(self) -> None:
        def mutate_source(root: Path, _contract: dict) -> None:
            for filename, timestamp in (
                ("users.csv", "2026-01-13T00:00:00Z"),
                ("support_tickets.csv", "2025-12-01T00:00:00Z"),
            ):
                rows, fields = DATA.read_csv(root / filename)
                for row in rows:
                    row["source_updated_at"] = timestamp
                DATA.write_csv(root / filename, rows, fields)

        with TemporaryDirectory() as directory:
            result, _paths = self.audit(Path(directory), mutate_source=mutate_source)

        freshness = find_check(result["report"], "freshness_and_observation_windows_are_explicit")
        reasons = {item["reason"] for item in freshness["observed"]["errors"]}
        self.assertIn("future availability", reasons)
        self.assertIn("stale", reasons)

    def test_incomplete_population_cannot_silently_enter_analysis(self) -> None:
        def mutate_source(root: Path, _contract: dict) -> None:
            rows, fields = DATA.read_csv(root / "user_week.csv")
            for row in rows:
                row["window_complete"] = "false"
            DATA.write_csv(root / "user_week.csv", rows, fields)

        with TemporaryDirectory() as directory:
            result, _paths = self.audit(Path(directory), mutate_source=mutate_source)

        self.assertFalse(
            find_check(result["report"], "freshness_and_observation_windows_are_explicit")["valid"]
        )
        self.assertEqual(result["public"]["rows"], [])

    def test_each_capstone_route_has_a_minimal_control_profile(self) -> None:
        profiles = [
            ("core_analytics", "standard", "descriptive"),
            ("product_experiments", "standard", "product_decision"),
            ("data_analytics_engineering", "standard", "data_quality"),
            ("decision_science", "causal", "causal"),
            ("decision_science", "forecast", "forecast"),
            ("machine_learning", "baseline", "predictive"),
            ("machine_learning", "strong_model", "decision_policy"),
            ("delivery_product", "standard", "delivery_quality"),
        ]
        for route, variant, claim_type in profiles:
            with self.subTest(route=route, variant=variant):
                contract = DATA.default_contract("project")
                contract["route_policy"] = DATA.default_route_policy(route, variant)
                contract["route_controls"] = DATA.default_route_controls(route, variant)
                state = {
                    "project_id": "project",
                    "route": route,
                    "route_variant": variant,
                    "claim_type": claim_type,
                }
                route_check = DATA.validate_route_controls(contract, state)
                self.assertTrue(route_check["valid"], route_check["observed"]["errors"])

    def test_missing_route_control_and_core_causal_overclaim_block(self) -> None:
        contract = DATA.default_contract("project")
        contract["route_controls"].pop()
        state = {
            "route": "core_analytics",
            "route_variant": "standard",
            "claim_type": "causal",
        }

        route_check = DATA.validate_route_controls(contract, state)

        self.assertFalse(route_check["valid"])
        fields = {item["field"] for item in route_check["observed"]["errors"]}
        self.assertIn("route_controls", fields)
        self.assertIn("claim_type", fields)

    def test_public_policy_cannot_allow_restricted_fields(self) -> None:
        def mutate(contract: dict) -> None:
            contract["public_release_policy"]["allowed_classifications"].append("restricted")

        with TemporaryDirectory() as directory:
            result, _paths = self.audit(Path(directory), mutate)

        public = find_check(result["report"], "public_release_excludes_restricted_and_secret_rows")
        self.assertFalse(public["valid"])

    def test_public_sample_enforces_group_size_and_contains_no_identifiers(self) -> None:
        with TemporaryDirectory() as directory:
            result, _paths = self.audit(Path(directory))
            blocked, _paths = self.audit(
                Path(directory) / "blocked",
                lambda value: value["public_release_policy"].__setitem__("minimum_group_size", 5),
            )

        self.assertEqual(len(result["public"]["rows"]), 2)
        self.assertEqual(set(result["public"]["rows"][0]), set(DATA.PUBLIC_SAMPLE_FIELDS))
        self.assertNotIn("user_id", result["public"]["rows"][0])
        self.assertIn(
            "public_sample_meets_aggregate_grain_and_group_size",
            blocked["report"]["summary"]["blocking_errors"],
        )

    def test_package_handoff_advances_state_and_hashes_every_output(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.inputs(root)
            result = DATA.build_data_contract_package(
                upstream_brief_package=paths["upstream_brief_package"],
                data_contract_path=paths["data_contract_path"],
                dataset_manifest_path=paths["dataset_manifest_path"],
                source_root=paths["source_root"],
                output_dir=root / "package",
            )
            state = read_json(result["state_path"])
            manifest = read_json(result["manifest_path"])

            self.assertEqual(state["current_stage"], "data_contract")
            self.assertEqual(state["stage_status"], "data_ready")
            self.assertEqual(state["data_contract_id"], "weekly-retention-data-v1")
            self.assertIsNone(state["baseline_id"])
            self.assertEqual(state["open_blockers"], [])
            self.assertFalse(manifest["raw_sources_copied"])
            self.assertEqual(manifest["renderer_used"], "capstone_data_contract_auditor")
            for entry in manifest["outputs"].values():
                path = result["output_dir"] / entry["path"]
                self.assertEqual(entry["sha256"], sha256(path))
                self.assertEqual(entry["bytes"], path.stat().st_size)

    def test_lineage_and_checksum_inventory_cover_declared_sources(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.inputs(root)
            result = DATA.build_data_contract_package(
                upstream_brief_package=paths["upstream_brief_package"],
                data_contract_path=paths["data_contract_path"],
                dataset_manifest_path=paths["dataset_manifest_path"],
                source_root=paths["source_root"],
                output_dir=root / "package",
            )
            with result["lineage_report_path"].open(encoding="utf-8", newline="") as source:
                lineage = list(csv.DictReader(source))
            with result["checksum_inventory_path"].open(encoding="utf-8", newline="") as source:
                checksums = list(csv.DictReader(source))

        self.assertEqual(
            {row["source_id"] for row in lineage}, {"users", "user_week", "support_tickets"}
        )
        self.assertTrue(all(row["status"] == "declared" for row in lineage))
        self.assertTrue(all(row["matches"] == "true" for row in checksums))
        self.assertTrue(all(row["publication_class"] == "restricted" for row in checksums))

    def test_cli_exit_codes_distinguish_blocked_contract_and_missing_inputs(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.inputs(root)
            contract = read_json(paths["data_contract_path"])
            contract["public_release_policy"]["minimum_group_size"] = 5
            write_json(paths["data_contract_path"], contract)
            blocked = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--upstream-brief-package",
                    paths["upstream_brief_package"],
                    "--data-contract",
                    paths["data_contract_path"],
                    "--dataset-manifest",
                    paths["dataset_manifest_path"],
                    "--source-root",
                    paths["source_root"],
                    "--output-dir",
                    root / "blocked",
                    "--fail-on-invalid",
                ],
                capture_output=True,
                text=True,
            )
            missing = subprocess.run(
                [sys.executable, ARTIFACT, "--output-dir", root / "missing"],
                capture_output=True,
                text=True,
            )

        self.assertEqual(blocked.returncode, 1)
        self.assertEqual(json.loads(blocked.stdout)["status"], "data_contract_block")
        self.assertEqual(missing.returncode, 2)
        self.assertEqual(json.loads(missing.stdout)["error"]["code"], "missing_inputs")

    def test_audit_does_not_mutate_contract_or_manifest(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.inputs(root)
            contract_before = read_json(paths["data_contract_path"])
            manifest_before = read_json(paths["dataset_manifest_path"])

            DATA.audit_data_contract(
                upstream_brief_package=paths["upstream_brief_package"],
                data_contract_path=paths["data_contract_path"],
                dataset_manifest_path=paths["dataset_manifest_path"],
                source_root=paths["source_root"],
            )

            self.assertEqual(read_json(paths["data_contract_path"]), contract_before)
            self.assertEqual(read_json(paths["dataset_manifest_path"]), manifest_before)
            self.assertEqual(copy.deepcopy(contract_before), contract_before)


if __name__ == "__main__":
    import unittest

    unittest.main()
