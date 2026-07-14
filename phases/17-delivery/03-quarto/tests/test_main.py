from __future__ import annotations

import csv
import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "quarto_report_packager.py"
CODE = ROOT / "code" / "main.py"
SPEC = importlib.util.spec_from_file_location("quarto_report_packager", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
PACKAGER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PACKAGER
SPEC.loader.exec_module(PACKAGER)


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
    paths = PACKAGER.write_sample_inputs(root / "inputs")
    result = PACKAGER.build_quarto_report(
        spec_path=paths["spec_path"],
        metrics_path=paths["metrics_path"],
        evidence_path=paths["evidence_path"],
        workbook_audit_path=paths["workbook_audit_path"],
        memo_audit_path=paths["memo_audit_path"],
        output_dir=root / "report",
    )
    return paths, result


def check_by_id(audit: dict, check_id: str) -> dict:
    return next(check for check in audit["checks"] if check["id"] == check_id)


class QuartoReportPackagerTest(unittest.TestCase):
    def test_sample_report_package_is_valid_and_writes_files(self) -> None:
        with TemporaryDirectory() as directory:
            _paths, result = build_sample(Path(directory))

            self.assertTrue(result.audit["valid"])
            self.assertEqual(result.audit["readiness_status"], "ready")
            for path in [
                result.project_path,
                result.qmd_path,
                result.params_path,
                result.html_path,
                result.figure_path,
                result.source_links_path,
                result.audit_path,
                result.rebuild_check_path,
                result.manifest_path,
            ]:
                self.assertTrue(path.is_file(), path)

    def test_qmd_contains_executable_python_parameters_tables_and_figure_ref(self) -> None:
        with TemporaryDirectory() as directory:
            _paths, result = build_sample(Path(directory))
            qmd = result.qmd_path.read_text(encoding="utf-8")

            self.assertIn("#| tags: [parameters]", qmd)
            self.assertGreaterEqual(qmd.count("```{python}"), 4)
            self.assertIn("#| label: tbl-metrics", qmd)
            self.assertIn("#| label: tbl-evidence", qmd)
            self.assertIn("@fig-guardrails", qmd)
            self.assertIn("quarto render report.qmd --to html --execute-params params.yml", qmd)

    def test_quarto_project_config_and_params_are_portable(self) -> None:
        with TemporaryDirectory() as directory:
            paths, result = build_sample(Path(directory))
            project = yaml.safe_load(result.project_path.read_text(encoding="utf-8"))
            params = yaml.safe_load(result.params_path.read_text(encoding="utf-8"))

            self.assertEqual(project["project"]["render"], ["report.qmd"])
            self.assertTrue(project["format"]["html"]["embed-resources"])
            self.assertEqual(params["metric_status_filter"], "all")
            self.assertFalse(Path(params["metrics_path"]).is_absolute())
            self.assertTrue((result.output_dir / params["metrics_path"]).resolve().samefile(paths["metrics_path"]))

    def test_html_preview_contains_decision_tables_sources_and_figure(self) -> None:
        with TemporaryDirectory() as directory:
            _paths, result = build_sample(Path(directory))
            html = result.html_path.read_text(encoding="utf-8")

            self.assertIn("pause_rollout", html)
            self.assertIn("support_ticket_rate_7d", html)
            self.assertIn("claim_evidence_matrix", html)
            self.assertIn("fig-guardrails", html)
            self.assertIn("Source links", html)
            self.assertIn("Limitations", html)

    def test_source_links_cover_required_artifacts_with_hashes(self) -> None:
        with TemporaryDirectory() as directory:
            paths, result = build_sample(Path(directory))
            rows = read_csv(result.source_links_path)
            spec = read_json(paths["spec_path"])

            self.assertEqual(
                {row["source_id"] for row in rows},
                {item["source_id"] for item in spec["source_artifacts"]},
            )
            self.assertTrue(all(len(row["sha256"]) == 64 for row in rows))
            self.assertTrue(all(not Path(row["path"]).is_absolute() for row in rows))

    def test_manifest_hashes_inputs_and_outputs(self) -> None:
        with TemporaryDirectory() as directory:
            _paths, result = build_sample(Path(directory))
            manifest = read_json(result.manifest_path)

            self.assertEqual(manifest["hash_algorithm"], "sha256")
            self.assertEqual(manifest["render_command"], "quarto render report.qmd --to html --execute-params params.yml")
            self.assertEqual(manifest["renderer_used"], "lesson_deterministic_html_preview")
            self.assertIn("metric_summary", manifest["inputs"])
            self.assertIn("report_html", manifest["outputs"])
            hashes = [
                item["sha256"]
                for section in ("inputs", "outputs")
                for item in manifest[section].values()
            ]
            self.assertTrue(all(len(value) == 64 for value in hashes))

    def test_rebuild_check_detects_changed_input_and_changed_outputs(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths, first = build_sample(root)
            rows = read_csv(paths["metrics_path"])
            rows[0]["current"] = "0.027"
            write_csv(paths["metrics_path"], rows, PACKAGER.REQUIRED_METRIC_COLUMNS)

            second = PACKAGER.build_quarto_report(
                spec_path=paths["spec_path"],
                metrics_path=paths["metrics_path"],
                evidence_path=paths["evidence_path"],
                workbook_audit_path=paths["workbook_audit_path"],
                memo_audit_path=paths["memo_audit_path"],
                output_dir=root / "report-after-change",
                previous_manifest_path=first.manifest_path,
            )

            rebuild = read_json(second.rebuild_check_path)
            self.assertTrue(rebuild["valid"])
            self.assertEqual(rebuild["changed_inputs"], ["metric_summary"])
            self.assertIn("report_html", rebuild["changed_outputs"])
            self.assertIn("figure_svg", rebuild["changed_outputs"])

    def test_rebuild_check_flags_unexpected_output_change_without_input_change(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            _paths, first = build_sample(root)
            stale_manifest = read_json(first.manifest_path)
            stale_manifest["outputs"]["report_html"]["sha256"] = "0" * 64
            stale_path = root / "stale_manifest.json"
            write_json(stale_path, stale_manifest)

            paths = PACKAGER.write_sample_inputs(root / "same-inputs")
            second = PACKAGER.build_quarto_report(
                spec_path=paths["spec_path"],
                metrics_path=paths["metrics_path"],
                evidence_path=paths["evidence_path"],
                workbook_audit_path=paths["workbook_audit_path"],
                memo_audit_path=paths["memo_audit_path"],
                output_dir=root / "report-second",
                previous_manifest_path=stale_path,
            )

            rebuild = read_json(second.rebuild_check_path)
            self.assertFalse(rebuild["valid"])
            self.assertIn("report_html", rebuild["unexpected_output_changes"])

    def test_invalid_workbook_audit_blocks_report(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths = PACKAGER.write_sample_inputs(root / "inputs")
            workbook_audit = read_json(paths["workbook_audit_path"])
            workbook_audit["valid"] = False
            workbook_audit["summary"]["blocking_errors"] = ["summary_formulas_are_present"]
            write_json(paths["workbook_audit_path"], workbook_audit)

            result = PACKAGER.build_quarto_report(**paths, output_dir=root / "report")

            self.assertFalse(result.audit["valid"])
            self.assertFalse(check_by_id(result.audit, "upstream_workbook_audit_is_valid")["valid"])

    def test_missing_limitations_blocks_report(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths = PACKAGER.write_sample_inputs(root / "inputs")
            spec = read_json(paths["spec_path"])
            spec["limitations"] = []
            write_json(paths["spec_path"], spec)

            result = PACKAGER.build_quarto_report(**paths, output_dir=root / "report")

            self.assertFalse(result.audit["valid"])
            self.assertFalse(check_by_id(result.audit, "limitations_are_explicit")["valid"])

    def test_broken_source_link_blocks_report(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths = PACKAGER.write_sample_inputs(root / "inputs")
            spec = read_json(paths["spec_path"])
            spec["source_artifacts"][0]["path"] = "missing_memo.md"
            write_json(paths["spec_path"], spec)

            result = PACKAGER.build_quarto_report(**paths, output_dir=root / "report")

            self.assertFalse(result.audit["valid"])
            link_check = check_by_id(result.audit, "source_artifacts_are_portable_and_present")
            self.assertFalse(link_check["valid"])
            self.assertIn("missing_source:executive_memo:missing_memo.md", link_check["observed"])

    def test_hidden_sensitive_source_column_blocks_report(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths = PACKAGER.write_sample_inputs(root / "inputs")
            rows = read_csv(paths["metrics_path"])
            for row in rows:
                row["user_email"] = "customer@example.com"
            write_csv(paths["metrics_path"], rows, PACKAGER.REQUIRED_METRIC_COLUMNS + ["user_email"])

            result = PACKAGER.build_quarto_report(**paths, output_dir=root / "report")

            self.assertFalse(result.audit["valid"])
            sensitive_check = check_by_id(result.audit, "no_sensitive_fields_in_report_sources")
            self.assertFalse(sensitive_check["valid"])
            self.assertEqual(sensitive_check["observed"]["headers"], ["user_email"])

    def test_audit_detects_missing_required_figure_after_tampering(self) -> None:
        with TemporaryDirectory() as directory:
            paths, result = build_sample(Path(directory))
            result.figure_path.unlink()
            audit = PACKAGER.audit_report_package(
                output_dir=result.output_dir,
                spec=read_json(paths["spec_path"]),
                metrics=read_csv(paths["metrics_path"]),
                evidence=read_csv(paths["evidence_path"]),
                workbook_audit=read_json(paths["workbook_audit_path"]),
                memo_audit=read_json(paths["memo_audit_path"]),
                source_root=paths["spec_path"].parent,
                initial_checks=[],
            )

            self.assertFalse(audit["valid"])
            self.assertFalse(check_by_id(audit, "required_figures_exist_and_are_referenced")["valid"])

    def test_cli_write_example_builds_report_package(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            proc = subprocess.run(
                [
                    sys.executable,
                    str(ARTIFACT),
                    "--write-example",
                    str(root / "inputs"),
                    "--output-dir",
                    str(root / "report"),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertTrue(payload["valid"])
            self.assertTrue((root / "report" / "report.qmd").is_file())
            self.assertTrue((root / "report" / "render_manifest.json").is_file())

    def test_cli_returns_nonzero_for_invalid_report_when_requested(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths = PACKAGER.write_sample_inputs(root / "inputs")
            spec = read_json(paths["spec_path"])
            spec["limitations"] = []
            write_json(paths["spec_path"], spec)

            proc = subprocess.run(
                [
                    sys.executable,
                    str(ARTIFACT),
                    "--spec",
                    str(paths["spec_path"]),
                    "--metrics",
                    str(paths["metrics_path"]),
                    "--evidence",
                    str(paths["evidence_path"]),
                    "--workbook-audit",
                    str(paths["workbook_audit_path"]),
                    "--memo-audit",
                    str(paths["memo_audit_path"]),
                    "--output-dir",
                    str(root / "report"),
                    "--fail-on-invalid",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(proc.returncode, 2, proc.stderr)
            self.assertFalse(json.loads(proc.stdout)["valid"])

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
        self.assertEqual(payload["files"], [
            "_quarto.yml",
            "params.yml",
            "report.qmd",
            "report.html",
            "figures/guardrail_status.svg",
            "source_links.csv",
            "report_audit.json",
            "rebuild_check.json",
            "render_manifest.json",
        ])


if __name__ == "__main__":
    unittest.main()
