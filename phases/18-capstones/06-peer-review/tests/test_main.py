from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

LESSON_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = LESSON_ROOT / "outputs" / "capstone_peer_review_kit.py"
CODE = LESSON_ROOT / "code" / "main.py"
sys.path.insert(0, str(LESSON_ROOT / "outputs"))

import capstone_peer_review_kit as REVIEW  # noqa: E402


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: dict) -> Path:
    return REVIEW.write_json(path, value)


def find_check(report: dict, check_id: str) -> dict:
    return next(item for item in report["checks"] if item["id"] == check_id)


class CapstonePeerReviewKitTest(TestCase):
    def inputs(self, root: Path) -> dict[str, Path]:
        return REVIEW.write_sample_inputs(root / "inputs")

    def audit(
        self, root: Path, mutate_submission=None, mutate_spec=None
    ) -> tuple[dict, dict, dict]:
        paths = self.inputs(root)
        if mutate_submission is not None:
            submission = read_json(paths["review_submission_path"])
            mutate_submission(submission)
            write_json(paths["review_submission_path"], submission)
        if mutate_spec is not None:
            spec = read_json(paths["review_spec_path"])
            mutate_spec(spec)
            write_json(paths["review_spec_path"], spec)
        report, result = REVIEW.audit_peer_review(
            upstream_verification_package=paths["upstream_verification_package"],
            review_spec_path=paths["review_spec_path"],
            review_submission_path=paths["review_submission_path"],
        )
        return report, result, paths

    def refresh_verification_output(self, package: Path, output_id: str) -> None:
        manifest_path = package / "verification_manifest.json"
        manifest = read_json(manifest_path)
        relative = manifest["outputs"][output_id]["path"]
        target = package / relative
        manifest["outputs"][output_id]["sha256"] = REVIEW.sha256_file(target)
        manifest["outputs"][output_id]["bytes"] = target.stat().st_size
        write_json(manifest_path, manifest)

    def refresh_response_hash(self, submission: dict, finding_id: str, claim_id: str) -> None:
        claim = next(item for item in submission["reviewed_claims"] if item["claim_id"] == claim_id)
        response = next(
            item for item in submission["author_responses"] if item["finding_id"] == finding_id
        )
        response["reviewed_claim_sha256"] = REVIEW.canonical_sha256(claim)

    def test_reference_review_reaches_review_ready(self) -> None:
        with TemporaryDirectory() as directory:
            report, result, _paths = self.audit(Path(directory))

        self.assertTrue(report["valid"])
        self.assertEqual(report["status"], "review_ready")
        self.assertEqual(report["summary"]["next_stage"], "defense")
        self.assertEqual(report["summary"]["check_count"], 12)
        self.assertEqual(report["summary"]["finding_count"], 3)
        self.assertEqual(report["summary"]["closed_findings"], 3)
        self.assertEqual(report["summary"]["severity_counts"]["major"], 1)
        self.assertEqual(report["summary"]["severity_counts"]["minor"], 1)
        self.assertEqual(report["summary"]["severity_counts"]["question"], 1)
        self.assertEqual(report["summary"]["provisional_rubric_score"], 19)
        self.assertTrue(result["re_review"]["valid"])

    def test_code_example_writes_complete_review_package(self) -> None:
        completed = subprocess.run(
            [sys.executable, CODE],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        payload = json.loads(completed.stdout)

        self.assertTrue(payload["valid"])
        self.assertEqual(payload["status"], "review_ready")
        self.assertEqual(payload["findings"], 3)
        self.assertEqual(payload["closed_findings"], 3)
        self.assertEqual(payload["next_stage"], "defense")
        for name in (
            "review_spec.json",
            "review_report.json",
            "review_rubric.json",
            "finding_ledger.csv",
            "author_responses.csv",
            "reviewed_claims.json",
            "changed_file_inventory.csv",
            "rerun_results.json",
            "re_review_report.json",
            "capstone_state.json",
            "review_manifest.json",
        ):
            self.assertTrue((LESSON_ROOT / "outputs" / name).is_file(), name)

    def test_cli_help_and_write_example_expose_review_inputs(self) -> None:
        help_result = subprocess.run(
            [sys.executable, ARTIFACT, "--help"],
            check=True,
            capture_output=True,
            text=True,
        )
        for option in (
            "--upstream-verification-package",
            "--review-spec",
            "--review-submission",
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

            self.assertEqual(payload["status"], "review_ready")
            self.assertTrue((root / "input" / "review_spec.json").is_file())
            self.assertTrue((root / "input" / "review_submission.json").is_file())
            self.assertTrue((root / "package" / "review_manifest.json").is_file())

    def test_reviewer_cannot_be_project_author(self) -> None:
        def mutate(submission: dict) -> None:
            submission["reviewer"]["reviewer_id"] = submission["self_review"]["author_id"]
            for finding in submission["findings"]:
                finding["raised_by_reviewer_id"] = submission["reviewer"]["reviewer_id"]

        with TemporaryDirectory() as directory:
            report, _result, _paths = self.audit(Path(directory), mutate_submission=mutate)

        independence = find_check(report, "reviewer_independence_is_disclosed")
        self.assertFalse(independence["valid"])
        self.assertEqual(report["status"], "review_block")

    def test_independent_agent_requires_clean_context_and_disclosure(self) -> None:
        def mutate(submission: dict) -> None:
            submission["reviewer"]["clean_review_context"] = False
            submission["reviewer"]["assistance_disclosure"] = ""

        with TemporaryDirectory() as directory:
            report, _result, _paths = self.audit(Path(directory), mutate_submission=mutate)

        independence = find_check(report, "reviewer_independence_is_disclosed")
        self.assertFalse(independence["valid"])
        self.assertEqual(len(independence["observed"]["errors"]), 2)

    def test_reviewer_must_name_exact_reviewed_manifest(self) -> None:
        with TemporaryDirectory() as directory:
            report, _result, _paths = self.audit(
                Path(directory),
                mutate_submission=lambda value: value["reviewer"].update(
                    {"reviewed_manifest_sha256": "0" * 64}
                ),
            )

        independence = find_check(report, "reviewer_independence_is_disclosed")
        self.assertFalse(independence["valid"])
        self.assertEqual(
            independence["observed"]["errors"][0]["field"],
            "reviewer.reviewed_manifest_sha256",
        )

    def test_self_review_must_finish_before_independent_review(self) -> None:
        with TemporaryDirectory() as directory:
            report, _result, _paths = self.audit(
                Path(directory),
                mutate_submission=lambda value: value["self_review"].update(
                    {"completed_at": "2026-01-13T10:30:00Z"}
                ),
            )

        self_review = find_check(report, "author_self_review_precedes_independent_review")
        self.assertFalse(self_review["valid"])

    def test_self_review_requires_every_predeclared_check(self) -> None:
        def mutate(submission: dict) -> None:
            submission["self_review"]["checks"].pop()

        with TemporaryDirectory() as directory:
            report, _result, _paths = self.audit(Path(directory), mutate_submission=mutate)

        self.assertFalse(
            find_check(report, "author_self_review_precedes_independent_review")["valid"]
        )

    def test_unknown_finding_severity_is_rejected(self) -> None:
        def mutate(submission: dict) -> None:
            submission["findings"][0]["severity"] = "suggestion"

        with TemporaryDirectory() as directory:
            report, _result, _paths = self.audit(Path(directory), mutate_submission=mutate)

        findings = find_check(report, "findings_have_severity_and_exact_evidence")
        self.assertFalse(findings["valid"])
        self.assertEqual(findings["observed"]["errors"][0]["field"], "findings[0].severity")

    def test_finding_requires_exact_existing_evidence_selector(self) -> None:
        def mutate(submission: dict) -> None:
            submission["findings"][0]["evidence_path"] = "sensitivity_report.csv"

        with TemporaryDirectory() as directory:
            report, _result, _paths = self.audit(Path(directory), mutate_submission=mutate)

        findings = find_check(report, "findings_have_severity_and_exact_evidence")
        self.assertFalse(findings["valid"])
        self.assertIn("selector required", findings["observed"]["errors"][0]["reason"])

    def test_author_cannot_mark_response_resolved(self) -> None:
        def mutate(submission: dict) -> None:
            submission["author_responses"][0]["resolved"] = True

        with TemporaryDirectory() as directory:
            report, result, _paths = self.audit(Path(directory), mutate_submission=mutate)

        responses = find_check(report, "author_responses_use_evidence_statuses")
        self.assertFalse(responses["valid"])
        row = next(
            item
            for item in result["re_review"]["findings"]
            if item["finding_id"] == "review-finding-001"
        )
        self.assertFalse(row["closed"])

    def test_response_status_must_use_contract_vocabulary(self) -> None:
        def mutate(submission: dict) -> None:
            submission["author_responses"][0]["response_status"] = "fixed"

        with TemporaryDirectory() as directory:
            report, _result, _paths = self.audit(Path(directory), mutate_submission=mutate)

        self.assertFalse(find_check(report, "author_responses_use_evidence_statuses")["valid"])

    def test_every_finding_requires_exactly_one_response(self) -> None:
        def mutate(submission: dict) -> None:
            submission["author_responses"].pop()

        with TemporaryDirectory() as directory:
            report, result, _paths = self.audit(Path(directory), mutate_submission=mutate)

        self.assertFalse(find_check(report, "author_responses_use_evidence_statuses")["valid"])
        self.assertIn("review-finding-003", result["re_review"]["summary"]["open_findings"])

    def test_accepted_major_without_declared_rerun_stays_open(self) -> None:
        def mutate(submission: dict) -> None:
            submission["author_responses"][0]["rerun_check_ids"] = ["claim_evidence_audit"]

        with TemporaryDirectory() as directory:
            report, result, _paths = self.audit(Path(directory), mutate_submission=mutate)

        reruns = find_check(report, "changed_scopes_rerun_all_affected_checks")
        self.assertFalse(reruns["valid"])
        self.assertIn("review-finding-001", result["re_review"]["summary"]["open_blocker_or_major"])

    def test_stale_after_checksum_blocks_claim_change(self) -> None:
        def mutate(submission: dict) -> None:
            submission["author_responses"][0]["reviewed_claim_sha256"] = "f" * 64

        with TemporaryDirectory() as directory:
            report, _result, _paths = self.audit(Path(directory), mutate_submission=mutate)

        response = find_check(report, "author_responses_use_evidence_statuses")
        changed = find_check(report, "changed_claims_have_before_and_after_checksums")
        self.assertFalse(response["valid"])
        self.assertFalse(changed["valid"])

    def test_unchanged_claim_is_not_an_implemented_fix(self) -> None:
        def mutate(submission: dict) -> None:
            proposed = next(
                item
                for item in submission["proposed_claims"]
                if item["claim_id"] == "claim-sensitivity"
            )
            for index, claim in enumerate(submission["reviewed_claims"]):
                if claim["claim_id"] == "claim-sensitivity":
                    submission["reviewed_claims"][index] = proposed
            self.refresh_response_hash(submission, "review-finding-001", "claim-sensitivity")

        with TemporaryDirectory() as directory:
            report, _result, _paths = self.audit(Path(directory), mutate_submission=mutate)

        changed = find_check(report, "changed_claims_have_before_and_after_checksums")
        self.assertFalse(changed["valid"])
        self.assertEqual(changed["observed"]["errors"][0]["change_kind"], "unchanged")

    def test_semantically_overbroad_claim_fails_rerun_even_with_fresh_hash(self) -> None:
        def mutate(submission: dict) -> None:
            claim = next(
                item
                for item in submission["reviewed_claims"]
                if item["claim_id"] == "claim-sensitivity"
            )
            claim["assertion"]["robust_across_scenarios"] = True
            self.refresh_response_hash(submission, "review-finding-001", "claim-sensitivity")

        with TemporaryDirectory() as directory:
            report, _result, _paths = self.audit(Path(directory), mutate_submission=mutate)

        reruns = find_check(report, "changed_scopes_rerun_all_affected_checks")
        self.assertFalse(reruns["valid"])
        self.assertIn("sensitivity_analysis", reruns["observed"]["failed_checks"])

    def test_partially_accepted_major_remains_open(self) -> None:
        def mutate(submission: dict) -> None:
            submission["author_responses"][0]["response_status"] = "partially_accepted"

        with TemporaryDirectory() as directory:
            report, result, _paths = self.audit(Path(directory), mutate_submission=mutate)

        self.assertEqual(report["status"], "review_block")
        self.assertIn("review-finding-001", result["re_review"]["summary"]["open_blocker_or_major"])

    def test_declined_major_without_accepted_waiver_remains_open(self) -> None:
        def mutate(submission: dict) -> None:
            response = submission["author_responses"][0]
            response["response_status"] = "declined_with_evidence"
            response["changed_scopes"] = []
            response["rerun_check_ids"] = []

        with TemporaryDirectory() as directory:
            report, result, _paths = self.audit(Path(directory), mutate_submission=mutate)

        self.assertEqual(report["status"], "review_block")
        self.assertIn("review-finding-001", result["re_review"]["summary"]["open_blocker_or_major"])

    def test_tampered_upstream_output_blocks_review(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.inputs(root)
            target = paths["upstream_verification_package"] / "sensitivity_report.csv"
            target.write_text(target.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            report, _result = REVIEW.audit_peer_review(
                upstream_verification_package=paths["upstream_verification_package"],
                review_spec_path=paths["review_spec_path"],
                review_submission_path=paths["review_submission_path"],
            )

        upstream = find_check(report, "upstream_verification_package_is_immutable_and_ready")
        self.assertFalse(upstream["valid"])
        self.assertEqual(
            upstream["observed"]["errors"][0]["field"], "outputs.sensitivity_report.sha256"
        )

    def test_missing_upstream_package_returns_structured_review_block(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.inputs(root)
            report, result = REVIEW.audit_peer_review(
                upstream_verification_package=root / "missing-verification-package",
                review_spec_path=paths["review_spec_path"],
                review_submission_path=paths["review_submission_path"],
            )

        self.assertEqual(report["status"], "review_block")
        upstream = find_check(report, "upstream_verification_package_is_immutable_and_ready")
        self.assertFalse(upstream["valid"])
        self.assertIn("verification_manifest.json", upstream["observed"]["missing"])
        self.assertFalse(result["re_review"]["valid"])

    def test_major_waiver_requires_existing_evidence_and_named_owner(self) -> None:
        def mutate(submission: dict) -> None:
            response = submission["author_responses"][0]
            response["response_status"] = "declined_with_evidence"
            response["changed_scopes"] = []
            response["rerun_check_ids"] = []
            response["waiver"] = {
                "accepted_by_decision_owner": True,
                "owner_role": "head_of_support_operations",
                "evidence_path": "missing-waiver-evidence.json",
            }

        with TemporaryDirectory() as directory:
            report, result, _paths = self.audit(Path(directory), mutate_submission=mutate)

        self.assertEqual(report["status"], "review_block")
        finding = next(
            item
            for item in result["re_review"]["findings"]
            if item["finding_id"] == "review-finding-001"
        )
        self.assertFalse(finding["waiver_valid"])
        self.assertFalse(finding["closed"])

    def test_rehashed_later_stage_upstream_still_blocks_review(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.inputs(root)
            package = paths["upstream_verification_package"]
            state_path = package / "capstone_state.json"
            state = read_json(state_path)
            state["current_stage"] = "review"
            state["stage_status"] = "review_ready"
            write_json(state_path, state)
            self.refresh_verification_output(package, "capstone_state")
            submission = read_json(paths["review_submission_path"])
            submission["reviewer"]["reviewed_manifest_sha256"] = REVIEW.sha256_file(
                package / "verification_manifest.json"
            )
            write_json(paths["review_submission_path"], submission)
            report, _result = REVIEW.audit_peer_review(
                upstream_verification_package=package,
                review_spec_path=paths["review_spec_path"],
                review_submission_path=paths["review_submission_path"],
            )

        upstream = find_check(report, "upstream_verification_package_is_immutable_and_ready")
        self.assertFalse(upstream["valid"])
        self.assertEqual(upstream["observed"]["errors"][0]["field"], "capstone_state.stage_status")

    def test_audit_does_not_mutate_upstream_package(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.inputs(root)
            before = REVIEW.directory_checksums(paths["upstream_verification_package"])
            REVIEW.audit_peer_review(
                upstream_verification_package=paths["upstream_verification_package"],
                review_spec_path=paths["review_spec_path"],
                review_submission_path=paths["review_submission_path"],
            )
            after = REVIEW.directory_checksums(paths["upstream_verification_package"])

        self.assertEqual(before, after)

    def test_predeclared_spec_cannot_contain_observed_result(self) -> None:
        def mutate(spec: dict) -> None:
            spec["final_status"] = "review_ready"

        with TemporaryDirectory() as directory:
            report, _result, _paths = self.audit(Path(directory), mutate_spec=mutate)

        predeclared = find_check(report, "review_spec_is_predeclared_and_route_neutral")
        self.assertFalse(predeclared["valid"])
        self.assertEqual(
            predeclared["observed"]["errors"][-1]["forbidden_result_fields"],
            ["final_status"],
        )

    def test_reference_rubric_is_provisional_and_evidence_linked(self) -> None:
        with TemporaryDirectory() as directory:
            _report, result, _paths = self.audit(Path(directory))

        rubric = result["rubric"]
        self.assertEqual(len(rubric["dimensions"]), 6)
        self.assertEqual(rubric["summary"]["total_score"], 19)
        self.assertTrue(rubric["summary"]["provisional_only"])
        self.assertTrue(rubric["summary"]["final_defense_not_scored"])
        self.assertTrue(all(item["evidence_paths"] for item in rubric["dimensions"]))

    def test_built_manifest_covers_outputs_and_detects_tampering(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.inputs(root)
            output = root / "package"
            result = REVIEW.build_review_package(
                upstream_verification_package=paths["upstream_verification_package"],
                review_spec_path=paths["review_spec_path"],
                review_submission_path=paths["review_submission_path"],
                output_dir=output,
            )
            self.assertEqual(REVIEW.validate_review_package(output), [])
            self.assertTrue(result["manifest"]["reviewer_independence_disclosed"])
            self.assertFalse(result["manifest"]["author_declared_resolution_allowed"])
            target = output / "author_responses.csv"
            target.write_text(target.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            errors = REVIEW.validate_review_package(output)

        self.assertEqual(errors[0]["field"], "outputs.author_responses.sha256")

    def test_output_is_deterministic_for_same_inputs(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.inputs(root)
            first = root / "first"
            second = root / "second"
            kwargs = {
                "upstream_verification_package": paths["upstream_verification_package"],
                "review_spec_path": paths["review_spec_path"],
                "review_submission_path": paths["review_submission_path"],
            }
            REVIEW.build_review_package(**kwargs, output_dir=first)
            REVIEW.build_review_package(**kwargs, output_dir=second)

            for name in (
                "review_report.json",
                "finding_ledger.csv",
                "author_responses.csv",
                "re_review_report.json",
                "review_manifest.json",
            ):
                self.assertEqual((first / name).read_bytes(), (second / name).read_bytes(), name)

    def test_cli_fail_on_invalid_returns_nonzero(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self.inputs(root)
            submission = read_json(paths["review_submission_path"])
            submission["author_responses"][0]["rerun_check_ids"] = []
            write_json(paths["review_submission_path"], submission)
            completed = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--upstream-verification-package",
                    paths["upstream_verification_package"],
                    "--review-spec",
                    paths["review_spec_path"],
                    "--review-submission",
                    paths["review_submission_path"],
                    "--output-dir",
                    root / "package",
                    "--fail-on-invalid",
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )

        self.assertEqual(completed.returncode, 1)
        self.assertEqual(json.loads(completed.stdout)["status"], "review_block")
