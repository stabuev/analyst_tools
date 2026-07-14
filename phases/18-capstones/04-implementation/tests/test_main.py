from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

LESSON_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = LESSON_ROOT / "outputs" / "capstone_route_implementation.py"
CODE = LESSON_ROOT / "code" / "main.py"
sys.path.insert(0, str(LESSON_ROOT / "outputs"))

import capstone_route_implementation as IMPLEMENTATION  # noqa: E402


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: dict) -> Path:
    IMPLEMENTATION.write_json(path, value)
    return path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def find_check(report: dict, check_id: str) -> dict:
    return next(item for item in report["checks"] if item["id"] == check_id)


class CapstoneRouteImplementationTest(TestCase):
    def inputs(self, root: Path) -> dict[str, Path]:
        return IMPLEMENTATION.write_sample_inputs(root / "inputs")

    def audit(self, root: Path, mutate=None) -> tuple[dict, dict, dict]:
        paths = self.inputs(root)
        spec = read_json(paths["implementation_spec_path"])
        if mutate is not None:
            mutate(spec)
            write_json(paths["implementation_spec_path"], spec)
        report, result = IMPLEMENTATION.audit_implementation(
            upstream_baseline_package=paths["upstream_baseline_package"],
            implementation_spec_path=paths["implementation_spec_path"],
        )
        return report, result, paths

    def refresh_upstream_entry(self, package: Path, key: str, filename: str) -> None:
        manifest_path = package / "baseline_manifest.json"
        manifest = read_json(manifest_path)
        path = package / filename
        manifest["outputs"][key]["sha256"] = sha256(path)
        manifest["outputs"][key]["bytes"] = path.stat().st_size
        write_json(manifest_path, manifest)

    def test_reference_candidate_is_honestly_rejected_but_implementation_is_ready(self) -> None:
        with TemporaryDirectory() as directory:
            report, result, _paths = self.audit(Path(directory))

        self.assertTrue(report["valid"])
        self.assertEqual(report["status"], "implementation_ready")
        self.assertEqual(report["summary"]["next_stage"], "verification")
        self.assertEqual(report["summary"]["check_count"], 11)
        self.assertEqual(report["summary"]["candidate_rows"], 2)
        self.assertEqual(report["summary"]["selected_segments"], ["high_touch"])
        self.assertEqual(report["summary"]["candidate_value"], 0.666667)
        self.assertEqual(report["summary"]["candidate_threshold"], 0.766667)
        self.assertFalse(report["summary"]["candidate_pass"])
        self.assertEqual(report["summary"]["selected_method"], "baseline")
        self.assertEqual(
            result["candidate_acceptance"]["decision_status"], "candidate_rejected_keep_baseline"
        )
        self.assertIn("candidate_did_not_clear_practical_threshold", report["summary"]["warnings"])

    def test_code_example_writes_complete_implementation_package(self) -> None:
        result = subprocess.run(
            [sys.executable, CODE], check=True, capture_output=True, text=True, timeout=30
        )
        payload = json.loads(result.stdout)

        self.assertTrue(payload["valid"])
        self.assertEqual(payload["status"], "implementation_ready")
        self.assertFalse(payload["candidate_pass"])
        self.assertEqual(payload["selected_method"], "baseline")
        for name in (
            "implementation_spec.json",
            "implementation_report.json",
            "implementation_config.json",
            "route_adapter_report.json",
            "candidate_metrics.csv",
            "candidate_decision.json",
            "candidate_acceptance.json",
            "evidence_ledger.csv",
            "run_trace.csv",
            "capstone_state.json",
            "implementation_manifest.json",
        ):
            self.assertTrue((LESSON_ROOT / "outputs" / name).is_file(), name)

    def test_cli_write_example_and_help_expose_immutable_inputs(self) -> None:
        help_result = subprocess.run(
            [sys.executable, ARTIFACT, "--help"],
            check=True,
            capture_output=True,
            text=True,
        )
        for option in (
            "--upstream-baseline-package",
            "--implementation-spec",
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
                timeout=30,
            )
            payload = json.loads(result.stdout)

            self.assertEqual(payload["status"], "implementation_ready")
            self.assertTrue((root / "input" / "implementation_spec.json").is_file())
            self.assertTrue((root / "package" / "implementation_manifest.json").is_file())

    def test_upstream_baseline_state_tampering_blocks_run(self) -> None:
        with TemporaryDirectory() as directory:
            paths = self.inputs(Path(directory))
            state_path = paths["upstream_baseline_package"] / "capstone_state.json"
            state = read_json(state_path)
            state["baseline_id"] = "changed-after-baseline"
            write_json(state_path, state)
            report, _result = IMPLEMENTATION.audit_implementation(
                upstream_baseline_package=paths["upstream_baseline_package"],
                implementation_spec_path=paths["implementation_spec_path"],
            )

        upstream = find_check(report, "upstream_baseline_is_ready_immutable_and_untampered")
        self.assertFalse(upstream["valid"])
        self.assertEqual(
            upstream["observed"]["errors"][0]["field"], "outputs.capstone_state.sha256"
        )

    def test_frozen_acceptance_gate_tampering_blocks_run(self) -> None:
        with TemporaryDirectory() as directory:
            paths = self.inputs(Path(directory))
            gate_path = paths["upstream_baseline_package"] / "acceptance_gate.json"
            gate = read_json(gate_path)
            gate["candidate_threshold"] = 0.6
            write_json(gate_path, gate)
            report, _result = IMPLEMENTATION.audit_implementation(
                upstream_baseline_package=paths["upstream_baseline_package"],
                implementation_spec_path=paths["implementation_spec_path"],
            )

        upstream = find_check(report, "upstream_baseline_is_ready_immutable_and_untampered")
        self.assertFalse(upstream["valid"])
        self.assertEqual(
            upstream["observed"]["errors"][0]["field"], "outputs.acceptance_gate.sha256"
        )

    def test_spec_ids_and_route_must_match_upstream_state(self) -> None:
        def mutate(spec: dict) -> None:
            spec["project_id"] = "another-project"
            spec["contract_id"] = "another-contract"
            spec["baseline_id"] = "another-baseline"
            spec["route"] = "machine_learning"

        with TemporaryDirectory() as directory:
            report, _result, _paths = self.audit(Path(directory), mutate)

        structure = find_check(report, "implementation_spec_matches_frozen_upstream_contracts")
        self.assertFalse(structure["valid"])
        self.assertEqual(
            {item["field"] for item in structure["observed"]["errors"]},
            {"project_id", "contract_id", "baseline_id", "route"},
        )

    def test_all_route_variants_have_explicit_adapter_profiles(self) -> None:
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
        for route, variant in profiles:
            with self.subTest(route=route, variant=variant):
                state = {
                    "project_id": "project",
                    "data_contract_id": "contract",
                    "baseline_id": "baseline",
                    "route": route,
                    "route_variant": variant,
                }
                spec = IMPLEMENTATION.default_implementation_spec(state)

                route_check = IMPLEMENTATION.validate_route_adapter(spec, state)

                self.assertTrue(route_check["valid"], route_check["observed"]["errors"])

    def test_adapter_kind_output_grain_and_claim_boundary_cannot_drift(self) -> None:
        def mutate(spec: dict) -> None:
            adapter = spec["route_adapter"]
            adapter["adapter_kind"] = "hidden_notebook"
            adapter["primary_output"] = "screenshot.png"
            adapter["claim_boundary"] = "causal_effect"
            adapter["output_grain"] = ["user_id"]

        with TemporaryDirectory() as directory:
            report, _result, _paths = self.audit(Path(directory), mutate)

        route_check = find_check(report, "route_adapter_is_explicit_and_respects_claim_boundary")
        self.assertFalse(route_check["valid"])
        self.assertEqual(len(route_check["observed"]["errors"]), 4)

    def test_weights_must_be_nonnegative_and_sum_to_one(self) -> None:
        def mutate(spec: dict) -> None:
            spec["frozen_config"]["score_weights"] = {
                "churn_rate": 0.9,
                "activation_gap": 0.4,
                "support_load": -0.3,
            }

        with TemporaryDirectory() as directory:
            report, _result, _paths = self.audit(Path(directory), mutate)

        config = find_check(report, "config_policy_and_threshold_sources_are_frozen_before_run")
        self.assertFalse(config["valid"])
        self.assertEqual(config["observed"]["errors"][0]["field"], "score_weights")

    def test_observed_candidate_fields_are_forbidden_in_predeclared_spec(self) -> None:
        def mutate(spec: dict) -> None:
            spec["candidate_policy"]["candidate_value"] = 0.8
            spec["candidate_policy"]["selected_method"] = "candidate"

        with TemporaryDirectory() as directory:
            report, _result, _paths = self.audit(Path(directory), mutate)

        config = find_check(report, "config_policy_and_threshold_sources_are_frozen_before_run")
        self.assertFalse(config["valid"])
        paths = config["observed"]["errors"][0]["paths"]
        self.assertEqual(len(paths), 2)

    def test_baseline_metric_schema_and_grain_are_immutable_adapter_inputs(self) -> None:
        with TemporaryDirectory() as directory:
            paths = self.inputs(Path(directory))
            package = paths["upstream_baseline_package"]
            metrics_path = package / "baseline_metrics.csv"
            rows, fields = IMPLEMENTATION.read_csv(metrics_path)
            rows.append(dict(rows[0]))
            IMPLEMENTATION.write_csv(metrics_path, rows, fields)
            self.refresh_upstream_entry(package, "baseline_metrics", "baseline_metrics.csv")
            report, _result = IMPLEMENTATION.audit_implementation(
                upstream_baseline_package=package,
                implementation_spec_path=paths["implementation_spec_path"],
            )

        input_check = find_check(
            report, "adapter_input_preserves_approved_aggregate_grain_and_metrics"
        )
        self.assertFalse(input_check["valid"])
        self.assertEqual(input_check["observed"]["errors"][0]["field"], "grain")

    def test_churn_rate_is_reconciled_from_counts_before_scoring(self) -> None:
        with TemporaryDirectory() as directory:
            paths = self.inputs(Path(directory))
            package = paths["upstream_baseline_package"]
            metrics_path = package / "baseline_metrics.csv"
            rows, fields = IMPLEMENTATION.read_csv(metrics_path)
            rows[0]["churn_rate"] = "0.1"
            IMPLEMENTATION.write_csv(metrics_path, rows, fields)
            self.refresh_upstream_entry(package, "baseline_metrics", "baseline_metrics.csv")
            report, _result = IMPLEMENTATION.audit_implementation(
                upstream_baseline_package=package,
                implementation_spec_path=paths["implementation_spec_path"],
            )

        input_check = find_check(
            report, "adapter_input_preserves_approved_aggregate_grain_and_metrics"
        )
        self.assertFalse(input_check["valid"])
        self.assertEqual(input_check["observed"]["errors"][0]["field"], "churn_rate")

    def test_candidate_score_components_and_ranking_are_deterministic(self) -> None:
        with TemporaryDirectory() as directory:
            report, result, _paths = self.audit(Path(directory))

        self.assertTrue(
            find_check(report, "route_adapter_produces_deterministic_bounded_candidate_outputs")[
                "valid"
            ]
        )
        metrics = result["candidate_metrics"]
        self.assertEqual(metrics[0]["segment_id"], "high_touch")
        self.assertEqual(metrics[0]["candidate_score"], 1.0)
        self.assertEqual(metrics[1]["candidate_score"], 0.0)
        self.assertEqual([row["candidate_rank"] for row in metrics], [1, 2])

    def test_candidate_failure_does_not_become_an_implementation_blocker(self) -> None:
        with TemporaryDirectory() as directory:
            report, result, _paths = self.audit(Path(directory))

        acceptance = find_check(
            report, "candidate_is_compared_to_the_frozen_acceptance_and_capacity_gate"
        )
        self.assertTrue(acceptance["valid"])
        self.assertFalse(result["candidate_acceptance"]["candidate_pass"])
        self.assertEqual(report["summary"]["blocking_errors"], [])

    def test_candidate_can_be_selected_only_when_metric_and_capacity_pass(self) -> None:
        gate = {
            "metric_id": "captured_churn_recall",
            "direction": "maximize",
            "baseline_value": 0.666667,
            "candidate_threshold": 0.766667,
            "tolerance": 0.000001,
            "max_capacity": 4,
        }
        decision = {"candidate_value": 0.8, "reviewed_users": 4}

        result, acceptance = IMPLEMENTATION.evaluate_candidate(decision, gate)

        self.assertTrue(acceptance["valid"])
        self.assertTrue(result["candidate_pass"])
        self.assertEqual(result["selected_method"], "candidate")

    def test_capacity_overrun_blocks_acceptance_evaluation(self) -> None:
        gate = {
            "metric_id": "captured_churn_recall",
            "direction": "maximize",
            "baseline_value": 0.666667,
            "candidate_threshold": 0.766667,
            "tolerance": 0.000001,
            "max_capacity": 4,
        }
        decision = {"candidate_value": 1.0, "reviewed_users": 8}

        result, acceptance = IMPLEMENTATION.evaluate_candidate(decision, gate)

        self.assertFalse(acceptance["valid"])
        self.assertFalse(result["candidate_pass"])
        self.assertEqual(acceptance["observed"]["errors"][0]["field"], "capacity")

    def test_environment_and_dependency_count_must_fit_complexity_budget(self) -> None:
        def mutate(spec: dict) -> None:
            spec["environment"]["manager"] = "pip"
            spec["environment"]["standard_library_only"] = False
            spec["environment"]["new_runtime_dependencies"] = ["a", "b"]

        with TemporaryDirectory() as directory:
            report, _result, _paths = self.audit(Path(directory), mutate)

        complexity = find_check(
            report, "implementation_stays_within_complexity_and_locked_environment_budget"
        )
        self.assertFalse(complexity["valid"])
        self.assertEqual(len(complexity["observed"]["errors"]), 3)

    def test_evidence_claims_require_unique_ids_paths_fields_and_limitations(self) -> None:
        def mutate(spec: dict) -> None:
            claims = spec["evidence_claims"]
            claims[1]["claim_id"] = claims[0]["claim_id"]
            claims[1]["evidence_path"] = "unknown.txt"
            claims[1]["evidence_fields"] = []
            claims[1]["limitation"] = ""

        with TemporaryDirectory() as directory:
            report, _result, _paths = self.audit(Path(directory), mutate)

        evidence = find_check(report, "evidence_ledger_links_every_claim_to_output_and_limitation")
        self.assertFalse(evidence["valid"])
        fields = {item["field"] for item in evidence["observed"]["errors"]}
        self.assertEqual(fields, {"limitation", "evidence_fields", "evidence_path", "claim_id"})

    def test_claim_type_cannot_exceed_upstream_boundary(self) -> None:
        def mutate(spec: dict) -> None:
            spec["evidence_claims"][0]["claim_type"] = "causal"

        with TemporaryDirectory() as directory:
            report, _result, _paths = self.audit(Path(directory), mutate)

        evidence = find_check(report, "evidence_ledger_links_every_claim_to_output_and_limitation")
        self.assertFalse(evidence["valid"])
        self.assertEqual(evidence["observed"]["errors"][0]["allowed"], "descriptive")

    def test_reproducible_command_requires_locked_relative_complete_cli(self) -> None:
        def mutate(spec: dict) -> None:
            spec["reproducible_command"] = "/Users/me/python notebook.py"

        with TemporaryDirectory() as directory:
            report, _result, _paths = self.audit(Path(directory), mutate)

        command = find_check(report, "one_locked_relative_command_rebuilds_the_complete_package")
        self.assertFalse(command["valid"])
        self.assertGreaterEqual(len(command["observed"]["errors"]), 6)

    def test_public_boundary_rejects_restricted_candidate_columns(self) -> None:
        state = {
            "implementation_id": None,
            "verification_id": None,
            "review_id": None,
            "defense_id": None,
        }

        boundary = IMPLEMENTATION.validate_public_boundary(
            [{"segment_id": "high_touch", "user_id": "u1"}], state
        )

        self.assertFalse(boundary["valid"])
        self.assertEqual(boundary["observed"]["errors"][0]["restricted_columns"], ["user_id"])

    def test_package_state_advances_only_to_implementation(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.inputs(root)
            result = IMPLEMENTATION.build_implementation_package(
                upstream_baseline_package=paths["upstream_baseline_package"],
                implementation_spec_path=paths["implementation_spec_path"],
                output_dir=root / "package",
            )
            state = read_json(result["state_path"])

        self.assertEqual(state["current_stage"], "implementation")
        self.assertEqual(state["stage_status"], "implementation_ready")
        self.assertEqual(state["implementation_id"], "weekly-retention-core-implementation-v1")
        self.assertIsNone(state["verification_id"])
        self.assertEqual(state["open_blockers"], [])
        self.assertIn("evidence_ledger.csv", state["artifact_inventory"])

    def test_manifest_hashes_every_output_and_records_baseline_selection(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.inputs(root)
            result = IMPLEMENTATION.build_implementation_package(
                upstream_baseline_package=paths["upstream_baseline_package"],
                implementation_spec_path=paths["implementation_spec_path"],
                output_dir=root / "package",
            )
            manifest = read_json(result["manifest_path"])

            self.assertFalse(manifest["raw_sources_copied"])
            self.assertFalse(manifest["upstream_inputs_mutated"])
            self.assertFalse(manifest["candidate_pass"])
            self.assertEqual(manifest["selected_method"], "baseline")
            self.assertEqual(manifest["renderer_used"], "capstone_route_implementation")
            for entry in manifest["outputs"].values():
                path = result["output_dir"] / entry["path"]
                self.assertEqual(entry["sha256"], sha256(path))
                self.assertEqual(entry["bytes"], path.stat().st_size)

    def test_run_trace_is_ordered_complete_and_uses_one_implementation_id(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.inputs(root)
            result = IMPLEMENTATION.build_implementation_package(
                upstream_baseline_package=paths["upstream_baseline_package"],
                implementation_spec_path=paths["implementation_spec_path"],
                output_dir=root / "package",
            )
            rows, _fields = IMPLEMENTATION.read_csv(result["trace_path"])

        self.assertEqual([int(row["sequence"]) for row in rows], list(range(1, 7)))
        self.assertTrue(all(row["status"] == "completed" for row in rows))
        self.assertEqual(
            {row["implementation_id"] for row in rows}, {"weekly-retention-core-implementation-v1"}
        )
        self.assertEqual({row["selected_method"] for row in rows}, {"baseline"})

    def test_cli_exit_codes_distinguish_blocked_spec_and_missing_inputs(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.inputs(root)
            spec = read_json(paths["implementation_spec_path"])
            spec["frozen_config"]["score_weights"]["churn_rate"] = 2.0
            write_json(paths["implementation_spec_path"], spec)
            blocked = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--upstream-baseline-package",
                    paths["upstream_baseline_package"],
                    "--implementation-spec",
                    paths["implementation_spec_path"],
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
        self.assertEqual(json.loads(blocked.stdout)["status"], "implementation_block")
        self.assertEqual(missing.returncode, 2)
        self.assertEqual(json.loads(missing.stdout)["error"]["code"], "missing_inputs")

    def test_audit_does_not_mutate_spec_or_upstream_package(self) -> None:
        with TemporaryDirectory() as directory:
            paths = self.inputs(Path(directory))
            spec_before = Path(paths["implementation_spec_path"]).read_bytes()
            baseline_path = paths["upstream_baseline_package"] / "baseline_metrics.csv"
            baseline_before = baseline_path.read_bytes()

            IMPLEMENTATION.audit_implementation(
                upstream_baseline_package=paths["upstream_baseline_package"],
                implementation_spec_path=paths["implementation_spec_path"],
            )

            self.assertEqual(Path(paths["implementation_spec_path"]).read_bytes(), spec_before)
            self.assertEqual(baseline_path.read_bytes(), baseline_before)


if __name__ == "__main__":
    import unittest

    unittest.main()
