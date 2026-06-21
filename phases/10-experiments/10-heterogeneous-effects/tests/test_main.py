from __future__ import annotations

import csv
import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
PHASE_ROOT = ROOT.parent
ARTIFACT = ROOT / "outputs" / "segment_effect_auditor.py"
POLICY = ROOT / "outputs" / "segment_policy.json"
REPORT = ROOT / "outputs" / "heterogeneity_report.json"
SEGMENT_EFFECTS = ROOT / "outputs" / "segment_effects.csv"
INTERACTIONS = ROOT / "outputs" / "interaction_checks.csv"
MANIFEST = ROOT / "outputs" / "segment_manifest.json"
PROTOCOL = PHASE_ROOT / "01-hypothesis-and-metric" / "outputs" / "experiment_protocol.json"
OBSERVATIONS = PHASE_ROOT / "05-means-and-proportions" / "outputs" / "metric_observations.csv"
USERS = PHASE_ROOT / "data" / "tiny" / "users.csv"
MULTIPLE_TESTING = PHASE_ROOT / "08-multiple-testing" / "outputs" / "multiple_testing_report.json"
PEEKING = PHASE_ROOT / "09-peeking" / "outputs" / "sequential_monitoring_report.json"
CODE = ROOT / "code" / "main.py"

MODULE_SPEC = importlib.util.spec_from_file_location("segment_effect_auditor", ARTIFACT)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
AUDITOR = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(AUDITOR)


def load_examples() -> tuple[dict, dict, list[dict], list[dict], dict, dict]:
    return (
        AUDITOR.read_json(PROTOCOL),
        AUDITOR.read_json(POLICY),
        AUDITOR.read_csv(OBSERVATIONS),
        AUDITOR.read_csv(USERS),
        AUDITOR.read_json(MULTIPLE_TESTING),
        AUDITOR.read_json(PEEKING),
    )


def row_by_segment(rows: list[dict], dimension: str, segment_value: str, metric_id: str) -> dict:
    for row in rows:
        if row["dimension"] == dimension and row["segment_value"] == segment_value and row["metric_id"] == metric_id:
            return row
    raise AssertionError(f"segment not found: {dimension}={segment_value} {metric_id}")


