from __future__ import annotations

import csv
import importlib.util
import json
import subprocess
import sys
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "multi_format_report_renderer.py"
CODE = ROOT / "code" / "main.py"
SPEC = importlib.util.spec_from_file_location("multi_format_report_renderer", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
RENDERER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = RENDERER
SPEC.loader.exec_module(RENDERER)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def build_sample(root: Path):
    sample = RENDERER.write_sample_report_package(root / "sample")
    result = RENDERER.build_multi_format_report(
        report_dir=sample["report_dir"],
        format_spec_path=sample["format_spec_path"],
        output_dir=root / "formats",
    )
    return sample, result


def check_by_id(qa_report: dict, check_id: str) -> dict:
    return next(check for check in qa_report["checks"] if check["id"] == check_id)


def docx_xml(path: Path) -> str:
    with zipfile.ZipFile(path) as docx:
        return docx.read("word/document.xml").decode("utf-8")


def rewrite_docx_relationships_with_external_link(path: Path) -> None:
    with zipfile.ZipFile(path) as source:
        entries = {name: source.read(name) for name in source.namelist()}
    entries["word/_rels/document.xml.rels"] = b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rExt" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target="https://example.invalid/report" TargetMode="External"/>
</Relationships>
"""
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as target:
        for name, payload in entries.items():
            target.writestr(name, payload)


class MultiFormatReportRendererTest(unittest.TestCase):
    def test_sample_multi_format_package_is_valid_and_writes_files(self) -> None:
        with TemporaryDirectory() as directory:
            _sample, result = build_sample(Path(directory))

            self.assertTrue(result.qa_report["valid"])
            self.assertEqual(result.qa_report["readiness_status"], "ready")
            for path in [
                result.html_path,
                result.pdf_path,
                result.docx_path,
                result.targets_path,
                result.asset_inventory_path,
                result.link_audit_path,
                result.qa_report_path,
                result.manifest_path,
            ]:
                self.assertTrue(path.is_file(), path)

    def test_html_target_embeds_svg_and_preserves_traceability(self) -> None:
        with TemporaryDirectory() as directory:
            _sample, result = build_sample(Path(directory))
            html = result.html_path.read_text(encoding="utf-8")

            self.assertIn('data-format-target="html"', html)
            self.assertIn("data:image/svg+xml;base64,", html)
            self.assertIn("guardrail_status.svg sha256", html)
            self.assertIn("trial-onboarding-quarto-report", html)
            self.assertNotIn('src="figures/guardrail_status.svg"', html)

    def test_pdf_target_is_valid_pdf_and_names_command_and_figure(self) -> None:
        with TemporaryDirectory() as directory:
            _sample, result = build_sample(Path(directory))
            payload = result.pdf_path.read_bytes()

            self.assertTrue(payload.startswith(b"%PDF-1.4"))
            self.assertTrue(payload.rstrip().endswith(b"%%EOF"))
            self.assertIn(b"quarto render report.qmd --to pdf", payload)
            self.assertIn(b"guardrail_status.svg", payload)

    def test_docx_target_is_ooxml_and_names_decision_command_and_figure(self) -> None:
        with TemporaryDirectory() as directory:
            _sample, result = build_sample(Path(directory))
            with zipfile.ZipFile(result.docx_path) as docx:
                names = set(docx.namelist())
            xml = docx_xml(result.docx_path)

            self.assertIn("[Content_Types].xml", names)
            self.assertIn("_rels/.rels", names)
            self.assertIn("word/document.xml", names)
            self.assertIn("Delivery report DOCX target", xml)
            self.assertIn("pause_rollout", xml)
            self.assertIn("quarto render report.qmd --to docx", xml)
            self.assertIn("guardrail_status.svg", xml)

    def test_manifest_records_quarto_commands_hashes_and_renderer_boundary(self) -> None:
        with TemporaryDirectory() as directory:
            _sample, result = build_sample(Path(directory))
            manifest = read_json(result.manifest_path)

            self.assertEqual(manifest["hash_algorithm"], "sha256")
            self.assertEqual(manifest["renderer_used"], "lesson_deterministic_multi_format_renderer")
            self.assertEqual(
                manifest["render_commands"],
                {
                    "html": "quarto render report.qmd --to html --execute-params params.yml",
                    "pdf": "quarto render report.qmd --to pdf --execute-params params.yml",
                    "docx": "quarto render report.qmd --to docx --execute-params params.yml",
                },
            )
            hashes = [
                item["sha256"]
                for section in ("inputs", "outputs")
                for item in manifest[section].values()
            ]
            self.assertTrue(all(len(value) == 64 for value in hashes))

    def test_link_audit_covers_upstream_sources(self) -> None:
        with TemporaryDirectory() as directory:
            sample, result = build_sample(Path(directory))
            source_rows = read_csv(sample["report_dir"] / "source_links.csv")
            audit_rows = read_csv(result.link_audit_path)

            self.assertEqual(len(audit_rows), len(source_rows))
            self.assertTrue(all(row["status"] == "ok" for row in audit_rows))
            self.assertTrue(all(len(row["actual_sha256"]) == 64 for row in audit_rows))

    def test_invalid_upstream_report_audit_blocks_formats(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            sample = RENDERER.write_sample_report_package(root / "sample")
            audit_path = sample["report_dir"] / "report_audit.json"
            audit = read_json(audit_path)
            audit["valid"] = False
            audit["summary"]["blocking_errors"] = ["source_report_was_tampered"]
            write_json(audit_path, audit)

            result = RENDERER.build_multi_format_report(
                report_dir=sample["report_dir"],
                format_spec_path=sample["format_spec_path"],
                output_dir=root / "formats",
            )

            self.assertFalse(result.qa_report["valid"])
            self.assertFalse(check_by_id(result.qa_report, "upstream_report_audit_is_valid")["valid"])

    def test_broken_source_link_blocks_formats(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            sample = RENDERER.write_sample_report_package(root / "sample")
            links_path = sample["report_dir"] / "source_links.csv"
            rows = read_csv(links_path)
            rows[0]["path"] = "missing_memo.md"
            write_csv(links_path, rows, ["source_id", "kind", "path", "sha256", "referenced_in_section"])

            result = RENDERER.build_multi_format_report(
                report_dir=sample["report_dir"],
                format_spec_path=sample["format_spec_path"],
                output_dir=root / "formats",
            )

            self.assertFalse(result.qa_report["valid"])
            link_check = check_by_id(result.qa_report, "source_links_resolve_with_expected_hashes")
            self.assertFalse(link_check["valid"])
            self.assertIn(rows[0]["source_id"], link_check["observed"])

    def test_missing_docx_required_target_blocks_formats(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            sample = RENDERER.write_sample_report_package(root / "sample")
            spec = read_json(sample["format_spec_path"])
            spec["required_targets"] = ["html", "pdf"]
            spec["targets"].pop("docx")
            write_json(sample["format_spec_path"], spec)

            result = RENDERER.build_multi_format_report(
                report_dir=sample["report_dir"],
                format_spec_path=sample["format_spec_path"],
                output_dir=root / "formats",
            )

            self.assertFalse(result.qa_report["valid"])
            target_check = check_by_id(result.qa_report, "format_targets_cover_html_pdf_docx")
            self.assertFalse(target_check["valid"])
            self.assertEqual(target_check["observed"]["missing_required"], ["docx"])

    def test_unsupported_format_target_blocks_formats(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            sample = RENDERER.write_sample_report_package(root / "sample")
            spec = read_json(sample["format_spec_path"])
            spec["required_targets"].append("pptx")
            spec["targets"]["pptx"] = {"output": "report.pptx", "render_command": "quarto render report.qmd --to pptx"}
            write_json(sample["format_spec_path"], spec)

            result = RENDERER.build_multi_format_report(
                report_dir=sample["report_dir"],
                format_spec_path=sample["format_spec_path"],
                output_dir=root / "formats",
            )

            self.assertFalse(result.qa_report["valid"])
            self.assertIn("pptx", check_by_id(result.qa_report, "format_targets_cover_html_pdf_docx")["observed"]["unsupported"])

    def test_nonembedded_html_resource_blocks_audit_after_tamper(self) -> None:
        with TemporaryDirectory() as directory:
            sample, result = build_sample(Path(directory))
            html = result.html_path.read_text(encoding="utf-8")
            html = re_sub_data_uri(html, 'figures/guardrail_status.svg')
            result.html_path.write_text(html, encoding="utf-8")
            manifest = read_json(result.manifest_path)

            audit = RENDERER.audit_format_package(
                report_dir=sample["report_dir"],
                output_dir=result.output_dir,
                format_spec=read_json(sample["format_spec_path"]),
                output_entries=manifest["outputs"],
            )

            self.assertFalse(audit["valid"])
            self.assertFalse(check_by_id(audit, "html_output_embeds_local_figure_resources")["valid"])

    def test_docx_external_relationship_blocks_audit_after_tamper(self) -> None:
        with TemporaryDirectory() as directory:
            sample, result = build_sample(Path(directory))
            rewrite_docx_relationships_with_external_link(result.docx_path)
            manifest = read_json(result.manifest_path)

            audit = RENDERER.audit_format_package(
                report_dir=sample["report_dir"],
                output_dir=result.output_dir,
                format_spec=read_json(sample["format_spec_path"]),
                output_entries=manifest["outputs"],
            )

            self.assertFalse(audit["valid"])
            self.assertFalse(check_by_id(audit, "docx_output_is_valid_ooxml_package")["valid"])

    def test_interactive_content_blocks_static_targets(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            sample = RENDERER.write_sample_report_package(root / "sample")
            qmd_path = sample["report_dir"] / "report.qmd"
            qmd_path.write_text(qmd_path.read_text(encoding="utf-8") + "\n<script>plotly()</script>\n", encoding="utf-8")

            result = RENDERER.build_multi_format_report(
                report_dir=sample["report_dir"],
                format_spec_path=sample["format_spec_path"],
                output_dir=root / "formats",
            )

            self.assertFalse(result.qa_report["valid"])
            self.assertIn("plotly", check_by_id(result.qa_report, "static_targets_have_no_interactive_only_content")["observed"])

    def test_layout_warnings_are_non_blocking(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            sample = RENDERER.write_sample_report_package(root / "sample")
            spec = read_json(sample["format_spec_path"])
            spec["format_limits"]["max_table_columns_for_pdf"] = 4
            write_json(sample["format_spec_path"], spec)

            result = RENDERER.build_multi_format_report(
                report_dir=sample["report_dir"],
                format_spec_path=sample["format_spec_path"],
                output_dir=root / "formats",
            )

            self.assertTrue(result.qa_report["valid"])
            self.assertEqual(result.qa_report["readiness_status"], "ready_with_warnings")
            self.assertIn("layout_sensitive_warnings_are_recorded", result.qa_report["summary"]["warnings"])

    def test_rebuild_check_detects_changed_input_and_outputs(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            sample, first = build_sample(root)
            html_path = sample["report_dir"] / "report.html"
            html_path.write_text(
                html_path.read_text(encoding="utf-8").replace("pause_rollout", "continue_rollout"),
                encoding="utf-8",
            )

            second = RENDERER.build_multi_format_report(
                report_dir=sample["report_dir"],
                format_spec_path=sample["format_spec_path"],
                output_dir=root / "formats-second",
                previous_manifest_path=first.manifest_path,
            )
            manifest = read_json(second.manifest_path)

            self.assertTrue(manifest["rebuild_check"]["valid"])
            self.assertIn("source_report_html", manifest["rebuild_check"]["changed_inputs"])
            self.assertEqual(
                set(manifest["rebuild_check"]["changed_outputs"]),
                {"html_report", "pdf_report", "docx_report"},
            )

    def test_rebuild_check_flags_unexpected_output_change_without_input_change(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            sample, first = build_sample(root)
            stale_manifest = read_json(first.manifest_path)
            stale_manifest["outputs"]["html_report"]["sha256"] = "0" * 64
            stale_path = root / "stale_format_manifest.json"
            write_json(stale_path, stale_manifest)

            second = RENDERER.build_multi_format_report(
                report_dir=sample["report_dir"],
                format_spec_path=sample["format_spec_path"],
                output_dir=root / "formats-second",
                previous_manifest_path=stale_path,
            )

            self.assertFalse(second.qa_report["valid"])
            rebuild_check = check_by_id(second.qa_report, "format_rebuild_check_is_consistent")
            self.assertFalse(rebuild_check["valid"])
            self.assertIn("html_report", rebuild_check["observed"]["unexpected_output_changes"])

    def test_cli_write_example_builds_multi_format_package(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            proc = subprocess.run(
                [
                    sys.executable,
                    str(ARTIFACT),
                    "--write-example",
                    str(root / "example"),
                    "--output-dir",
                    str(root / "formats"),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertTrue(payload["valid"])
            self.assertTrue((root / "formats" / "report.pdf").is_file())
            self.assertTrue((root / "formats" / "report.docx").is_file())

    def test_cli_fail_on_invalid_returns_two(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            sample = RENDERER.write_sample_report_package(root / "sample")
            audit_path = sample["report_dir"] / "report_audit.json"
            audit = read_json(audit_path)
            audit["valid"] = False
            audit["summary"]["blocking_errors"] = ["manual_blocker"]
            write_json(audit_path, audit)

            proc = subprocess.run(
                [
                    sys.executable,
                    str(ARTIFACT),
                    "--report-dir",
                    str(sample["report_dir"]),
                    "--format-spec",
                    str(sample["format_spec_path"]),
                    "--output-dir",
                    str(root / "formats"),
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
            "report.html",
            "report.pdf",
            "report.docx",
            "format_targets.json",
            "asset_inventory.csv",
            "link_audit.csv",
            "format_qa_report.json",
            "format_manifest.json",
        ])


def re_sub_data_uri(html_text: str, replacement: str) -> str:
    return __import__("re").sub(r'data:image/svg\+xml;base64,[^"]+', replacement, html_text, count=1)


if __name__ == "__main__":
    unittest.main()
