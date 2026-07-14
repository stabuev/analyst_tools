from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase


LESSON_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[4]
ARTIFACT_PATH = LESSON_ROOT / "outputs" / "capstone_portfolio_builder.py"
SPEC = importlib.util.spec_from_file_location("capstone_portfolio_builder", ARTIFACT_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT_PATH}")
BUILDER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BUILDER
SPEC.loader.exec_module(BUILDER)


class PortfolioDefenseTest(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._template_tmp = TemporaryDirectory()
        cls.template = Path(cls._template_tmp.name) / "inputs"
        BUILDER.write_sample_inputs(cls.template)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._template_tmp.cleanup()

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.inputs_root = self.root / "inputs"
        shutil.copytree(self.template, self.inputs_root)
        self.packages = {
            stage: self.inputs_root / f"{stage}-package"
            for stage in BUILDER.STAGE_DEFINITIONS
        }
        self.brief_path = self.inputs_root / "brief-source" / "capstone_brief.json"
        self.runner = BUILDER.IMPLEMENTATION_RUNNER
        self.spec_path = self.inputs_root / "defense_spec.json"
        self.submission_path = self.inputs_root / "defense_submission.json"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def audit(self):
        return BUILDER.audit_defense(
            packages=self.packages,
            capstone_brief_path=self.brief_path,
            implementation_runner=self.runner,
            defense_spec_path=self.spec_path,
            defense_submission_path=self.submission_path,
        )

    def build(self, name: str = "build"):
        return BUILDER.build_portfolio_package(
            packages=self.packages,
            capstone_brief_path=self.brief_path,
            implementation_runner=self.runner,
            defense_spec_path=self.spec_path,
            defense_submission_path=self.submission_path,
            output_dir=self.root / name,
        )

    def check(self, report: dict, check_id: str) -> dict:
        return next(item for item in report["checks"] if item["id"] == check_id)

    def read(self, path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    def write(self, path: Path, value: dict) -> None:
        BUILDER.write_json(path, value)

    def refresh_stage_manifest(self, stage: str, relative: str) -> None:
        definition = BUILDER.STAGE_DEFINITIONS[stage]
        manifest_path = self.packages[stage] / definition["manifest"]
        manifest = self.read(manifest_path)
        target = self.packages[stage] / relative
        entry = next(
            value
            for value in manifest["outputs"].values()
            if value["path"] == relative
        )
        entry["sha256"] = BUILDER.sha256_file(target)
        entry["bytes"] = target.stat().st_size
        self.write(manifest_path, manifest)

    def sync_review_bindings(self) -> None:
        digest = BUILDER.sha256_file(self.packages["review"] / "review_manifest.json")
        spec = self.read(self.spec_path)
        submission = self.read(self.submission_path)
        spec["reviewed_manifest_sha256"] = digest
        submission["reviewed_manifest_sha256"] = digest
        self.write(self.spec_path, spec)
        self.write(self.submission_path, submission)

    def refresh_final_manifest(self, package: Path, relative: str) -> None:
        manifest_path = package / "manifest.json"
        manifest = self.read(manifest_path)
        target = package / relative
        entry = next(
            value
            for value in manifest["outputs"].values()
            if value["path"] == relative
        )
        entry["sha256"] = BUILDER.sha256_file(target)
        entry["bytes"] = target.stat().st_size
        self.write(manifest_path, manifest)

    def test_reference_defense_passes_without_distinction(self) -> None:
        report, result = self.audit()

        self.assertTrue(report["valid"])
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["summary"]["rubric_score"], 21)
        self.assertEqual(len(report["checks"]), 18)
        self.assertTrue(result["live_report"]["valid"])
        self.assertEqual(len(report["summary"]["challenge_classes"]), 5)

    def test_final_package_contains_contract_tree_and_passes_verify_mode(self) -> None:
        result = self.build()
        package = result["package_dir"]

        self.assertTrue(result["valid"])
        self.assertFalse(BUILDER.validate_portfolio_package(package))
        self.assertFalse(
            [name for name in BUILDER.REQUIRED_PACKAGE_FILES if not (package / name).is_file()]
        )
        state = self.read(package / "capstone-state.json")
        self.assertEqual(state["current_stage"], "defense")
        self.assertEqual(state["stage_status"], "passed")
        self.assertEqual(state["defense_id"], "weekly-retention-core-defense-v1")

    def test_two_builds_have_identical_tracked_output_hashes(self) -> None:
        first = self.build("first")["manifest"]["outputs"]
        second = self.build("second")["manifest"]["outputs"]

        first_hashes = {entry["path"]: entry["sha256"] for entry in first.values()}
        second_hashes = {entry["path"]: entry["sha256"] for entry in second.values()}
        self.assertEqual(first_hashes, second_hashes)

    def test_audit_does_not_mutate_any_source_stage(self) -> None:
        before = {
            stage: BUILDER.directory_checksums(path)
            for stage, path in self.packages.items()
        }
        report, _result = self.audit()

        after = {
            stage: BUILDER.directory_checksums(path)
            for stage, path in self.packages.items()
        }
        self.assertEqual(before, after)
        self.assertTrue(
            self.check(report, "defense_does_not_mutate_reviewed_stage_packages")["valid"]
        )

    def test_stage_output_tamper_blocks_defense(self) -> None:
        target = self.packages["verification"] / "verification_report.json"
        target.write_text(target.read_text(encoding="utf-8") + "\n", encoding="utf-8")

        report, _result = self.audit()

        self.assertEqual(report["status"], "revision_required")
        self.assertFalse(
            self.check(report, "verification_package_is_ready_and_immutable")["valid"]
        )

    def test_rehashed_upstream_state_still_breaks_chain_binding(self) -> None:
        state_path = self.packages["brief"] / "capstone_state.json"
        state = self.read(state_path)
        state["warnings"].append("post_review_change")
        self.write(state_path, state)
        self.refresh_stage_manifest("brief", "capstone_state.json")

        report, _result = self.audit()

        self.assertTrue(self.check(report, "brief_package_is_ready_and_immutable")["valid"])
        self.assertFalse(
            self.check(report, "stage_chain_is_continuous_and_checksum_bound")["valid"]
        )

    def test_stale_reviewed_manifest_hash_blocks_defense(self) -> None:
        spec = self.read(self.spec_path)
        submission = self.read(self.submission_path)
        spec["reviewed_manifest_sha256"] = "0" * 64
        submission["reviewed_manifest_sha256"] = "0" * 64
        self.write(self.spec_path, spec)
        self.write(self.submission_path, submission)

        report, _result = self.audit()

        self.assertFalse(
            self.check(report, "defense_spec_is_predeclared_and_bound_to_review")["valid"]
        )
        self.assertFalse(
            self.check(report, "peer_review_is_closed_for_exact_defense_input")["valid"]
        )

    def test_rehashed_open_review_finding_blocks_defense(self) -> None:
        path = self.packages["review"] / "re_review_report.json"
        review = self.read(path)
        review["valid"] = False
        review["summary"]["open_findings"] = ["RF-001"]
        self.write(path, review)
        self.refresh_stage_manifest("review", "re_review_report.json")
        self.sync_review_bindings()

        report, _result = self.audit()

        self.assertTrue(self.check(report, "review_package_is_ready_and_immutable")["valid"])
        self.assertFalse(
            self.check(report, "peer_review_is_closed_for_exact_defense_input")["valid"]
        )

    def test_missing_brief_section_blocks_defense(self) -> None:
        submission = self.read(self.submission_path)
        submission["defense_brief"]["sections"]["limitations"] = ""
        self.write(self.submission_path, submission)

        report, _result = self.audit()

        self.assertFalse(
            self.check(report, "defense_brief_fits_time_and_covers_decision_story")["valid"]
        )

    def test_defense_longer_than_ten_minutes_blocks_defense(self) -> None:
        submission = self.read(self.submission_path)
        submission["defense_brief"]["duration_minutes"] = 11
        self.write(self.submission_path, submission)

        report, _result = self.audit()

        self.assertEqual(report["status"], "revision_required")
        self.assertFalse(
            self.check(report, "defense_brief_fits_time_and_covers_decision_story")["valid"]
        )

    def test_author_cannot_be_the_defense_evaluator(self) -> None:
        submission = self.read(self.submission_path)
        submission["evaluator"]["evaluator_id"] = submission["presenter"]["author_id"]
        submission["evaluator"]["is_project_author"] = True
        self.write(self.submission_path, submission)

        report, _result = self.audit()

        self.assertFalse(
            self.check(report, "defense_evaluator_is_independent_and_disclosed")["valid"]
        )

    def test_independent_agent_must_disclose_context(self) -> None:
        submission = self.read(self.submission_path)
        submission["evaluator"]["clean_context"] = False
        submission["evaluator"]["assistance_disclosure"] = ""
        self.write(self.submission_path, submission)

        report, _result = self.audit()

        self.assertFalse(
            self.check(report, "defense_evaluator_is_independent_and_disclosed")["valid"]
        )

    def test_descriptive_claim_cannot_smuggle_causality(self) -> None:
        submission = self.read(self.submission_path)
        submission["defense_claims"][0]["statement"] = (
            "The weighted route causes churn reduction."
        )
        self.write(self.submission_path, submission)

        report, _result = self.audit()

        self.assertFalse(
            self.check(
                report, "defense_claims_have_exact_evidence_and_bounded_language"
            )["valid"]
        )

    def test_claim_requires_existing_exact_evidence_path(self) -> None:
        submission = self.read(self.submission_path)
        submission["defense_claims"][0]["evidence_path"] = (
            "verification:missing-report.json#result"
        )
        self.write(self.submission_path, submission)

        report, _result = self.audit()

        self.assertFalse(
            self.check(
                report, "defense_claims_have_exact_evidence_and_bounded_language"
            )["valid"]
        )

    def test_three_distinct_challenge_classes_are_required(self) -> None:
        submission = self.read(self.submission_path)
        submission["challenge_questions"] = submission["challenge_questions"][:2]
        self.write(self.submission_path, submission)

        report, _result = self.audit()

        self.assertFalse(
            self.check(
                report, "challenge_answers_cover_failure_classes_and_bound_uncertainty"
            )["valid"]
        )

    def test_unknown_answer_requires_testable_next_step(self) -> None:
        submission = self.read(self.submission_path)
        question = submission["challenge_questions"][3]
        self.assertEqual(question["answer_status"], "unknown_with_testable_next_step")
        question["next_check"] = ""
        self.write(self.submission_path, submission)

        report, _result = self.audit()

        self.assertFalse(
            self.check(
                report, "challenge_answers_cover_failure_classes_and_bound_uncertainty"
            )["valid"]
        )

    def test_changed_runner_hash_blocks_predeclared_live_demo(self) -> None:
        changed_runner = self.root / "changed_runner.py"
        shutil.copy2(self.runner, changed_runner)
        changed_runner.write_text(
            changed_runner.read_text(encoding="utf-8") + "\n# changed after review\n",
            encoding="utf-8",
        )
        self.runner = changed_runner

        report, _result = self.audit()

        self.assertFalse(
            self.check(report, "defense_spec_is_predeclared_and_bound_to_review")["valid"]
        )

    def test_public_release_declaration_cannot_include_raw_material(self) -> None:
        submission = self.read(self.submission_path)
        submission["public_release"]["raw_sources_included"] = True
        self.write(self.submission_path, submission)

        report, _result = self.audit()

        self.assertFalse(
            self.check(
                report, "public_package_excludes_raw_sensitive_and_secret_material"
            )["valid"]
        )

    def test_public_sample_with_pii_column_blocks_defense_even_when_rehashed(self) -> None:
        sample = self.packages["data"] / "public_data_sample.csv"
        rows, fields = BUILDER.read_csv(sample)
        for row in rows:
            row["email"] = "fake@example.invalid"
        BUILDER.write_csv(sample, rows, [*fields, "email"])
        self.refresh_stage_manifest("data", "public_data_sample.csv")

        report, _result = self.audit()

        public = self.check(
            report, "public_package_excludes_raw_sensitive_and_secret_material"
        )
        self.assertFalse(public["valid"])
        self.assertIn("email", json.dumps(public["observed"]))

    def test_blocker_overrides_distinction_level_scores(self) -> None:
        rubric = {
            "dimensions": [
                {"dimension_id": dimension_id, "score": 4}
                for dimension_id, _name in BUILDER.RUBRIC_DIMENSIONS
            ],
            "summary": {"total_score": 24},
        }

        self.assertEqual(
            BUILDER.rubric_outcome(rubric, ["required_checksum_mismatch"]),
            "revision_required",
        )

    def test_rubric_thresholds_distinguish_pass_and_distinction(self) -> None:
        def rubric(scores: list[int]) -> dict:
            return {
                "dimensions": [
                    {"dimension_id": item[0], "score": score}
                    for item, score in zip(BUILDER.RUBRIC_DIMENSIONS, scores, strict=True)
                ],
                "summary": {"total_score": sum(scores)},
            }

        self.assertEqual(BUILDER.rubric_outcome(rubric([3, 3, 3, 4, 4, 4]), []), "passed")
        self.assertEqual(
            BUILDER.rubric_outcome(rubric([3, 3, 4, 4, 4, 4]), []),
            "passed_with_distinction",
        )
        self.assertEqual(
            BUILDER.rubric_outcome(rubric([2, 3, 3, 2, 2, 2]), []),
            "revision_required",
        )

    def test_provenance_catches_tamper_after_root_manifest_is_refreshed(self) -> None:
        package = self.build()["package_dir"]
        relative = "review/re-review-report.json"
        target = package / relative
        target.write_text(target.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        self.refresh_final_manifest(package, relative)

        errors = BUILDER.validate_portfolio_package(package)

        self.assertIn("stage_provenance", {item["field"] for item in errors})

    def test_final_verify_detects_missing_and_untracked_files(self) -> None:
        package = self.build()["package_dir"]
        (package / "handoff" / "limitations.md").unlink()
        (package / "unexpected.txt").write_text("unexpected\n", encoding="utf-8")

        errors = BUILDER.validate_portfolio_package(package)
        fields = {item["field"] for item in errors}

        self.assertIn("outputs.coverage", fields)
        self.assertIn("required_package_files", fields)

    def test_final_verify_scans_fake_secret_marker_after_rehash(self) -> None:
        package = self.build()["package_dir"]
        relative = "handoff/runbook.md"
        target = package / relative
        target.write_text(
            target.read_text(encoding="utf-8") + "\nTOKEN=fake-fixture-only\n",
            encoding="utf-8",
        )
        self.refresh_final_manifest(package, relative)

        errors = BUILDER.validate_portfolio_package(package)

        self.assertIn("public_scan", {item["field"] for item in errors})

    def test_cli_build_and_verify_modes(self) -> None:
        sample = self.root / "cli-inputs"
        output = self.root / "cli-output"
        build = subprocess.run(
            [
                sys.executable,
                str(ARTIFACT_PATH),
                "--write-example",
                str(sample),
                "--output-dir",
                str(output),
                "--fail-on-invalid",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(build.returncode, 0, build.stderr)
        payload = json.loads(build.stdout)
        self.assertEqual(payload["status"], "passed")

        verify = subprocess.run(
            [
                sys.executable,
                str(ARTIFACT_PATH),
                "--verify-package",
                str(output / BUILDER.PACKAGE_NAME),
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(verify.returncode, 0, verify.stderr)
        self.assertTrue(json.loads(verify.stdout)["valid"])

    def test_cli_help_names_both_operating_modes(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(ARTIFACT_PATH), "--help"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0)
        self.assertIn("--write-example", completed.stdout)
        self.assertIn("--verify-package", completed.stdout)


if __name__ == "__main__":
    import unittest

    unittest.main()