class SegmentEffectAuditTest(unittest.TestCase):
    def setUp(self) -> None:
        (
            self.protocol,
            self.policy,
            self.observations,
            self.users,
            self.multiple_testing,
            self.peeking,
        ) = load_examples()

    def build(
        self,
        policy: dict | None = None,
        multiple_testing: dict | None = None,
        peeking: dict | None = None,
    ) -> tuple[dict, list[dict], list[dict], dict]:
        return AUDITOR.build_report(
            self.protocol,
            self.policy if policy is None else policy,
            self.observations,
            self.users,
            self.multiple_testing if multiple_testing is None else multiple_testing,
            self.peeking if peeking is None else peeking,
        )

    def test_committed_outputs_match_calculated_report(self) -> None:
        report, segment_rows, interaction_rows, manifest = self.build()
        self.assertEqual(report, json.loads(REPORT.read_text(encoding="utf-8")))
        self.assertEqual(manifest, json.loads(MANIFEST.read_text(encoding="utf-8")))
        with TemporaryDirectory() as directory:
            root = Path(directory)
            segment_path = root / "segment_effects.csv"
            interaction_path = root / "interaction_checks.csv"
            AUDITOR.write_csv(segment_path, segment_rows, AUDITOR.SEGMENT_EFFECT_FIELDS)
            AUDITOR.write_csv(interaction_path, interaction_rows, AUDITOR.INTERACTION_FIELDS)
            self.assertEqual(segment_path.read_text(encoding="utf-8"), SEGMENT_EFFECTS.read_text(encoding="utf-8"))
            self.assertEqual(interaction_path.read_text(encoding="utf-8"), INTERACTIONS.read_text(encoding="utf-8"))
        self.assertTrue(report["valid"])
        self.assertFalse(report["ready_for_decision"])
        self.assertEqual(report["summary"]["segment_rows"], 13)

    def test_predeclared_platform_effect_is_diagnostic_but_below_minimum(self) -> None:
        report, segment_rows, _, _ = self.build()
        row = row_by_segment(segment_rows, "platform", "android", "activation_rate_7d")
        self.assertTrue(row["predeclared"])
        self.assertTrue(row["has_both_variants"])
        self.assertFalse(row["meets_minimum_cell_size"])
        self.assertEqual(row["absolute_lift"], -0.666667)
        self.assertEqual(row["p_value"], 0.136037)
        self.assertEqual(row["status"], "below_minimum_cell_size")
        self.assertIn("segment_cells_below_minimum_size", report["summary"]["decision_blockers"])
        self.assertFalse(row["decision_eligible"])

    def test_acquisition_channel_missing_variant_is_not_an_effect(self) -> None:
        _, segment_rows, _, _ = self.build()
        paid_search = row_by_segment(segment_rows, "acquisition_channel", "paid_search", "activation_rate_7d")
        organic = row_by_segment(segment_rows, "acquisition_channel", "organic", "activation_rate_7d")
        self.assertEqual(paid_search["control_units"], 0)
        self.assertEqual(paid_search["treatment_units"], 1)
        self.assertEqual(organic["control_units"], 2)
        self.assertEqual(organic["treatment_units"], 0)
        self.assertEqual(paid_search["status"], "missing_variant")
        self.assertEqual(paid_search["p_value"], "nan")
        self.assertIn("missing_control_or_treatment_in_segment", paid_search["diagnostics"])

    def test_post_hoc_country_ru_is_exploratory_only(self) -> None:
        _, segment_rows, _, _ = self.build()
        row = row_by_segment(segment_rows, "country", "RU", "activation_rate_7d")
        self.assertFalse(row["predeclared"])
        self.assertEqual(row["segment_role"], "post_hoc")
        self.assertEqual(row["decision_use"], "exploratory_only")
        self.assertEqual(row["absolute_lift"], -1.0)
        self.assertEqual(row["p_value"], 0.083265)
        self.assertIn("post_hoc_exploratory_only", row["diagnostics"])
        self.assertIn("segment_dimension_not_predeclared", row["diagnostics"])
        self.assertFalse(row["decision_eligible"])

    def test_interaction_checks_require_overlap_in_two_segments(self) -> None:
        report, _, interaction_rows, _ = self.build()
        self.assertEqual(len(interaction_rows), 5)
        self.assertEqual({row["status"] for row in interaction_rows}, {"insufficient_overlap"})
        acquisition = next(row for row in interaction_rows if row["dimension"] == "acquisition_channel")
        self.assertEqual(acquisition["estimable_segments"], 0)
        self.assertIn("interaction_checks_insufficient_overlap", report["summary"]["decision_blockers"])

    def test_policy_cannot_promote_post_hoc_country_to_predeclared(self) -> None:
        policy = json.loads(json.dumps(self.policy))
        policy["dimensions"][2]["predeclared"] = True
        report, _, _, manifest = self.build(policy=policy)
        self.assertFalse(report["valid"])
        self.assertFalse(manifest["valid"])
        self.assertIn("predeclared_dimensions_match_protocol", report["summary"]["blocking_failures"])

    def test_policy_minimum_cell_size_must_match_protocol(self) -> None:
        policy = json.loads(json.dumps(self.policy))
        policy["minimum_cell_size"] = 1
        report, segment_rows, _, _ = self.build(policy=policy)
        country_ru = row_by_segment(segment_rows, "country", "RU", "activation_rate_7d")
        self.assertEqual(country_ru["status"], "exploratory_only")
        self.assertFalse(report["valid"])
        self.assertIn("minimum_cell_size_matches_protocol", report["summary"]["blocking_failures"])

    def test_invalid_upstream_report_invalidates_segment_audit(self) -> None:
        multiple_testing = json.loads(json.dumps(self.multiple_testing))
        multiple_testing["valid"] = False
        report, _, _, _ = self.build(multiple_testing=multiple_testing)
        self.assertFalse(report["valid"])
        self.assertIn("upstream_multiple_testing_valid", report["summary"]["blocking_failures"])

    def test_code_example_prints_segment_summary(self) -> None:
        result = subprocess.run(
            [sys.executable, CODE],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(result.stdout)
        self.assertTrue(payload["valid"])
        self.assertFalse(payload["ready_for_decision"])
        self.assertEqual(payload["minimum_cell_size"], 500)
        self.assertEqual(payload["platform_android_primary_lift"], -0.666667)
        self.assertEqual(payload["platform_android_status"], "below_minimum_cell_size")
        self.assertEqual(payload["missing_variant_rows"], 10)
        self.assertEqual(payload["manifest_artifact"], "segment-effect-auditor")

    def test_cli_writes_report_effects_interactions_and_manifest(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            report_path = root / "report.json"
            segment_path = root / "segment_effects.csv"
            interaction_path = root / "interaction_checks.csv"
            manifest_path = root / "manifest.json"
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--protocol",
                    PROTOCOL,
                    "--segment-policy",
                    POLICY,
                    "--observations",
                    OBSERVATIONS,
                    "--users",
                    USERS,
                    "--multiple-testing-report",
                    MULTIPLE_TESTING,
                    "--peeking-report",
                    PEEKING,
                    "--output-report",
                    report_path,
                    "--output-segment-effects",
                    segment_path,
                    "--output-interactions",
                    interaction_path,
                    "--output-manifest",
                    manifest_path,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), json.loads(report_path.read_text(encoding="utf-8")))
            with segment_path.open(encoding="utf-8", newline="") as source:
                self.assertEqual(len(list(csv.DictReader(source))), 13)
            with interaction_path.open(encoding="utf-8", newline="") as source:
                self.assertEqual(len(list(csv.DictReader(source))), 5)
            self.assertEqual(json.loads(manifest_path.read_text(encoding="utf-8"))["artifact"], "segment-effect-auditor")


if __name__ == "__main__":
    unittest.main()
