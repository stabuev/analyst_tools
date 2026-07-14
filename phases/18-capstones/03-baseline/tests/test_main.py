from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

LESSON_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = LESSON_ROOT / "outputs" / "capstone_baseline_gate.py"
CODE = LESSON_ROOT / "code" / "main.py"
sys.path.insert(0, str(LESSON_ROOT / "outputs"))

import capstone_baseline_gate as BASELINE  # noqa: E402


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: dict) -> Path:
    BASELINE.write_json(path, value)
    return path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def find_check(report: dict, check_id: str) -> dict:
    return next(item for item in report["checks"] if item["id"] == check_id)


class CapstoneBaselineGateTest(TestCase):
    def inputs(self, root: Path) -> dict[str, Path]:
        return BASELINE.write_sample_inputs(root / "inputs")

    def audit(self, root: Path, mutate=None) -> tuple[dict, dict, dict]:
        paths = self.inputs(root)
        spec = read_json(paths["baseline_spec_path"])
        if mutate is not None:
            mutate(spec)
            write_json(paths["baseline_spec_path"], spec)
        report, result, manifest = BASELINE.audit_baseline(
            upstream_data_package=paths["upstream_data_package"],
            baseline_spec_path=paths["baseline_spec_path"],
        )
        return report, result, paths

    def refresh_upstream_entry(self, package: Path, key: str, filename: str) -> None:
        manifest_path = package / "data_package_manifest.json"
        manifest = read_json(manifest_path)
        path = package / filename
        manifest["outputs"][key]["sha256"] = sha256(path)
        manifest["outputs"][key]["bytes"] = path.stat().st_size
        write_json(manifest_path, manifest)

    def test_reference_baseline_is_ready_with_frozen_candidate_threshold(self) -> None:
        with TemporaryDirectory() as directory:
            report, result, _paths = self.audit(Path(directory))

        self.assertTrue(report["valid"])
        self.assertEqual(report["status"], "baseline_ready")
        self.assertEqual(report["summary"]["next_stage"], "implementation")
        self.assertEqual(report["summary"]["check_count"], 9)
        self.assertEqual(report["summary"]["metric_rows"], 2)
        self.assertEqual(report["summary"]["selected_segments"], ["high_touch"])
        self.assertEqual(report["summary"]["baseline_value"], 0.666667)
        self.assertEqual(report["summary"]["candidate_threshold"], 0.766667)
        self.assertIsNone(result["acceptance_gate"]["candidate_value"])
        self.assertIsNone(result["acceptance_gate"]["candidate_pass"])

    def test_code_example_writes_all_baseline_outputs(self) -> None:
        result = subprocess.run([sys.executable, CODE], check=True, capture_output=True, text=True)
        payload = json.loads(result.stdout)

        self.assertTrue(payload["valid"])
        self.assertEqual(payload["status"], "baseline_ready")
        self.assertEqual(payload["selected_segments"], ["high_touch"])
        for name in (
            "baseline_spec.json",
            "baseline_report.json",
            "baseline_metrics.csv",
            "baseline_decision.json",
            "manual_reconciliation.csv",
            "acceptance_gate.json",
            "complexity_budget.json",
            "capstone_state.json",
            "baseline_manifest.json",
        ):
            self.assertTrue((LESSON_ROOT / "outputs" / name).is_file(), name)

    def test_cli_write_example_and_help_expose_stage_inputs(self) -> None:
        help_result = subprocess.run(
            [sys.executable, ARTIFACT, "--help"],
            check=True,
            capture_output=True,
            text=True,
        )
        for option in (
            "--upstream-data-package",
            "--baseline-spec",
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

            self.assertEqual(payload["status"], "baseline_ready")
            self.assertTrue((root / "input" / "baseline_spec.json").is_file())
            self.assertTrue((root / "package" / "baseline_manifest.json").is_file())

    def test_upstream_state_tampering_blocks_baseline(self) -> None:
        with TemporaryDirectory() as directory:
            paths = self.inputs(Path(directory))
            state_path = paths["upstream_data_package"] / "capstone_state.json"
            state = read_json(state_path)
            state["decision"] = "changed after data approval"
            write_json(state_path, state)
            report, _result, _manifest = BASELINE.audit_baseline(
                upstream_data_package=paths["upstream_data_package"],
                baseline_spec_path=paths["baseline_spec_path"],
            )

        self.assertFalse(report["valid"])
        self.assertIn(
            "upstream_data_package_is_ready_and_untampered",
            report["summary"]["blocking_errors"],
        )

    def test_public_sample_tampering_blocks_before_recalculation(self) -> None:
        with TemporaryDirectory() as directory:
            paths = self.inputs(Path(directory))
            sample_path = paths["upstream_data_package"] / "public_data_sample.csv"
            rows, fields = BASELINE.read_csv(sample_path)
            rows[0]["churned_users"] = "4"
            BASELINE.write_csv(sample_path, rows, fields)
            report, _result, _manifest = BASELINE.audit_baseline(
                upstream_data_package=paths["upstream_data_package"],
                baseline_spec_path=paths["baseline_spec_path"],
            )

        upstream = find_check(report, "upstream_data_package_is_ready_and_untampered")
        self.assertFalse(upstream["valid"])
        self.assertEqual(
            upstream["observed"]["errors"][0]["field"], "outputs.public_data_sample.sha256"
        )

    def test_spec_must_match_upstream_project_contract_and_decision(self) -> None:
        def mutate(spec: dict) -> None:
            spec["project_id"] = "another-project"
            spec["contract_id"] = "another-contract"
            spec["decision_question"] = "another decision"

        with TemporaryDirectory() as directory:
            report, _result, _paths = self.audit(Path(directory), mutate)

        structure = find_check(report, "baseline_spec_matches_decision_and_data_contract")
        self.assertFalse(structure["valid"])
        self.assertEqual(
            {item["field"] for item in structure["observed"]["errors"]},
            {"project_id", "contract_id", "decision_question"},
        )

    def test_baseline_input_must_be_the_aggregate_public_sample(self) -> None:
        def mutate(spec: dict) -> None:
            spec["input_contract"]["path"] = "users.csv"
            spec["input_contract"]["publication_class"] = "restricted"

        with TemporaryDirectory() as directory:
            report, _result, _paths = self.audit(Path(directory), mutate)

        structure = find_check(report, "baseline_spec_matches_decision_and_data_contract")
        self.assertFalse(structure["valid"])
        self.assertEqual(len(structure["observed"]["errors"]), 2)

    def test_duplicate_aggregate_grain_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            paths = self.inputs(Path(directory))
            package = paths["upstream_data_package"]
            sample_path = package / "public_data_sample.csv"
            rows, fields = BASELINE.read_csv(sample_path)
            rows.append(dict(rows[0]))
            BASELINE.write_csv(sample_path, rows, fields)
            self.refresh_upstream_entry(package, "public_data_sample", "public_data_sample.csv")
            report, _result, _manifest = BASELINE.audit_baseline(
                upstream_data_package=package,
                baseline_spec_path=paths["baseline_spec_path"],
            )

        aggregate = find_check(report, "aggregate_input_has_valid_grain_counts_and_rates")
        self.assertFalse(aggregate["valid"])
        self.assertEqual(aggregate["observed"]["errors"][0]["field"], "grain")

    def test_count_bounds_and_published_rate_are_independently_checked(self) -> None:
        with TemporaryDirectory() as directory:
            paths = self.inputs(Path(directory))
            package = paths["upstream_data_package"]
            sample_path = package / "public_data_sample.csv"
            rows, fields = BASELINE.read_csv(sample_path)
            rows[0]["churned_users"] = "5"
            rows[1]["activation_rate"] = "0.900"
            BASELINE.write_csv(sample_path, rows, fields)
            self.refresh_upstream_entry(package, "public_data_sample", "public_data_sample.csv")
            report, _result, _manifest = BASELINE.audit_baseline(
                upstream_data_package=package,
                baseline_spec_path=paths["baseline_spec_path"],
            )

        errors = find_check(report, "aggregate_input_has_valid_grain_counts_and_rates")["observed"][
            "errors"
        ]
        self.assertIn("counts", {item["field"] for item in errors})
        self.assertIn("activation_rate", {item["field"] for item in errors})

    def test_all_route_variants_have_explicit_minimal_baselines(self) -> None:
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
                    "decision": "decision",
                    "route": route,
                    "route_variant": variant,
                }
                spec = BASELINE.default_baseline_spec(state)

                route_check = BASELINE.validate_route_profile(spec, state)

                self.assertTrue(route_check["valid"], route_check["observed"]["errors"])

    def test_route_kind_metric_and_claim_boundary_cannot_drift(self) -> None:
        def mutate(spec: dict) -> None:
            spec["baseline_policy"]["baseline_kind"] = "complex_ml_model"
            spec["baseline_policy"]["claim_boundary"] = "causal_effect"
            spec["baseline_policy"]["no_causal_claim"] = False
            spec["acceptance_metric"]["metric_id"] = "accuracy"

        with TemporaryDirectory() as directory:
            report, _result, _paths = self.audit(Path(directory), mutate)

        route_check = find_check(report, "route_baseline_is_minimal_and_claim_safe")
        self.assertFalse(route_check["valid"])
        self.assertEqual(len(route_check["observed"]["errors"]), 4)

    def test_ranking_uses_support_load_then_segment_id_as_tie_breakers(self) -> None:
        spec = BASELINE.default_baseline_spec(
            {
                "project_id": "project",
                "data_contract_id": "contract",
                "decision": "decision",
                "route": "core_analytics",
                "route_variant": "standard",
            }
        )
        metrics = [
            {
                "as_of_week": "2026-01-05T00:00:00Z",
                "segment_id": "a",
                "users": 4,
                "activated_users": 2,
                "activation_rate": 0.5,
                "support_ticket_count": 4,
                "support_tickets_per_user": 1.0,
                "churned_users": 2,
                "churn_rate": 0.5,
            },
            {
                "as_of_week": "2026-01-05T00:00:00Z",
                "segment_id": "b",
                "users": 4,
                "activated_users": 2,
                "activation_rate": 0.5,
                "support_ticket_count": 6,
                "support_tickets_per_user": 1.5,
                "churned_users": 2,
                "churn_rate": 0.5,
            },
        ]

        decision, decision_check, ranked = BASELINE.build_baseline_decision(spec, metrics)

        self.assertTrue(decision_check["valid"])
        self.assertEqual(decision["selected_segments"], ["b"])
        self.assertEqual([row["rank"] for row in ranked], [1, 2])

    def test_manual_reconciliation_blocks_wrong_expected_denominator_result(self) -> None:
        def mutate(spec: dict) -> None:
            spec["manual_reconciliation"]["expected_metrics"]["churn_rate"] = 0.25

        with TemporaryDirectory() as directory:
            report, result, _paths = self.audit(Path(directory), mutate)

        manual = find_check(report, "manual_reconciliation_matches_tiny_slice")
        self.assertFalse(manual["valid"])
        self.assertEqual(manual["observed"]["errors"][0]["field"], "expected_metrics.churn_rate")
        self.assertEqual(result["manual_rows"][-1]["observed"], 0.5)

    def test_manual_reconciliation_requires_a_declared_existing_slice(self) -> None:
        def mutate(spec: dict) -> None:
            spec["manual_reconciliation"]["slice"]["segment_id"] = "missing"

        with TemporaryDirectory() as directory:
            report, _result, _paths = self.audit(Path(directory), mutate)

        manual = find_check(report, "manual_reconciliation_matches_tiny_slice")
        self.assertFalse(manual["valid"])
        self.assertEqual(manual["observed"]["errors"][0]["field"], "slice")

    def test_acceptance_gate_requires_practical_delta_tolerance_and_capacity(self) -> None:
        def mutate(spec: dict) -> None:
            spec["acceptance_metric"]["practical_improvement"] = 0
            spec["acceptance_metric"]["tolerance"] = 0
            spec["acceptance_metric"]["max_capacity"] = 0

        with TemporaryDirectory() as directory:
            report, _result, _paths = self.audit(Path(directory), mutate)

        acceptance = find_check(report, "acceptance_metric_threshold_and_tolerance_are_predeclared")
        self.assertFalse(acceptance["valid"])
        self.assertEqual(
            {item["field"] for item in acceptance["observed"]["errors"]},
            {"practical_improvement", "tolerance", "max_capacity"},
        )

    def test_complexity_budget_has_bounded_cost_and_retain_baseline_stop_rule(self) -> None:
        def mutate(spec: dict) -> None:
            budget = spec["complexity_budget"]
            budget["max_new_runtime_dependencies"] = 20
            budget["max_implementation_hours"] = 30
            budget["fallback_action"] = "force_complex_candidate"
            budget["stop_rule"] = ""

        with TemporaryDirectory() as directory:
            report, _result, _paths = self.audit(Path(directory), mutate)

        budget_check = find_check(
            report, "complexity_budget_limits_candidate_cost_and_has_a_stop_rule"
        )
        self.assertFalse(budget_check["valid"])
        self.assertEqual(len(budget_check["observed"]["errors"]), 4)

    def test_future_candidate_results_are_forbidden_in_baseline_spec(self) -> None:
        def mutate(spec: dict) -> None:
            spec["acceptance_metric"]["candidate_value"] = 0.9
            spec["acceptance_metric"]["candidate_pass"] = True

        with TemporaryDirectory() as directory:
            report, _result, _paths = self.audit(Path(directory), mutate)

        isolation = find_check(
            report, "baseline_is_isolated_from_implementation_and_future_results"
        )
        self.assertFalse(isolation["valid"])
        self.assertEqual(len(isolation["observed"]["errors"][0]["paths"]), 2)

    def test_later_stage_identifier_in_upstream_state_blocks_isolation(self) -> None:
        with TemporaryDirectory() as directory:
            paths = self.inputs(Path(directory))
            package = paths["upstream_data_package"]
            state_path = package / "capstone_state.json"
            state = read_json(state_path)
            state["implementation_id"] = "peeked-implementation"
            write_json(state_path, state)
            self.refresh_upstream_entry(package, "capstone_state", "capstone_state.json")
            report, _result, _manifest = BASELINE.audit_baseline(
                upstream_data_package=package,
                baseline_spec_path=paths["baseline_spec_path"],
            )

        isolation = find_check(
            report, "baseline_is_isolated_from_implementation_and_future_results"
        )
        self.assertFalse(isolation["valid"])
        self.assertEqual(
            isolation["observed"]["errors"][0]["field"], "capstone_state.implementation_id"
        )

    def test_package_handoff_advances_only_to_baseline_stage(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.inputs(root)
            result = BASELINE.build_baseline_package(
                upstream_data_package=paths["upstream_data_package"],
                baseline_spec_path=paths["baseline_spec_path"],
                output_dir=root / "package",
            )
            state = read_json(result["state_path"])

        self.assertEqual(state["current_stage"], "baseline")
        self.assertEqual(state["stage_status"], "baseline_ready")
        self.assertEqual(state["baseline_id"], "weekly-retention-segment-baseline-v1")
        self.assertIsNone(state["implementation_id"])
        self.assertEqual(state["open_blockers"], [])
        self.assertIn("acceptance_gate.json", state["artifact_inventory"])

    def test_manifest_hashes_outputs_and_declares_no_candidate_peeking(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.inputs(root)
            result = BASELINE.build_baseline_package(
                upstream_data_package=paths["upstream_data_package"],
                baseline_spec_path=paths["baseline_spec_path"],
                output_dir=root / "package",
            )
            manifest = read_json(result["manifest_path"])

            self.assertFalse(manifest["raw_sources_copied"])
            self.assertFalse(manifest["candidate_results_observed"])
            self.assertEqual(manifest["renderer_used"], "capstone_baseline_gate")
            for entry in manifest["outputs"].values():
                path = result["output_dir"] / entry["path"]
                self.assertEqual(entry["sha256"], sha256(path))
                self.assertEqual(entry["bytes"], path.stat().st_size)

    def test_cli_exit_codes_distinguish_blocked_baseline_and_missing_inputs(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.inputs(root)
            spec = read_json(paths["baseline_spec_path"])
            spec["manual_reconciliation"]["expected_inputs"]["users"] = 99
            write_json(paths["baseline_spec_path"], spec)
            blocked = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--upstream-data-package",
                    paths["upstream_data_package"],
                    "--baseline-spec",
                    paths["baseline_spec_path"],
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
        self.assertEqual(json.loads(blocked.stdout)["status"], "baseline_block")
        self.assertEqual(missing.returncode, 2)
        self.assertEqual(json.loads(missing.stdout)["error"]["code"], "missing_inputs")

    def test_audit_does_not_mutate_spec_or_upstream_sample(self) -> None:
        with TemporaryDirectory() as directory:
            paths = self.inputs(Path(directory))
            spec_before = read_json(paths["baseline_spec_path"])
            sample_path = paths["upstream_data_package"] / "public_data_sample.csv"
            sample_before = sample_path.read_bytes()

            BASELINE.audit_baseline(
                upstream_data_package=paths["upstream_data_package"],
                baseline_spec_path=paths["baseline_spec_path"],
            )

            self.assertEqual(read_json(paths["baseline_spec_path"]), spec_before)
            self.assertEqual(sample_path.read_bytes(), sample_before)


if __name__ == "__main__":
    import unittest

    unittest.main()
