from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
PHASE_ROOT = ROOT.parent
ARTIFACT = ROOT / "outputs" / "experiment_decision_packager.py"
POLICY = ROOT / "outputs" / "decision_policy.json"
PACKAGE = ROOT / "outputs" / "experiment-decision-package"
MANIFEST = PACKAGE / "manifest.json"
SUMMARY = PACKAGE / "decision_summary.json"
EVIDENCE_INDEX = PACKAGE / "evidence_index.json"
CHECKSUMS = PACKAGE / "checksums.json"
CODE = ROOT / "code" / "main.py"

MODULE_SPEC = importlib.util.spec_from_file_location("experiment_decision_packager", ARTIFACT)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
PACKAGER = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(PACKAGER)


def package_files(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


class ExperimentDecisionPackageTest(unittest.TestCase):
    def test_committed_package_matches_rebuilt_package(self) -> None:
        with TemporaryDirectory() as directory:
            output_dir = Path(directory) / "experiment-decision-package"
            package = PACKAGER.build_package(PHASE_ROOT, POLICY, output_dir)
            self.assertEqual(package["manifest"], json.loads((output_dir / "manifest.json").read_text(encoding="utf-8")))
            self.assertEqual(package_files(output_dir), package_files(PACKAGE))

    def test_decision_summary_is_hold_not_launch_or_rollback(self) -> None:
        summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
        self.assertEqual(summary["decision"], "hold")
        self.assertFalse(summary["launch_allowed"])
        self.assertFalse(summary["rollback_required"])
        self.assertIn("missed_primary_direction", summary["decision_reasons"])
        self.assertIn("multiple_testing_does_not_allow_launch", summary["decision_reasons"])
        self.assertIn("peeking_audit_not_ready_for_decision", summary["decision_reasons"])
        self.assertIn("segment_cells_below_minimum_size", summary["decision_reasons"])
        self.assertFalse(summary["launch_requirements"]["effect_analysis_ready"])
        self.assertFalse(summary["launch_requirements"]["multiple_testing_allows_launch"])

    def test_primary_effects_propagate_from_raw_bootstrap_and_cuped(self) -> None:
        primary = json.loads(SUMMARY.read_text(encoding="utf-8"))["primary_metric"]
        self.assertEqual(primary["metric_id"], "activation_rate_7d")
        self.assertEqual(primary["raw_absolute_lift"], -0.666667)
        self.assertEqual(primary["raw_p_value"], 0.931981)
        self.assertEqual(primary["bootstrap_ci_low"], -1.0)
        self.assertEqual(primary["bootstrap_ci_high"], 0.0)
        self.assertEqual(primary["cuped_adjusted_absolute_lift"], -0.416667)
        self.assertEqual(primary["cuped_p_value"], 0.804109)

    def test_required_evidence_items_are_present(self) -> None:
        index = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))["evidence"]
        ids = {entry["id"] for entry in index}
        self.assertEqual(len(index), 20)
        self.assertTrue(
            {
                "protocol",
                "assignment_audit",
                "randomization_health",
                "power_plan",
                "effect_results",
                "bootstrap_intervals",
                "variance_reduction",
                "multiple_testing",
                "peeking",
                "heterogeneity",
            }.issubset(ids)
        )
        paths = {entry["package_path"] for entry in index}
        self.assertIn("evidence/02_assignment_audit.json", paths)
        self.assertIn("evidence/10_segment_effects.csv", paths)

    def test_assignment_audit_validates_assignment_exposure_integrity(self) -> None:
        audit = json.loads((PACKAGE / "evidence" / "02_assignment_audit.json").read_text(encoding="utf-8"))
        self.assertTrue(audit["valid"])
        self.assertEqual(audit["summary"]["assigned_units"], 5)
        self.assertEqual(audit["summary"]["exposed_units"], 5)
        self.assertEqual(audit["summary"]["variant_counts"], {"control": 3, "treatment": 2})
        self.assertEqual(audit["summary"]["variant_mismatches"], [])

    def test_assignment_audit_detects_exposure_variant_mismatch(self) -> None:
        protocol = PACKAGER.read_json(PHASE_ROOT / "01-hypothesis-and-metric" / "outputs" / "experiment_protocol.json")
        assignments = PACKAGER.read_csv(PHASE_ROOT / "data" / "tiny" / "assignments.csv")
        exposures = PACKAGER.read_csv(PHASE_ROOT / "data" / "tiny" / "exposures.csv")
        exposures[0]["variant_id"] = "treatment"
        audit = PACKAGER.assignment_audit(protocol, assignments, exposures)
        self.assertFalse(audit["valid"])
        self.assertEqual(audit["summary"]["variant_mismatches"][0]["assignment_unit_id"], "U001")
        failed = [check["id"] for check in audit["checks"] if not check["valid"]]
        self.assertEqual(failed, ["exposure_variant_matches_assignment"])

    def test_checksum_manifest_matches_package_files(self) -> None:
        checksums = json.loads(CHECKSUMS.read_text(encoding="utf-8"))
        self.assertEqual(checksums["algorithm"], "sha256")
        self.assertEqual(len(checksums["files"]), 23)
        for entry in checksums["files"]:
            self.assertEqual(entry["sha256"], PACKAGER.sha256_file(PACKAGE / entry["path"]))
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(manifest["checksums_sha256"], PACKAGER.sha256_file(CHECKSUMS))
        self.assertEqual(manifest["package_files"], 23)

    def test_decision_policy_must_allow_selected_decision(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            policy_path = root / "policy.json"
            policy = json.loads(POLICY.read_text(encoding="utf-8"))
            policy["allowed_decisions"] = ["launch"]
            policy_path.write_text(json.dumps(policy, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                PACKAGER.build_package(PHASE_ROOT, policy_path, root / "package")

    def test_code_example_prints_decision_summary(self) -> None:
        result = subprocess.run(
            [sys.executable, CODE],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(result.stdout)
        self.assertTrue(payload["valid"])
        self.assertEqual(payload["decision"], "hold")
        self.assertFalse(payload["launch_allowed"])
        self.assertFalse(payload["rollback_required"])
        self.assertEqual(payload["primary_metric"], "activation_rate_7d")
        self.assertEqual(payload["raw_absolute_lift"], -0.666667)
        self.assertEqual(payload["cuped_adjusted_absolute_lift"], -0.416667)
        self.assertEqual(payload["evidence_items"], 20)
        self.assertEqual(payload["checksum_algorithm"], "sha256")

    def test_cli_writes_complete_package(self) -> None:
        with TemporaryDirectory() as directory:
            output_dir = Path(directory) / "package"
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--phase-root",
                    PHASE_ROOT,
                    "--decision-policy",
                    POLICY,
                    "--output-dir",
                    output_dir,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads(result.stdout)
            self.assertEqual(manifest["decision"], "hold")
            self.assertTrue((output_dir / "decision_report.md").is_file())
            self.assertTrue((output_dir / "checksums.json").is_file())
            self.assertTrue((output_dir / "evidence" / "10_heterogeneity_report.json").is_file())
            self.assertEqual(json.loads((output_dir / "manifest.json").read_text(encoding="utf-8")), manifest)


if __name__ == "__main__":
    unittest.main()
