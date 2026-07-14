from __future__ import annotations

import csv
import importlib.util
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "plotly_interactive_appendix.py"
CODE = ROOT / "code" / "main.py"
SPEC = importlib.util.spec_from_file_location("plotly_interactive_appendix", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
BUILDER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BUILDER
SPEC.loader.exec_module(BUILDER)


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
    sample = BUILDER.write_sample_delivery_package(root / "sample")
    result = BUILDER.build_interactive_appendix(
        delivery_dir=sample["delivery_dir"],
        interactive_spec_path=sample["interactive_spec_path"],
        output_dir=root / "interactive",
    )
    return sample, result


def check_by_id(audit: dict, check_id: str) -> dict:
    return next(check for check in audit["checks"] if check["id"] == check_id)


def source_table_path(delivery_dir: Path, source_id: str) -> Path:
    return BUILDER.resolve_source_tables(delivery_dir)["tables"][source_id]["path"]


class PlotlyInteractiveAppendixTest(unittest.TestCase):
    def test_sample_interactive_appendix_is_valid_and_writes_files(self) -> None:
        with TemporaryDirectory() as directory:
            _sample, result = build_sample(Path(directory))

            self.assertTrue(result.audit["valid"])
            self.assertEqual(result.audit["readiness_status"], "ready")
            for path in [
                result.html_path,
                result.figure_spec_path,
                result.fallback_path,
                result.source_links_path,
                result.audit_path,
                result.manifest_path,
                result.interactive_spec_path,
            ]:
                self.assertTrue(path.is_file(), path)

    def test_figure_spec_has_dropdown_filters_customdata_and_hover_context(self) -> None:
        with TemporaryDirectory() as directory:
            _sample, result = build_sample(Path(directory))
            figure = read_json(result.figure_spec_path)

            self.assertEqual(figure["lesson_metadata"]["allowed_filters"], ["all", "ok", "watch", "breached"])
            self.assertEqual(len(figure["data"]), 4)
            buttons = figure["layout"]["updatemenus"][0]["buttons"]
            self.assertEqual([button["label"] for button in buttons], ["All", "Ok", "Watch", "Breached"])
            self.assertTrue(all(trace.get("customdata") is not None for trace in figure["data"]))
            self.assertIn("support_ticket_rate_7d", json.dumps(figure["data"][0]["customdata"], ensure_ascii=False))
            self.assertTrue(
                all(
                    "metric_id=" in trace["hovertemplate"]
                    and "status=" in trace["hovertemplate"]
                    and "owner=" in trace["hovertemplate"]
                    and "evidence_count=" in trace["hovertemplate"]
                    for trace in figure["data"]
                )
            )

    def test_interactive_html_is_standalone_plotly_export_with_source_links(self) -> None:
        with TemporaryDirectory() as directory:
            _sample, result = build_sample(Path(directory))
            html = result.html_path.read_text(encoding="utf-8")

            self.assertIn("Plotly.newPlot", html)
            self.assertIn("plotly-interactive-appendix", html)
            self.assertIn('id="source-table-links"', html)
            self.assertIn("static-fallbacks/metric_status.svg", html)
            self.assertNotIn("dash-renderer", html.lower())
            script_sources = re.findall(r"<script[^>]+src=[\"']([^\"']+)[\"']", html, flags=re.IGNORECASE)
            self.assertFalse([source for source in script_sources if "cdn.plot.ly" in source.lower()])

    def test_static_fallback_svg_is_written_and_mentions_metrics(self) -> None:
        with TemporaryDirectory() as directory:
            _sample, result = build_sample(Path(directory))
            svg = result.fallback_path.read_text(encoding="utf-8")

            self.assertIn("<svg", svg)
            self.assertIn("support_ticket_rate_7d", svg)
            self.assertIn("subscription_cancel_rate_14d", svg)
            self.assertIn("threshold", svg)

    def test_source_table_links_cover_metric_and_evidence_with_hashes(self) -> None:
        with TemporaryDirectory() as directory:
            _sample, result = build_sample(Path(directory))
            rows = read_csv(result.source_links_path)

            self.assertEqual({row["source_id"] for row in rows}, {"metric_summary", "claim_evidence_matrix"})
            self.assertTrue(all(len(row["sha256"]) == 64 for row in rows))
            self.assertEqual({row["used_in"] for row in rows}, {"plotly_interactive_appendix"})

    def test_manifest_hashes_inputs_outputs_and_renderer_boundary(self) -> None:
        with TemporaryDirectory() as directory:
            _sample, result = build_sample(Path(directory))
            manifest = read_json(result.manifest_path)

            self.assertEqual(manifest["hash_algorithm"], "sha256")
            self.assertEqual(manifest["renderer_used"], "plotly_interactive_appendix_builder")
            self.assertIn("plotly_version", manifest)
            self.assertIn("source_metric_summary", manifest["inputs"])
            self.assertIn("interactive_html", manifest["outputs"])
            hashes = [
                item["sha256"]
                for section in ("inputs", "outputs")
                for item in manifest[section].values()
            ]
            self.assertTrue(all(len(value) == 64 for value in hashes))

    def test_invalid_upstream_format_qa_blocks_appendix(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            sample = BUILDER.write_sample_delivery_package(root / "sample")
            qa_path = sample["delivery_dir"] / "format_qa_report.json"
            qa = read_json(qa_path)
            qa["valid"] = False
            qa["summary"]["blocking_errors"] = ["format_bundle_was_tampered"]
            write_json(qa_path, qa)

            result = BUILDER.build_interactive_appendix(
                delivery_dir=sample["delivery_dir"],
                interactive_spec_path=sample["interactive_spec_path"],
                output_dir=root / "interactive",
            )

            self.assertFalse(result.audit["valid"])
            self.assertFalse(check_by_id(result.audit, "upstream_format_qa_is_valid")["valid"])

    def test_broken_upstream_link_audit_blocks_appendix(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            sample = BUILDER.write_sample_delivery_package(root / "sample")
            link_audit_path = sample["delivery_dir"] / "link_audit.csv"
            rows = read_csv(link_audit_path)
            rows[0]["status"] = "missing"
            write_csv(link_audit_path, rows, list(rows[0].keys()))

            result = BUILDER.build_interactive_appendix(
                delivery_dir=sample["delivery_dir"],
                interactive_spec_path=sample["interactive_spec_path"],
                output_dir=root / "interactive",
            )

            self.assertFalse(result.audit["valid"])
            link_check = check_by_id(result.audit, "upstream_link_audit_has_no_broken_sources")
            self.assertFalse(link_check["valid"])
            self.assertIn(rows[0]["source_id"], link_check["observed"])

    def test_missing_source_table_link_blocks_appendix(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            sample = BUILDER.write_sample_delivery_package(root / "sample")
            source_links_path = BUILDER.resolve_source_tables(sample["delivery_dir"])["source_links_path"]
            rows = [row for row in read_csv(source_links_path) if row["source_id"] != "metric_summary"]
            write_csv(source_links_path, rows, ["source_id", "kind", "path", "sha256", "referenced_in_section"])

            result = BUILDER.build_interactive_appendix(
                delivery_dir=sample["delivery_dir"],
                interactive_spec_path=sample["interactive_spec_path"],
                output_dir=root / "interactive",
            )

            self.assertFalse(result.audit["valid"])
            self.assertFalse(check_by_id(result.audit, "source_tables_resolve_from_delivery_manifest")["valid"])

    def test_missing_hover_field_blocks_appendix(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            sample = BUILDER.write_sample_delivery_package(root / "sample")
            spec = read_json(sample["interactive_spec_path"])
            spec["hover_fields"].remove("owner")
            write_json(sample["interactive_spec_path"], spec)

            result = BUILDER.build_interactive_appendix(
                delivery_dir=sample["delivery_dir"],
                interactive_spec_path=sample["interactive_spec_path"],
                output_dir=root / "interactive",
            )

            self.assertFalse(result.audit["valid"])
            self.assertFalse(check_by_id(result.audit, "interactive_spec_declares_filters_hover_sources_and_fallback")["valid"])

    def test_missing_filter_blocks_appendix(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            sample = BUILDER.write_sample_delivery_package(root / "sample")
            spec = read_json(sample["interactive_spec_path"])
            spec["allowed_filters"].remove("breached")
            write_json(sample["interactive_spec_path"], spec)

            result = BUILDER.build_interactive_appendix(
                delivery_dir=sample["delivery_dir"],
                interactive_spec_path=sample["interactive_spec_path"],
                output_dir=root / "interactive",
            )

            self.assertFalse(result.audit["valid"])
            spec_check = check_by_id(result.audit, "interactive_spec_declares_filters_hover_sources_and_fallback")
            self.assertFalse(spec_check["valid"])
            self.assertEqual(spec_check["observed"]["missing_filters"], ["breached"])

    def test_sensitive_source_column_is_redacted_from_public_outputs(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            sample = BUILDER.write_sample_delivery_package(root / "sample")
            metric_path = source_table_path(sample["delivery_dir"], "metric_summary")
            rows = read_csv(metric_path)
            for row in rows:
                row["user_email"] = "customer@example.com"
            write_csv(metric_path, rows, list(rows[0].keys()))

            result = BUILDER.build_interactive_appendix(
                delivery_dir=sample["delivery_dir"],
                interactive_spec_path=sample["interactive_spec_path"],
                output_dir=root / "interactive",
            )

            self.assertTrue(result.audit["valid"])
            self.assertEqual(result.audit["redaction_summary"]["redacted_fields"], ["user_email"])
            public_text = (
                result.html_path.read_text(encoding="utf-8")
                + result.figure_spec_path.read_text(encoding="utf-8")
                + result.fallback_path.read_text(encoding="utf-8")
                + result.source_links_path.read_text(encoding="utf-8")
            )
            self.assertNotIn("customer@example.com", public_text)
            self.assertNotIn("user_email", public_text)

    def test_sensitive_leak_after_tamper_is_blocked(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            sample = BUILDER.write_sample_delivery_package(root / "sample")
            metric_path = source_table_path(sample["delivery_dir"], "metric_summary")
            rows = read_csv(metric_path)
            for row in rows:
                row["user_email"] = "customer@example.com"
            write_csv(metric_path, rows, list(rows[0].keys()))
            result = BUILDER.build_interactive_appendix(
                delivery_dir=sample["delivery_dir"],
                interactive_spec_path=sample["interactive_spec_path"],
                output_dir=root / "interactive",
            )
            result.html_path.write_text(
                result.html_path.read_text(encoding="utf-8") + "\ncustomer@example.com\n",
                encoding="utf-8",
            )

            audit = BUILDER.audit_interactive_appendix(
                delivery_dir=sample["delivery_dir"],
                output_dir=result.output_dir,
                interactive_spec=read_json(result.interactive_spec_path),
                output_entries=read_json(result.manifest_path)["outputs"],
            )

            self.assertFalse(audit["valid"])
            self.assertFalse(check_by_id(audit, "sensitive_fields_are_redacted_from_public_outputs")["valid"])

    def test_missing_static_fallback_blocks_audit_after_tamper(self) -> None:
        with TemporaryDirectory() as directory:
            sample, result = build_sample(Path(directory))
            result.fallback_path.unlink()

            audit = BUILDER.audit_interactive_appendix(
                delivery_dir=sample["delivery_dir"],
                output_dir=result.output_dir,
                interactive_spec=read_json(result.interactive_spec_path),
                output_entries=read_json(result.manifest_path)["outputs"],
            )

            self.assertFalse(audit["valid"])
            self.assertFalse(check_by_id(audit, "static_fallback_exists_and_is_linked")["valid"])

    def test_rebuild_check_detects_changed_source_input_and_outputs(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            sample, first = build_sample(root)
            metric_path = source_table_path(sample["delivery_dir"], "metric_summary")
            rows = read_csv(metric_path)
            rows[0]["current"] = "0.027"
            write_csv(metric_path, rows, list(rows[0].keys()))

            second = BUILDER.build_interactive_appendix(
                delivery_dir=sample["delivery_dir"],
                interactive_spec_path=sample["interactive_spec_path"],
                output_dir=root / "interactive-after-change",
                previous_manifest_path=first.manifest_path,
            )

            rebuild = read_json(second.manifest_path)["rebuild_check"]
            self.assertTrue(rebuild["valid"])
            self.assertEqual(rebuild["changed_inputs"], ["source_metric_summary"])
            self.assertEqual(set(rebuild["changed_outputs"]), BUILDER.PRIMARY_OUTPUT_KEYS)

    def test_rebuild_check_flags_unexpected_output_change_without_input_change(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            sample, first = build_sample(root)
            stale_manifest = read_json(first.manifest_path)
            stale_manifest["outputs"]["interactive_html"]["sha256"] = "0" * 64
            stale_path = root / "stale_interaction_manifest.json"
            write_json(stale_path, stale_manifest)

            second = BUILDER.build_interactive_appendix(
                delivery_dir=sample["delivery_dir"],
                interactive_spec_path=sample["interactive_spec_path"],
                output_dir=root / "interactive-second",
                previous_manifest_path=stale_path,
            )

            rebuild = read_json(second.manifest_path)["rebuild_check"]
            self.assertFalse(rebuild["valid"])
            self.assertEqual(rebuild["changed_inputs"], [])
            self.assertEqual(rebuild["unexpected_output_changes"], ["interactive_html"])
            self.assertFalse(check_by_id(second.audit, "interactive_rebuild_check_is_consistent")["valid"])

    def test_cli_write_example_builds_interactive_bundle(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            process = subprocess.run(
                [
                    sys.executable,
                    str(ARTIFACT),
                    "--write-example",
                    str(root / "sample"),
                    "--output-dir",
                    str(root / "interactive"),
                    "--fail-on-invalid",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(process.returncode, 0, process.stderr)
            payload = json.loads(process.stdout)
            self.assertTrue(payload["valid"])
            self.assertEqual(payload["readiness_status"], "ready")

    def test_cli_fail_on_invalid_returns_two(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            sample = BUILDER.write_sample_delivery_package(root / "sample")
            spec = read_json(sample["interactive_spec_path"])
            spec["allowed_filters"].remove("breached")
            write_json(sample["interactive_spec_path"], spec)

            process = subprocess.run(
                [
                    sys.executable,
                    str(ARTIFACT),
                    "--delivery-dir",
                    str(sample["delivery_dir"]),
                    "--interactive-spec",
                    str(sample["interactive_spec_path"]),
                    "--output-dir",
                    str(root / "interactive"),
                    "--fail-on-invalid",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(process.returncode, 2, process.stderr)
            payload = json.loads(process.stdout)
            self.assertFalse(payload["valid"])
            self.assertIn("interactive_spec_declares_filters_hover_sources_and_fallback", payload["blocking_errors"])

    def test_code_example_runs_without_external_files(self) -> None:
        process = subprocess.run(
            [sys.executable, str(CODE)],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(process.returncode, 0, process.stderr)
        payload = json.loads(process.stdout)
        self.assertTrue(payload["valid"])
        self.assertEqual(payload["renderer_used"], "plotly_interactive_appendix_builder")
        self.assertIn("interactive_appendix.html", payload["files"])


if __name__ == "__main__":
    unittest.main()
