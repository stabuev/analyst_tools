from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parents[2]
SPEC = ROOT / "outputs" / "causal_workflow_spec.json"
PACKAGE = ROOT / "outputs" / "causal_study_package.json"
MANIFEST = ROOT / "outputs" / "checksum_manifest.json"
ARTIFACT = ROOT / "outputs" / "causal_study_package_builder.py"
CODE = ROOT / "code" / "main.py"

MODULE_SPEC = importlib.util.spec_from_file_location("causal_study_package_builder", ARTIFACT)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
BUILDER = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules[MODULE_SPEC.name] = BUILDER
MODULE_SPEC.loader.exec_module(BUILDER)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def check(package: dict, check_id: str) -> dict:
    return next(item for item in package["checks"] if item["id"] == check_id)


def estimate(package: dict, estimate_id: str) -> dict:
    return next(item for item in package["estimate"]["rows"] if item["estimate_id"] == estimate_id)


class CausalStudyPackageBuilderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.spec = read_json(SPEC)

    def build(self, spec: dict | None = None) -> tuple[dict, dict]:
        return BUILDER.build_package(self.spec if spec is None else spec)

    def test_valid_package_summary_closes_phase_without_strong_claim(self) -> None:
        package, manifest = self.build()
        self.assertTrue(package["valid"])
        self.assertEqual(package["summary"]["source_files_n"], 15)
        self.assertEqual(
            package["summary"]["workflow_steps"],
            ["model", "identify", "estimate", "refute"],
        )
        self.assertEqual(package["summary"]["estimate_rows_n"], 7)
        self.assertEqual(package["summary"]["final_claim_status"], "blocked_single_strong_claim")
        self.assertFalse(package["summary"]["allowed_effect_claim"])
        self.assertEqual(
            package["summary"]["dowhy_runtime_status"],
            "not_installed_trace_validates_workflow_contract",
        )
        self.assertFalse(package["summary"]["econml_used"])
        self.assertEqual(package["summary"]["blocking_checks"], [])
        self.assertEqual(len(manifest["files"]), 15)

    def test_code_example_prints_transferable_summary(self) -> None:
        result = subprocess.run(
            [sys.executable, CODE],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(result.stdout)
        self.assertTrue(payload["package_valid"])
        self.assertEqual(payload["source_files_n"], 15)
        self.assertEqual(payload["workflow_steps"], ["model", "identify", "estimate", "refute"])
        self.assertEqual(payload["final_claim_status"], "blocked_single_strong_claim")
        self.assertFalse(payload["allowed_effect_claim"])
        self.assertFalse(payload["econml_used"])

    def test_package_contains_required_sections_and_checksum_manifest(self) -> None:
        package, manifest = self.build()
        for section in self.spec["required_package_sections"]:
            self.assertIn(section, package)
        self.assertTrue(check(package, "package_contains_required_sections")["valid"])
        self.assertTrue(check(package, "checksum_manifest_covers_all_sources")["valid"])
        self.assertEqual(len(package["checksum_manifest"]), len(self.spec["source_files"]))
        self.assertEqual(package["checksum_manifest"], manifest["files"])
        self.assertTrue(all(len(entry["sha256"]) == 64 for entry in manifest["files"]))

    def test_question_model_and_identification_are_preserved(self) -> None:
        package, _manifest = self.build()
        self.assertEqual(package["question"]["estimand_type"], "ATE")
        self.assertEqual(package["question"]["treatment"], "assisted_within_24h")
        self.assertEqual(package["question"]["comparator"], "no_assistance_within_24h")
        self.assertEqual(package["question"]["outcome"], "activation_14d")
        self.assertEqual(package["model"]["nodes"], 19)
        self.assertEqual(package["model"]["edges"], 44)
        self.assertEqual(
            package["identify"]["backdoor_identification_status"],
            "not_identified_due_to_unmeasured_confounding",
        )
        self.assertEqual(package["identify"]["unmeasured_confounders"], 1)
        self.assertIn("opened_support_chat_after_offer", package["identify"]["forbidden_controls"])

    def test_estimates_are_compared_but_never_pooled(self) -> None:
        package, _manifest = self.build()
        self.assertAlmostEqual(
            estimate(package, "g_formula_manual_ate")["estimate"],
            -0.39978100191623295,
        )
        self.assertAlmostEqual(estimate(package, "matching_att")["estimate"], -0.25)
        self.assertAlmostEqual(estimate(package, "aipw_ate")["estimate"], -0.3868752937879506)
        self.assertAlmostEqual(estimate(package, "did_estimate")["estimate"], 0.08)
        self.assertAlmostEqual(
            estimate(package, "rdd_wald_local_effect_diagnostic")["estimate"],
            -1.0,
        )
        self.assertAlmostEqual(estimate(package, "iv_wald_late")["estimate"], 0.5)
        self.assertFalse(package["estimate"]["pooling_allowed"])
        self.assertTrue(check(package, "different_estimands_are_not_pooled")["valid"])

    def test_refutation_and_evidence_statement_match_sensitivity_policy(self) -> None:
        package, _manifest = self.build()
        self.assertEqual(
            package["refute"]["falsification_failures"],
            ["placebo_outcome_pre_activation", "negative_control_outcome_app_crashes"],
        )
        self.assertAlmostEqual(package["refute"]["first_nulling_bias"], 0.4)
        self.assertFalse(package["refute"]["allowed_effect_claim"])
        self.assertFalse(package["evidence_statement"]["allowed_effect_claim"])
        self.assertEqual(
            package["evidence_statement"]["final_claim_status"],
            "blocked_single_strong_claim",
        )
        self.assertTrue(check(package, "final_claim_matches_sensitivity_policy")["valid"])

    def test_dowhy_workflow_trace_preserves_model_identify_estimate_refute_order(self) -> None:
        package, _manifest = self.build()
        trace = package["automation_audit"]["dowhy_workflow_trace"]
        self.assertEqual(
            [item["step"] for item in trace],
            ["model", "identify", "estimate", "refute"],
        )
        self.assertIn("CausalModel", trace[0]["dowhy_surface"])
        self.assertIn("identify_effect", trace[1]["dowhy_surface"])
        self.assertIn("estimate_effect", trace[2]["dowhy_surface"])
        self.assertIn("refute_estimate", trace[3]["dowhy_surface"])
        self.assertTrue(
            check(package, "dowhy_workflow_trace_has_model_identify_estimate_refute")[
                "valid"
            ]
        )

    def test_automation_audit_does_not_override_identification_or_use_econml(self) -> None:
        package, _manifest = self.build()
        self.assertTrue(check(package, "automation_does_not_override_identification")["valid"])
        self.assertTrue(
            check(package, "econml_is_not_used_without_heterogeneity_question")[
                "valid"
            ]
        )
        scope = package["automation_audit"]["econml_scope_decision"]
        self.assertFalse(scope["used"])
        self.assertIn("explicit heterogeneity estimand", scope["required_before_future_use"])
        self.assertTrue(check(package, "dowhy_runtime_is_optional_and_documented")["valid"])

    def test_committed_package_and_manifest_match_builder(self) -> None:
        committed_package = read_json(PACKAGE)
        committed_manifest = read_json(MANIFEST)
        fresh_package, fresh_manifest = self.build()
        self.assertEqual(committed_package["summary"], fresh_package["summary"])
        self.assertEqual(
            committed_package["evidence_statement"],
            fresh_package["evidence_statement"],
        )
        self.assertEqual(committed_manifest, fresh_manifest)

    def test_missing_upstream_source_blocks_package(self) -> None:
        spec = copy.deepcopy(self.spec)
        spec["source_files"][0]["path"] = "phases/13-causal-analysis/missing/question.json"
        package, manifest = self.build(spec)
        self.assertFalse(package["valid"])
        self.assertIn("all_required_sources_are_present", package["summary"]["blocking_checks"])
        self.assertFalse(check(package, "all_required_sources_are_present")["valid"])
        self.assertEqual(len(manifest["files"]), 14)

    def test_invalid_json_source_blocks_package(self) -> None:
        with TemporaryDirectory() as directory:
            invalid_path = Path(directory) / "not-json.json"
            invalid_path.write_text("{not json", encoding="utf-8")
            spec = copy.deepcopy(self.spec)
            spec["source_files"][0]["path"] = str(invalid_path)
            package, _manifest = self.build(spec)
            self.assertFalse(package["valid"])
            self.assertIn(
                "all_required_sources_are_valid_json",
                package["summary"]["blocking_checks"],
            )
            self.assertFalse(check(package, "all_required_sources_are_valid_json")["valid"])

    def test_wrong_workflow_order_is_rejected(self) -> None:
        spec = copy.deepcopy(self.spec)
        spec["workflow_contract"]["steps"] = ["model", "estimate", "identify", "refute"]
        package, _manifest = self.build(spec)
        workflow = check(package, "dowhy_workflow_trace_has_model_identify_estimate_refute")
        self.assertFalse(package["valid"])
        self.assertFalse(workflow["valid"])
        self.assertEqual(workflow["sample"], ["model", "identify", "estimate", "refute"])

    def test_final_claim_cannot_be_stronger_than_sensitivity_policy(self) -> None:
        with TemporaryDirectory() as directory:
            sensitivity = read_json(
                REPO_ROOT
                / "phases/13-causal-analysis/10-sensitivity/outputs/sensitivity_report.json"
            )
            sensitivity["summary"]["allowed_effect_claim"] = True
            sensitivity["claim_policy"]["allowed_effect_claim"] = True
            sensitivity_path = Path(directory) / "sensitivity_report.json"
            write_json(sensitivity_path, sensitivity)
            spec = copy.deepcopy(self.spec)
            spec["source_files"][-1]["path"] = str(sensitivity_path)
            package, _manifest = self.build(spec)
            claim = check(package, "final_claim_matches_sensitivity_policy")
            self.assertFalse(package["valid"])
            self.assertFalse(claim["valid"])
            self.assertEqual(claim["sample"], {"evidence": False, "refute": True})

    def test_cli_fail_on_invalid_exits_nonzero_for_missing_source(self) -> None:
        with TemporaryDirectory() as directory:
            tmp = Path(directory)
            spec = copy.deepcopy(self.spec)
            spec["source_files"][0]["path"] = "phases/13-causal-analysis/missing/question.json"
            spec_path = tmp / "invalid_workflow_spec.json"
            output_path = tmp / "package.json"
            manifest_path = tmp / "manifest.json"
            write_json(spec_path, spec)
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--spec",
                    spec_path,
                    "--output",
                    output_path,
                    "--manifest",
                    manifest_path,
                    "--fail-on-invalid",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 1)
            payload = read_json(output_path)
            self.assertFalse(payload["valid"])
            self.assertIn("all_required_sources_are_present", payload["summary"]["blocking_checks"])


if __name__ == "__main__":
    unittest.main()
