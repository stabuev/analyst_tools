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
PHASE = ROOT.parent
ARTIFACT = ROOT / "outputs" / "robust_evidence_packager.py"
PACKAGE = ROOT / "outputs" / "statistical-evidence-report"
CODE = ROOT / "code" / "main.py"

MODULE_SPEC = importlib.util.spec_from_file_location("robust_evidence_packager", ARTIFACT)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
PACKAGER = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(PACKAGER)


class RobustEvidencePackagerTest(unittest.TestCase):
    def test_package_contains_required_delivery_files(self) -> None:
        required = [
            "question.json",
            "sampling/sampling-audit.json",
            "distributions/distribution-cards.json",
            "estimates/point-estimates.csv",
            "estimates/bias-variance.csv",
            "estimates/confidence-intervals.csv",
            "estimates/bootstrap-intervals.json",
            "association/correlation-audit.json",
            "regression/coefficients.csv",
            "regression/diagnostics.json",
            "robustness/robust-estimates.csv",
            "robustness/sensitivity.json",
            "figures/sampling-bias.png",
            "figures/interval-coverage.png",
            "figures/regression-diagnostics.png",
            "report.md",
            "manifest.json",
        ]
        for relative in required:
            self.assertTrue((PACKAGE / relative).exists(), relative)

    def test_manifest_checksums_match_files(self) -> None:
        manifest = json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(manifest["file_count"], 16)
        for relative, metadata in manifest["files"].items():
            self.assertEqual(PACKAGER.sha256(PACKAGE / relative), metadata["sha256"])
            self.assertGreater(metadata["bytes"], 0)

    def test_robust_estimates_include_mean_median_trimmed_and_winsorized(self) -> None:
        with (PACKAGE / "robustness" / "robust-estimates.csv").open(encoding="utf-8", newline="") as source:
            rows = list(csv.DictReader(source))
        revenue_methods = {row["method"] for row in rows if row["metric_id"] == "first_order_amount_rub"}
        self.assertIn("mean", revenue_methods)
        self.assertIn("median", revenue_methods)
        self.assertIn("trimmed_mean_20pct", revenue_methods)
        self.assertIn("winsorized_mean_10_90", revenue_methods)

    def test_sensitivity_report_carries_nonparametric_and_regression_flags(self) -> None:
        sensitivity = json.loads((PACKAGE / "robustness" / "sensitivity.json").read_text(encoding="utf-8"))
        self.assertIn("leave_one_out_revenue", sensitivity)
        self.assertEqual(sensitivity["nonparametric_comparison"]["method"], "mann_whitney_u")
        self.assertIn("too_few_rows_for_breusch_pagan", sensitivity["regression_warning_flags"])

    def test_report_links_claims_to_artifacts(self) -> None:
        report = (PACKAGE / "report.md").read_text(encoding="utf-8")
        self.assertIn("sampling/sampling-audit.json", report)
        self.assertIn("estimates/bootstrap-intervals.json", report)
        self.assertIn("robustness/sensitivity.json", report)
        self.assertIn("association-only", report)

    def test_figures_are_png_files(self) -> None:
        for relative in [
            "figures/sampling-bias.png",
            "figures/interval-coverage.png",
            "figures/regression-diagnostics.png",
        ]:
            path = PACKAGE / relative
            self.assertEqual(path.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
            self.assertGreater(path.stat().st_size, 1000)

    def test_cli_builds_package_in_new_directory(self) -> None:
        with TemporaryDirectory() as directory:
            output_dir = Path(directory) / "evidence"
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--phase-root",
                    PHASE,
                    "--output-dir",
                    output_dir,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["valid"])
            self.assertTrue((output_dir / "manifest.json").exists())

    def test_committed_package_matches_builder_manifest_shape(self) -> None:
        report = PACKAGER.build_package(PHASE, PACKAGE)
        manifest = json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(report["manifest"], manifest)

    def test_code_example_prints_package_summary(self) -> None:
        result = subprocess.run(
            [sys.executable, CODE],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["valid"])
        self.assertGreaterEqual(payload["files"], 16)


if __name__ == "__main__":
    unittest.main()
