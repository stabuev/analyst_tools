from __future__ import annotations

import copy
import csv
import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "decision_memo_builder.py"
CODE = ROOT / "code" / "main.py"
SPEC = importlib.util.spec_from_file_location("decision_memo_builder", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
BUILDER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BUILDER
SPEC.loader.exec_module(BUILDER)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def build_sample(root: Path):
    paths = BUILDER.write_sample_inputs(root / "inputs")
    return BUILDER.build_decision_memo(
        spec_path=paths["spec_path"],
        evidence_path=paths["evidence_path"],
        quality_gates_path=paths["quality_gates_path"],
        output_dir=root / "memo",
    )


def check_by_id(audit: dict, check_id: str) -> dict:
    return next(check for check in audit["checks"] if check["id"] == check_id)


class DecisionMemoBuilderTest(unittest.TestCase):
    def test_sample_memo_is_valid_with_visible_warnings(self) -> None:
        with TemporaryDirectory() as directory:
            result = build_sample(Path(directory))
            audit = result.audit

            self.assertTrue(audit["valid"])
            self.assertEqual(audit["readiness_status"], "ready_with_warnings")
            self.assertEqual(audit["recommended_decision"], "pause_rollout")
            self.assertEqual(audit["summary"]["claim_count"], 3)
            self.assertEqual(audit["summary"]["matrix_row_count"], 5)
            self.assertEqual(audit["summary"]["blocking_errors"], [])
            self.assertIn("quality_gate_warnings_are_visible", audit["summary"]["warnings"])
            self.assertIn("evidence_quality_warnings_are_disclosed", audit["summary"]["warnings"])
            for path in [result.memo_path, result.matrix_path, result.audit_path, result.manifest_path]:
                self.assertTrue(path.is_file(), path)

    def test_claim_evidence_matrix_links_claims_to_artifacts_and_metrics(self) -> None:
        with TemporaryDirectory() as directory:
            result = build_sample(Path(directory))
            rows = {row["evidence_id"]: row for row in read_csv(result.matrix_path)}

            self.assertEqual(rows["support-ticket-rate"]["claim_id"], "guardrails-above-threshold")
            self.assertEqual(rows["support-ticket-rate"]["metric_id"], "support_ticket_rate_7d")
            self.assertEqual(rows["support-ticket-rate"]["decision_impact"], "usable")
            self.assertEqual(rows["support-reason-coverage"]["decision_impact"], "usable_with_disclosure")
            self.assertEqual(rows["release-calendar"]["supports_decision"], "false")

    def test_uncited_claim_blocks_audit(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths = BUILDER.write_sample_inputs(root / "inputs")
            spec = read_json(paths["spec_path"])
            spec["claims"][0]["evidence_ids"] = []
            write_json(paths["spec_path"], spec)

            result = BUILDER.build_decision_memo(**paths, output_dir=root / "memo")

            self.assertFalse(result.audit["valid"])
            self.assertFalse(check_by_id(result.audit, "claims_have_evidence")["valid"])
            self.assertIn("claims_have_evidence", result.audit["summary"]["blocking_errors"])

    def test_unknown_evidence_id_blocks_audit(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths = BUILDER.write_sample_inputs(root / "inputs")
            spec = read_json(paths["spec_path"])
            spec["claims"][1]["evidence_ids"] = ["missing-quality-evidence"]
            write_json(paths["spec_path"], spec)

            result = BUILDER.build_decision_memo(**paths, output_dir=root / "memo")

            evidence_check = check_by_id(result.audit, "claim_evidence_ids_resolve")
            self.assertFalse(evidence_check["valid"])
            self.assertEqual(evidence_check["observed"], ["missing-quality-evidence"])

    def test_blocked_supporting_evidence_prevents_shipping(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths = BUILDER.write_sample_inputs(root / "inputs")
            rows = read_csv(paths["evidence_path"])
            for row in rows:
                if row["evidence_id"] == "cancel-rate":
                    row["quality_status"] = "block"
            write_csv(paths["evidence_path"], rows, sorted(BUILDER.REQUIRED_EVIDENCE_FIELDS))

            result = BUILDER.build_decision_memo(**paths, output_dir=root / "memo")

            self.assertFalse(result.audit["valid"])
            evidence_check = check_by_id(result.audit, "supporting_claims_have_usable_evidence")
            self.assertFalse(evidence_check["valid"])
            self.assertEqual(evidence_check["observed"], ["cancel-rate"])

    def test_quality_gate_block_prevents_publication(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths = BUILDER.write_sample_inputs(root / "inputs")
            rows = read_csv(paths["quality_gates_path"])
            rows[0]["status"] = "block"
            write_csv(paths["quality_gates_path"], rows, sorted(BUILDER.REQUIRED_GATE_FIELDS))

            result = BUILDER.build_decision_memo(**paths, output_dir=root / "memo")

            self.assertFalse(result.audit["valid"])
            gate_check = check_by_id(result.audit, "quality_gates_do_not_block_memo")
            self.assertFalse(gate_check["valid"])
            self.assertEqual(gate_check["observed"], ["freshness"])

    def test_overclaim_wording_is_rejected_without_causal_design(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths = BUILDER.write_sample_inputs(root / "inputs")
            spec = read_json(paths["spec_path"])
            spec["claims"][2]["statement"] = "Android release R002 caused the support ticket spike."
            write_json(paths["spec_path"], spec)

            result = BUILDER.build_decision_memo(**paths, output_dir=root / "memo")

            self.assertFalse(result.audit["valid"])
            overclaim_check = check_by_id(result.audit, "no_unsupported_overclaim_wording")
            self.assertFalse(overclaim_check["valid"])
            self.assertEqual(overclaim_check["observed"]["claims"], ["calendar-context-only"])

    def test_invalid_decision_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths = BUILDER.write_sample_inputs(root / "inputs")
            spec = read_json(paths["spec_path"])
            spec["recommended_decision"] = "ship_anyway"
            write_json(paths["spec_path"], spec)

            result = BUILDER.build_decision_memo(**paths, output_dir=root / "memo")

            self.assertFalse(result.audit["valid"])
            self.assertFalse(check_by_id(result.audit, "decision_is_allowed")["valid"])
            self.assertFalse(check_by_id(result.audit, "recommended_option_is_marked")["valid"])

    def test_rendered_memo_contains_required_sections_and_boundary(self) -> None:
        with TemporaryDirectory() as directory:
            result = build_sample(Path(directory))
            memo = result.memo_path.read_text(encoding="utf-8")

            for section in BUILDER.MEMO_REQUIRED_SECTIONS:
                self.assertIn(section, memo)
            self.assertIn("Recommended decision: `pause_rollout`", memo)
            self.assertIn("Causal claims allowed: `false`", memo)
            self.assertIn("support-and-cancel-reason-review", memo)

    def test_manifest_hashes_inputs_and_outputs(self) -> None:
        with TemporaryDirectory() as directory:
            result = build_sample(Path(directory))
            manifest = read_json(result.manifest_path)

            self.assertEqual(manifest["hash_algorithm"], "sha256")
            self.assertEqual(set(manifest["inputs"]), {"memo_spec", "evidence", "quality_gates"})
            self.assertEqual(
                set(manifest["outputs"]),
                {"claim_evidence_matrix", "executive_memo", "memo_audit"},
            )
            all_hashes = [
                item["sha256"]
                for section in ("inputs", "outputs")
                for item in manifest[section].values()
            ]
            self.assertTrue(all(len(value) == 64 for value in all_hashes))

    def test_cli_builds_package_and_returns_machine_readable_report(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths = BUILDER.write_sample_inputs(root / "inputs")
            proc = subprocess.run(
                [
                    sys.executable,
                    str(ARTIFACT),
                    "--spec",
                    str(paths["spec_path"]),
                    "--evidence",
                    str(paths["evidence_path"]),
                    "--quality-gates",
                    str(paths["quality_gates_path"]),
                    "--output-dir",
                    str(root / "memo"),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            report = json.loads(proc.stdout)
            self.assertTrue(report["valid"])
            self.assertEqual(report["readiness_status"], "ready_with_warnings")
            self.assertTrue(Path(report["manifest_path"]).is_file())

    def test_cli_write_example_can_generate_inputs_before_building(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            proc = subprocess.run(
                [
                    sys.executable,
                    str(ARTIFACT),
                    "--write-example",
                    str(root / "example-inputs"),
                    "--output-dir",
                    str(root / "memo"),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue((root / "example-inputs" / "memo_spec.json").is_file())
            self.assertTrue((root / "memo" / "executive_memo.md").is_file())

    def test_code_example_runs_without_external_files(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(CODE)],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["valid"])
        self.assertEqual(payload["recommended_decision"], "pause_rollout")
        self.assertEqual(payload["files"], [
            "executive_memo.md",
            "claim_evidence_matrix.csv",
            "memo_audit.json",
            "manifest.json",
        ])


if __name__ == "__main__":
    unittest.main()
