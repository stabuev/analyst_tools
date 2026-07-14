from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

LESSON_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = LESSON_ROOT / "outputs" / "capstone_independent_verifier.py"
CODE = LESSON_ROOT / "code" / "main.py"
sys.path.insert(0, str(LESSON_ROOT / "outputs"))

import capstone_independent_verifier as VERIFIER  # noqa: E402


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: dict) -> Path:
    return VERIFIER.write_json(path, value)


def find_check(report: dict, check_id: str) -> dict:
    return next(item for item in report["checks"] if item["id"] == check_id)


class CapstoneIndependentVerifierTest(TestCase):
    def inputs(self, root: Path) -> dict[str, Path]:
        return VERIFIER.write_sample_inputs(root / "inputs")

    def audit(self, root: Path, mutate_spec=None) -> tuple[dict, dict, dict]:
        paths = self.inputs(root)
        if mutate_spec is not None:
            spec = read_json(paths["verification_spec_path"])
            mutate_spec(spec)
            write_json(paths["verification_spec_path"], spec)
        report, result = VERIFIER.audit_verification(
            upstream_implementation_package=paths["upstream_implementation_package"],
            implementation_runner=paths["implementation_runner"],
            upstream_baseline_package=paths["upstream_baseline_package"],
            verification_spec_path=paths["verification_spec_path"],
        )
        return report, result, paths

    def refresh_implementation_output(self, package: Path, output_id: str, filename: str) -> None:
        VERIFIER.update_manifest_output(package, output_id, filename)

    def test_reference_package_reaches_verification_ready_without_selecting_candidate(self) -> None:
        with TemporaryDirectory() as directory:
            report, result, _paths = self.audit(Path(directory))

        self.assertTrue(report["valid"])
        self.assertEqual(report["status"], "verification_ready")
        self.assertEqual(report["summary"]["next_stage"], "peer_review")
        self.assertEqual(report["summary"]["check_count"], 11)
        self.assertTrue(report["summary"]["clean_room_match"])
        self.assertTrue(report["summary"]["shadow_pass"])
        self.assertEqual(report["summary"]["negative_fixtures"], 4)
        self.assertTrue(report["summary"]["negative_fixtures_pass"])
        self.assertEqual(report["summary"]["verified_claims"], 3)
        self.assertEqual(report["summary"]["selected_method"], "baseline")
        self.assertEqual(
            report["summary"]["sensitivity_decision_flips"],
            ["threshold_minus_practical_improvement"],
        )
        self.assertIn("candidate_conclusion_is_threshold_sensitive", report["summary"]["warnings"])
        self.assertFalse(result["acceptance"]["candidate_pass"])

    def test_code_example_writes_complete_verification_package(self) -> None:
        completed = subprocess.run(
            [sys.executable, CODE],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        payload = json.loads(completed.stdout)

        self.assertTrue(payload["valid"])
        self.assertEqual(payload["status"], "verification_ready")
        self.assertTrue(payload["clean_room_match"])
        self.assertEqual(payload["negative_fixtures"], 4)
        self.assertEqual(payload["selected_method"], "baseline")
        for name in (
            "verification_spec.json",
            "verification_report.json",
            "clean_room_rerun.json",
            "shadow_calculation.csv",
            "failure_fixture_results.csv",
            "sensitivity_report.csv",
            "claim_evidence_audit.csv",
            "route_verification_report.json",
            "test_results.json",
            "capstone_state.json",
            "verification_manifest.json",
        ):
            self.assertTrue((LESSON_ROOT / "outputs" / name).is_file(), name)

    def test_cli_help_and_write_example_expose_all_independent_inputs(self) -> None:
        help_result = subprocess.run(
            [sys.executable, ARTIFACT, "--help"],
            check=True,
            capture_output=True,
            text=True,
        )
        for option in (
            "--upstream-implementation-package",
            "--implementation-runner",
            "--upstream-baseline-package",
            "--verification-spec",
            "--write-example",
            "--fail-on-invalid",
        ):
            self.assertIn(option, help_result.stdout)

        with TemporaryDirectory() as directory:
            root = Path(directory)
            completed = subprocess.run(
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
                timeout=30,
            )
            payload = json.loads(completed.stdout)

            self.assertEqual(payload["status"], "verification_ready")
            self.assertTrue((root / "input" / "verification_spec.json").is_file())
            self.assertTrue((root / "package" / "verification_manifest.json").is_file())

    def test_tampered_implementation_output_blocks_package_integrity(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.inputs(root)
            target = paths["upstream_implementation_package"] / "candidate_metrics.csv"
            target.write_text(target.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            report, _result = VERIFIER.audit_verification(
                upstream_implementation_package=paths["upstream_implementation_package"],
                implementation_runner=paths["implementation_runner"],
                upstream_baseline_package=paths["upstream_baseline_package"],
                verification_spec_path=paths["verification_spec_path"],
            )

        integrity = find_check(report, "upstream_implementation_package_is_immutable")
        self.assertFalse(integrity["valid"])
        self.assertEqual(
            integrity["observed"]["errors"][0]["field"],
            "outputs.candidate_metrics.sha256",
        )

    def test_tampered_baseline_gate_blocks_immutable_input_check(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.inputs(root)
            gate_path = paths["upstream_baseline_package"] / "acceptance_gate.json"
            gate = read_json(gate_path)
            gate["candidate_threshold"] = 0.6
            write_json(gate_path, gate)
            report, _result = VERIFIER.audit_verification(
                upstream_implementation_package=paths["upstream_implementation_package"],
                implementation_runner=paths["implementation_runner"],
                upstream_baseline_package=paths["upstream_baseline_package"],
                verification_spec_path=paths["verification_spec_path"],
            )

        integrity = find_check(report, "upstream_implementation_package_is_immutable")
        self.assertFalse(integrity["valid"])
        self.assertEqual(
            integrity["observed"]["errors"][0]["field"],
            "inputs.upstream_acceptance_gate.sha256",
        )

    def test_rehashed_stale_stage_is_caught_beyond_checksum(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.inputs(root)
            package = paths["upstream_implementation_package"]
            state_path = package / "capstone_state.json"
            state = read_json(state_path)
            state["current_stage"] = "baseline"
            state["stage_status"] = "baseline_ready"
            write_json(state_path, state)
            self.refresh_implementation_output(package, "capstone_state", "capstone_state.json")
            report, _result = VERIFIER.audit_verification(
                upstream_implementation_package=package,
                implementation_runner=paths["implementation_runner"],
                upstream_baseline_package=paths["upstream_baseline_package"],
                verification_spec_path=paths["verification_spec_path"],
            )

        self.assertTrue(find_check(report, "upstream_implementation_package_is_immutable")["valid"])
        state_check = find_check(
            report, "implementation_state_is_ready_for_independent_verification"
        )
        self.assertFalse(state_check["valid"])
        self.assertEqual(
            {item["field"] for item in state_check["observed"]["errors"]},
            {"current_stage", "stage_status"},
        )

    def test_verification_ids_route_and_variant_must_match_upstream_state(self) -> None:
        def mutate(spec: dict) -> None:
            spec["project_id"] = "another-project"
            spec["implementation_id"] = "another-implementation"
            spec["route"] = "machine_learning"
            spec["route_variant"] = "strong_model"

        with TemporaryDirectory() as directory:
            report, _result, _paths = self.audit(Path(directory), mutate)

        spec_check = find_check(report, "verification_spec_is_independent_and_predeclared")
        self.assertFalse(spec_check["valid"])
        self.assertEqual(
            {item["field"] for item in spec_check["observed"]["errors"]},
            {"project_id", "implementation_id", "route", "route_variant"},
        )

    def test_independence_and_clean_room_policy_cannot_be_downgraded(self) -> None:
        def mutate(spec: dict) -> None:
            spec["independence"]["separate_process_from_implementation"] = False
            spec["independence"]["implementation_functions_imported_for_verification"] = True
            spec["clean_room"]["network_access"] = True
            spec["clean_room"]["inherit_pythonpath"] = True

        with TemporaryDirectory() as directory:
            report, _result, _paths = self.audit(Path(directory), mutate)

        spec_check = find_check(report, "verification_spec_is_independent_and_predeclared")
        self.assertFalse(spec_check["valid"])
        self.assertEqual(len(spec_check["observed"]["errors"]), 4)

    def test_runner_harness_and_lock_hashes_are_pinned(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.inputs(root)
            runner_copy = root / "changed_runner.py"
            shutil.copy2(paths["implementation_runner"], runner_copy)
            runner_copy.write_text(
                runner_copy.read_text(encoding="utf-8") + "\n# changed after pinning\n",
                encoding="utf-8",
            )
            report, _result = VERIFIER.audit_verification(
                upstream_implementation_package=paths["upstream_implementation_package"],
                implementation_runner=runner_copy,
                upstream_baseline_package=paths["upstream_baseline_package"],
                verification_spec_path=paths["verification_spec_path"],
            )

        spec_check = find_check(report, "verification_spec_is_independent_and_predeclared")
        self.assertFalse(spec_check["valid"])
        self.assertEqual(
            spec_check["observed"]["errors"][0]["field"],
            "source_contract.implementation_runner_sha256",
        )

    def test_observed_result_fields_are_forbidden_in_predeclared_spec(self) -> None:
        def mutate(spec: dict) -> None:
            spec["observed_result"] = {"candidate_value": 0.8, "selected_method": "candidate"}

        with TemporaryDirectory() as directory:
            report, _result, _paths = self.audit(Path(directory), mutate)

        spec_check = find_check(report, "verification_spec_is_independent_and_predeclared")
        self.assertFalse(spec_check["valid"])
        forbidden = next(
            item for item in spec_check["observed"]["errors"] if item["field"] == "predeclared_spec"
        )
        self.assertEqual(len(forbidden["forbidden_paths"]), 3)

    def test_all_route_variants_have_explicit_verification_profiles(self) -> None:
        profiles = [
            ("core_analytics", "standard"),
            ("product_experiments", "standard"),
            ("data_analytics_engineering", "standard"),
            ("decision_science", "causal"),
            ("decision_science", "forecast"),
            ("machine_learning", "baseline"),
            ("machine_learning", "strong_model"),
            ("delivery_product", "standard"),
        ]
        runner = VERIFIER.implementation_runner_path()
        for route, variant in profiles:
            with self.subTest(route=route, variant=variant):
                state = {
                    "project_id": "project",
                    "data_contract_id": "contract",
                    "baseline_id": "baseline",
                    "implementation_id": "project-implementation-v1",
                    "route": route,
                    "route_variant": variant,
                }
                spec = VERIFIER.default_verification_spec(state, runner)

                route_check = VERIFIER.validate_route_profile(spec, state)

                self.assertTrue(route_check["valid"])
                self.assertEqual(len(spec["route_verification_profile"]["required_controls"]), 4)

    def test_route_profile_adapter_claim_and_controls_cannot_drift(self) -> None:
        def mutate(spec: dict) -> None:
            profile = spec["route_verification_profile"]
            profile["adapter_kind"] = "screenshot_review"
            profile["claim_boundary"] = "causal_effect"
            profile["required_controls"] = ["looks_reasonable"]

        with TemporaryDirectory() as directory:
            report, _result, _paths = self.audit(Path(directory), mutate)

        route_check = find_check(report, "route_specific_verification_profile_is_complete")
        self.assertFalse(route_check["valid"])

    def test_clean_room_rerun_matches_every_output_without_volatile_paths(self) -> None:
        with TemporaryDirectory() as directory:
            report, result, _paths = self.audit(Path(directory))

        clean = result["clean_room_report"]
        self.assertTrue(find_check(report, "clean_room_rerun_matches_published_package")["valid"])
        self.assertTrue(clean["published_manifest_match"])
        self.assertEqual(len(clean["output_comparisons"]), 10)
        self.assertTrue(all(row["match"] for row in clean["output_comparisons"]))
        self.assertFalse(clean["implementation_functions_imported"])
        self.assertFalse(clean["pythonpath_inherited"])
        self.assertNotIn("manifest", clean["stdout_payload"])
        self.assertNotIn("output_dir", clean["stdout_payload"])

    def test_rehashed_published_result_that_runner_cannot_reproduce_blocks_clean_room(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.inputs(root)
            package = paths["upstream_implementation_package"]
            decision_path = package / "candidate_decision.json"
            decision = read_json(decision_path)
            decision["selected_segments"] = ["self_serve"]
            write_json(decision_path, decision)
            self.refresh_implementation_output(
                package, "candidate_decision", "candidate_decision.json"
            )
            report, _result = VERIFIER.audit_verification(
                upstream_implementation_package=package,
                implementation_runner=paths["implementation_runner"],
                upstream_baseline_package=paths["upstream_baseline_package"],
                verification_spec_path=paths["verification_spec_path"],
            )

        self.assertTrue(find_check(report, "upstream_implementation_package_is_immutable")["valid"])
        clean = find_check(report, "clean_room_rerun_matches_published_package")
        self.assertFalse(clean["valid"])
        self.assertIn("candidate_decision", clean["observed"]["mismatches"])

    def test_shadow_recalculates_components_ranking_denominator_and_gate(self) -> None:
        with TemporaryDirectory() as directory:
            report, result, _paths = self.audit(Path(directory))

        shadow = find_check(report, "shadow_calculation_matches_published_result")
        self.assertTrue(shadow["valid"])
        summary = result["shadow_summary"]
        self.assertEqual(summary["selected_segments"], ["high_touch"])
        self.assertEqual(summary["captured_churned_users"], 2)
        self.assertEqual(summary["total_churned_users"], 3)
        self.assertEqual(summary["candidate_value"], 0.666667)
        self.assertFalse(summary["candidate_pass"])
        self.assertEqual(summary["selected_method"], "baseline")
        self.assertEqual(len(result["shadow_rows"]), 22)
        self.assertTrue(all(row["passed"] for row in result["shadow_rows"]))

    def test_changed_shadow_denominator_is_detected(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.inputs(root)
            baseline_rows, _fields = VERIFIER.read_csv(
                paths["upstream_baseline_package"] / "baseline_metrics.csv"
            )
            package = paths["upstream_implementation_package"]
            shadow, rows, summary = VERIFIER.independent_shadow_calculation(
                baseline_metrics=baseline_rows,
                implementation_spec=read_json(package / "implementation_spec.json"),
                published_metrics=VERIFIER.read_csv(package / "candidate_metrics.csv")[0],
                published_decision=read_json(package / "candidate_decision.json"),
                published_acceptance=read_json(package / "candidate_acceptance.json"),
                acceptance_gate=read_json(
                    paths["upstream_baseline_package"] / "acceptance_gate.json"
                ),
                denominator_adjustment=1,
            )

        self.assertFalse(shadow["valid"])
        self.assertEqual(summary["candidate_value"], 0.5)
        self.assertIn("decision:candidate_value", shadow["observed"]["failed_rows"])
        self.assertTrue(any(not row["passed"] for row in rows))

    def test_shadow_tolerance_and_threshold_come_from_immutable_gate(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.inputs(root)
            package = paths["upstream_implementation_package"]
            gate = read_json(paths["upstream_baseline_package"] / "acceptance_gate.json")
            gate["candidate_threshold"] = 0.666667
            baseline_rows, _fields = VERIFIER.read_csv(
                paths["upstream_baseline_package"] / "baseline_metrics.csv"
            )
            shadow, _rows, summary = VERIFIER.independent_shadow_calculation(
                baseline_metrics=baseline_rows,
                implementation_spec=read_json(package / "implementation_spec.json"),
                published_metrics=VERIFIER.read_csv(package / "candidate_metrics.csv")[0],
                published_decision=read_json(package / "candidate_decision.json"),
                published_acceptance=read_json(package / "candidate_acceptance.json"),
                acceptance_gate=gate,
            )

        self.assertFalse(shadow["valid"])
        self.assertTrue(summary["candidate_pass"])
        self.assertIn("decision:candidate_threshold", shadow["observed"]["failed_rows"])

    def test_four_negative_fixtures_fail_at_their_specific_gates(self) -> None:
        with TemporaryDirectory() as directory:
            report, result, _paths = self.audit(Path(directory))

        fixture_check = find_check(report, "negative_fixtures_fail_at_expected_gates")
        self.assertTrue(fixture_check["valid"])
        self.assertEqual(
            {row["fixture_id"]: row["observed_check_id"] for row in result["fixture_rows"]},
            VERIFIER.REQUIRED_FIXTURES,
        )
        self.assertTrue(all(row["detected"] for row in result["fixture_rows"]))
        self.assertTrue(all(row["fixture_copy_removed"] for row in result["fixture_rows"]))

    def test_missing_predeclared_negative_fixture_blocks_verification(self) -> None:
        def mutate(spec: dict) -> None:
            spec["negative_fixtures"] = spec["negative_fixtures"][:-1]

        with TemporaryDirectory() as directory:
            report, _result, _paths = self.audit(Path(directory), mutate)

        spec_check = find_check(report, "verification_spec_is_independent_and_predeclared")
        self.assertFalse(spec_check["valid"])
        self.assertIn(
            "negative_fixtures",
            {item["field"] for item in spec_check["observed"]["errors"]},
        )

    def test_sensitivity_preserves_frozen_gate_and_reports_threshold_flip(self) -> None:
        with TemporaryDirectory() as directory:
            report, result, _paths = self.audit(Path(directory))

        sensitivity = find_check(
            report, "sensitivity_analysis_preserves_frozen_gate_and_reports_flips"
        )
        self.assertTrue(sensitivity["valid"])
        rows = {row["scenario_id"]: row for row in result["sensitivity_rows"]}
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows["frozen_gate"]["selected_method"], "baseline")
        self.assertTrue(rows["frozen_gate"]["is_frozen_gate"])
        self.assertEqual(
            rows["threshold_minus_practical_improvement"]["selected_method"],
            "candidate",
        )
        self.assertFalse(rows["capacity_minus_one"]["capacity_pass"])

    def test_claim_audit_requires_exact_fields_limitations_and_shadow_support(self) -> None:
        with TemporaryDirectory() as directory:
            report, result, _paths = self.audit(Path(directory))

        claims = find_check(report, "every_claim_is_supported_by_exact_evidence_and_shadow")
        self.assertTrue(claims["valid"])
        self.assertEqual(len(result["claim_rows"]), 3)
        for row in result["claim_rows"]:
            self.assertTrue(row["path_exists"])
            self.assertTrue(row["fields_exist"])
            self.assertTrue(row["limitation_present"])
            self.assertTrue(row["claim_type_allowed"])
            self.assertTrue(row["shadow_supported"])
            self.assertEqual(row["status"], "verified")

    def test_rehashed_missing_evidence_field_blocks_claim_traceability(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.inputs(root)
            package = paths["upstream_implementation_package"]
            ledger_path = package / "evidence_ledger.csv"
            rows, fields = VERIFIER.read_csv(ledger_path)
            rows[0]["evidence_fields"] += "|unknown_field"
            VERIFIER.write_csv(ledger_path, rows, fields)
            self.refresh_implementation_output(package, "evidence_ledger", "evidence_ledger.csv")
            report, _result = VERIFIER.audit_verification(
                upstream_implementation_package=package,
                implementation_runner=paths["implementation_runner"],
                upstream_baseline_package=paths["upstream_baseline_package"],
                verification_spec_path=paths["verification_spec_path"],
            )

        claim_check = find_check(report, "every_claim_is_supported_by_exact_evidence_and_shadow")
        self.assertFalse(claim_check["valid"])
        self.assertEqual(claim_check["observed"]["blocked_claims"], ["implementation-claim-01"])

    def test_required_skip_or_xfail_is_disclosed_and_blocks_green_summary(self) -> None:
        def mutate(spec: dict) -> None:
            spec["test_disclosure"]["skipped"] = [
                {
                    "test_id": "shadow_calculation",
                    "reason": "oracle unavailable",
                }
            ]

        with TemporaryDirectory() as directory:
            report, result, _paths = self.audit(Path(directory), mutate)

        disclosure = find_check(report, "skipped_and_xfail_tests_are_disclosed")
        self.assertFalse(disclosure["valid"])
        self.assertEqual(
            result["test_results"]["summary"]["required_disclosed_as_skip_or_xfail"],
            ["shadow_calculation"],
        )

    def test_reference_route_controls_reconcile_grain_denominator_ranking_and_claim(self) -> None:
        with TemporaryDirectory() as directory:
            _report, result, _paths = self.audit(Path(directory))

        route_report = result["route_report"]
        self.assertTrue(route_report["valid"])
        self.assertEqual(route_report["adapter_kind"], "weighted_segment_priority")
        self.assertEqual(len(route_report["controls"]), 4)
        self.assertTrue(all(control["passed"] for control in route_report["controls"]))

    def test_state_advances_only_to_verification_and_keeps_later_ids_null(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.inputs(root)
            result = VERIFIER.build_verification_package(
                upstream_implementation_package=paths["upstream_implementation_package"],
                implementation_runner=paths["implementation_runner"],
                upstream_baseline_package=paths["upstream_baseline_package"],
                verification_spec_path=paths["verification_spec_path"],
                output_dir=root / "package",
            )
            state = read_json(result["state_path"])

        self.assertEqual(state["current_stage"], "verification")
        self.assertEqual(state["stage_status"], "verification_ready")
        self.assertEqual(state["verification_id"], "weekly-retention-core-verification-v1")
        self.assertIsNone(state["review_id"])
        self.assertIsNone(state["defense_id"])
        self.assertEqual(state["open_blockers"], [])
        self.assertIn("shadow_calculation.csv", state["artifact_inventory"])

    def test_manifest_hashes_nested_outputs_and_package_is_deterministic(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.inputs(root)
            first = VERIFIER.build_verification_package(
                upstream_implementation_package=paths["upstream_implementation_package"],
                implementation_runner=paths["implementation_runner"],
                upstream_baseline_package=paths["upstream_baseline_package"],
                verification_spec_path=paths["verification_spec_path"],
                output_dir=root / "first",
            )
            second = VERIFIER.build_verification_package(
                upstream_implementation_package=paths["upstream_implementation_package"],
                implementation_runner=paths["implementation_runner"],
                upstream_baseline_package=paths["upstream_baseline_package"],
                verification_spec_path=paths["verification_spec_path"],
                output_dir=root / "second",
            )
            manifest = read_json(first["manifest_path"])

            self.assertTrue(manifest["independent_source_used"])
            self.assertTrue(manifest["clean_room_temporary_workspace"])
            self.assertFalse(manifest["implementation_functions_imported_for_verification"])
            self.assertFalse(manifest["raw_sources_copied"])
            self.assertFalse(manifest["upstream_inputs_mutated"])
            self.assertFalse(manifest["fixture_mutations_persisted"])
            self.assertEqual(manifest["selected_method"], "baseline")
            for entry in manifest["outputs"].values():
                path = first["output_dir"] / entry["path"]
                self.assertEqual(entry["sha256"], VERIFIER.sha256_file(path))
                self.assertEqual(entry["bytes"], path.stat().st_size)
            self.assertEqual(
                VERIFIER.sha256_file(first["manifest_path"]),
                VERIFIER.sha256_file(second["manifest_path"]),
            )

    def test_audit_never_mutates_upstream_packages_or_spec(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.inputs(root)
            before = {
                "implementation": VERIFIER.directory_checksums(
                    paths["upstream_implementation_package"]
                ),
                "baseline": VERIFIER.directory_checksums(paths["upstream_baseline_package"]),
                "spec": VERIFIER.sha256_file(paths["verification_spec_path"]),
            }
            VERIFIER.audit_verification(
                upstream_implementation_package=paths["upstream_implementation_package"],
                implementation_runner=paths["implementation_runner"],
                upstream_baseline_package=paths["upstream_baseline_package"],
                verification_spec_path=paths["verification_spec_path"],
            )
            after = {
                "implementation": VERIFIER.directory_checksums(
                    paths["upstream_implementation_package"]
                ),
                "baseline": VERIFIER.directory_checksums(paths["upstream_baseline_package"]),
                "spec": VERIFIER.sha256_file(paths["verification_spec_path"]),
            }

        self.assertEqual(before, after)

    def test_public_boundary_rejects_restricted_candidate_columns(self) -> None:
        state = {
            "current_stage": "implementation",
            "stage_status": "implementation_ready",
            "review_id": None,
            "defense_id": None,
        }
        boundary = VERIFIER.validate_public_boundary_and_stage(
            state=state,
            metrics_fields=["segment_id", "user_id", "api_key"],
            upstream_before={"implementation": {}, "baseline": {}},
            upstream_after={"implementation": {}, "baseline": {}},
        )

        self.assertFalse(boundary["valid"])
        self.assertEqual(
            boundary["observed"]["errors"][0]["restricted_columns"],
            ["api_key", "user_id"],
        )

    def test_cli_exit_codes_distinguish_blocked_verification_and_missing_inputs(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.inputs(root)
            spec = read_json(paths["verification_spec_path"])
            spec["independence"]["separate_process_from_implementation"] = False
            write_json(paths["verification_spec_path"], spec)
            blocked = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--upstream-implementation-package",
                    paths["upstream_implementation_package"],
                    "--implementation-runner",
                    paths["implementation_runner"],
                    "--upstream-baseline-package",
                    paths["upstream_baseline_package"],
                    "--verification-spec",
                    paths["verification_spec_path"],
                    "--output-dir",
                    root / "blocked",
                    "--fail-on-invalid",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            missing = subprocess.run(
                [sys.executable, ARTIFACT, "--output-dir", root / "missing"],
                capture_output=True,
                text=True,
            )

        self.assertEqual(blocked.returncode, 1)
        self.assertEqual(json.loads(blocked.stdout)["status"], "verification_block")
        self.assertEqual(missing.returncode, 2)
        self.assertEqual(json.loads(missing.stdout)["status"], "system_error")
