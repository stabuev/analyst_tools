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
PHASE_ROOT = ROOT.parent
ARTIFACT = ROOT / "outputs" / "product_problem_builder.py"
SAMPLE_PACKAGE = ROOT / "outputs" / "product-problem-investigation"
SPEC = importlib.util.spec_from_file_location("product_problem_builder", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
BUILDER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BUILDER
SPEC.loader.exec_module(BUILDER)


def build_tmp(root: Path) -> Path:
    package = root / "product-problem-investigation"
    result = BUILDER.build_package(PHASE_ROOT, package)
    if not result.report["valid"]:
        raise AssertionError(result.report)
    return package


def check_by_id(checks: list[dict], check_id: str) -> dict:
    return next(check for check in checks if check["id"] == check_id)


class ProductProblemBuilderTest(unittest.TestCase):
    def test_package_contains_required_delivery_files_and_valid_manifest(self) -> None:
        with TemporaryDirectory() as directory:
            package = build_tmp(Path(directory))
            required = {
                "brief.md",
                "metric-tree.json",
                "metric-specs.json",
                "tracking-plan.json",
                "audits/event-quality.json",
                "audits/metric-quality.json",
                "metrics/activity.csv",
                "metrics/funnel.csv",
                "metrics/cohorts.csv",
                "metrics/retention.csv",
                "metrics/monetization.csv",
                "metrics/segments.csv",
                "metrics/guardrails.csv",
                "metrics/anomalies.json",
                "figures/metric-trend.png",
                "figures/segment-decomposition.png",
                "report.md",
                "recommendation.json",
                "manifest.json",
            }
            files = {path.relative_to(package).as_posix() for path in package.rglob("*") if path.is_file()}
            self.assertEqual(files, required)
            self.assertTrue(all(item["valid"] for item in BUILDER.verify_manifest(package)))

    def test_sample_package_recommendation_matches_builder_output(self) -> None:
        with TemporaryDirectory() as directory:
            package = build_tmp(Path(directory))
            self.assertEqual(
                BUILDER.read_json(package / "recommendation.json"),
                BUILDER.read_json(SAMPLE_PACKAGE / "recommendation.json"),
            )
            self.assertEqual(
                (package / "report.md").read_text(encoding="utf-8"),
                (SAMPLE_PACKAGE / "report.md").read_text(encoding="utf-8"),
            )

    def test_recommendation_decision_and_options_are_machine_readable(self) -> None:
        recommendation = BUILDER.read_json(SAMPLE_PACKAGE / "recommendation.json")
        self.assertEqual(recommendation["decision"], "investigate")
        self.assertEqual(recommendation["allowed_decisions"], BUILDER.ALLOWED_DECISIONS)
        recommended = [option for option in recommendation["options"] if option["status"] == "recommended"]
        self.assertEqual([option["option_id"] for option in recommended], ["investigate"])
        self.assertFalse(recommendation["causal_claims_allowed"])

    def test_each_claim_has_existing_artifact_and_resolved_metric(self) -> None:
        recommendation = BUILDER.read_json(SAMPLE_PACKAGE / "recommendation.json")
        checks = BUILDER.validate_recommendation(recommendation, SAMPLE_PACKAGE)
        self.assertTrue(all(check["valid"] for check in checks), checks)
        for claim in recommendation["claims"]:
            self.assertTrue(claim["artifact_paths"])
            self.assertTrue(claim["metric_ids"])
            self.assertTrue(claim["limitation"])

    def test_causal_wording_is_rejected_without_causal_design(self) -> None:
        recommendation = copy.deepcopy(BUILDER.read_json(SAMPLE_PACKAGE / "recommendation.json"))
        recommendation["claims"][0]["statement"] = "Release R002 caused the support ticket spike."
        checks = BUILDER.validate_recommendation(recommendation, SAMPLE_PACKAGE)
        causal_check = check_by_id(checks, "no_unsupported_causal_claims")
        self.assertFalse(causal_check["valid"])
        self.assertEqual(causal_check["observed"], ["quality-gates-passed"])

    def test_uncited_claim_is_rejected(self) -> None:
        recommendation = copy.deepcopy(BUILDER.read_json(SAMPLE_PACKAGE / "recommendation.json"))
        recommendation["claims"][0]["artifact_paths"] = []
        checks = BUILDER.validate_recommendation(recommendation, SAMPLE_PACKAGE)
        self.assertFalse(check_by_id(checks, "claims_are_cited")["valid"])

    def test_unknown_metric_id_is_rejected(self) -> None:
        recommendation = copy.deepcopy(BUILDER.read_json(SAMPLE_PACKAGE / "recommendation.json"))
        recommendation["claims"][0]["metric_ids"] = ["mystery_rate"]
        checks = BUILDER.validate_recommendation(recommendation, SAMPLE_PACKAGE)
        self.assertFalse(check_by_id(checks, "claim_metrics_resolve")["valid"])
        self.assertEqual(check_by_id(checks, "claim_metrics_resolve")["observed"], ["mystery_rate"])

    def test_invalid_decision_is_rejected(self) -> None:
        recommendation = copy.deepcopy(BUILDER.read_json(SAMPLE_PACKAGE / "recommendation.json"))
        recommendation["decision"] = "ship_anyway"
        checks = BUILDER.validate_recommendation(recommendation, SAMPLE_PACKAGE)
        self.assertFalse(check_by_id(checks, "decision_allowed")["valid"])
        self.assertFalse(check_by_id(checks, "recommended_option_present")["valid"])

    def test_event_quality_audit_mirrors_anomaly_gates(self) -> None:
        audit = BUILDER.read_json(SAMPLE_PACKAGE / "audits" / "event-quality.json")
        anomalies = BUILDER.read_json(SAMPLE_PACKAGE / "metrics" / "anomalies.json")
        self.assertTrue(audit["valid"])
        self.assertEqual(audit["summary"], anomalies["summary"])
        self.assertEqual(audit["checks"], anomalies["quality_gates"])

    def test_metric_quality_audit_requires_all_package_files(self) -> None:
        with TemporaryDirectory() as directory:
            package = build_tmp(Path(directory))
            (package / "figures" / "metric-trend.png").unlink()
            recommendation = BUILDER.read_json(package / "recommendation.json")
            audit = BUILDER.build_metric_quality_audit(package, recommendation)
            self.assertFalse(audit["valid"])
            self.assertFalse(check_by_id(audit["checks"], "required_files_present")["valid"])
            self.assertEqual(
                check_by_id(audit["checks"], "required_files_present")["observed"],
                ["figures/metric-trend.png"],
            )

    def test_copied_metrics_are_byte_identical_to_sources(self) -> None:
        manifest = BUILDER.read_json(SAMPLE_PACKAGE / "manifest.json")
        for relative, source_info in manifest["source_artifacts"].items():
            source = PHASE_ROOT / source_info["source"]
            self.assertEqual((SAMPLE_PACKAGE / relative).read_bytes(), source.read_bytes())

    def test_figures_are_png_files(self) -> None:
        for name in ("metric-trend.png", "segment-decomposition.png"):
            payload = (SAMPLE_PACKAGE / "figures" / name).read_bytes()
            self.assertTrue(payload.startswith(b"\x89PNG\r\n\x1a\n"))
            self.assertGreater(len(payload), 1000)

    def test_cli_builds_package_and_prints_report(self) -> None:
        with TemporaryDirectory() as directory:
            package = Path(directory) / "delivery"
            proc = subprocess.run(
                [
                    sys.executable,
                    str(ARTIFACT),
                    "--phase-root",
                    str(PHASE_ROOT),
                    "--output",
                    str(package),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            report = json.loads(proc.stdout)
            self.assertTrue(report["valid"])
            self.assertEqual(report["decision"], "investigate")
            self.assertTrue((package / "manifest.json").is_file())

    def test_missing_source_artifact_fails_fast(self) -> None:
        with TemporaryDirectory() as directory:
            with self.assertRaises(FileNotFoundError):
                BUILDER.build_package(Path(directory) / "empty-phase", Path(directory) / "out")


if __name__ == "__main__":
    unittest.main()
