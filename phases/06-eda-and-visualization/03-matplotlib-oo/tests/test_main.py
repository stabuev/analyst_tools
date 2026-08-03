from __future__ import annotations

import copy
import importlib.util
import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PHASE = ROOT.parent
ARTIFACT = ROOT / "outputs" / "figure_factory.py"
AUDIT_ARTIFACT = PHASE / "02-data-audit" / "outputs" / "eda_audit.py"
DATA = PHASE / "data" / "tiny" / "user_journeys.csv"
CONTRACT = PHASE / "data" / "contract.json"
RELEASE_DATE = "2026-03-02"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


FACTORY = load_module("figure_factory", ARTIFACT)
AUDIT = load_module("eda_audit_for_figure_tests", AUDIT_ARTIFACT)


def audit_report() -> dict:
    return AUDIT.audit_frame(
        AUDIT.load_frame(DATA),
        AUDIT.load_contract(CONTRACT),
        source_sha256=AUDIT.sha256_file(DATA),
        contract_sha256=AUDIT.sha256_file(CONTRACT),
    )


def frame() -> pd.DataFrame:
    return FACTORY.prepare_analysis_frame(DATA, audit_report())


def write_report(path: Path, report: dict) -> None:
    path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")


def cli_command(artifact: Path, audit_path: Path, output: Path) -> list[object]:
    return [
        sys.executable,
        artifact,
        "--input",
        DATA,
        "--audit",
        audit_path,
        "--release-date",
        RELEASE_DATE,
        "--output-dir",
        output,
    ]


class FigureFactoryTest(unittest.TestCase):
    def test_audited_frame_has_one_row_per_complete_user(self) -> None:
        selected = frame()
        self.assertEqual(len(selected), 22)
        self.assertTrue(selected["user_id"].is_unique)
        self.assertTrue(selected["observed_days"].eq(7).all())

    def test_changed_source_is_rejected_by_checksum(self) -> None:
        with TemporaryDirectory() as directory:
            changed = Path(directory) / "changed.csv"
            changed.write_bytes(DATA.read_bytes() + b"\n")
            with self.assertRaisesRegex(FACTORY.FigureContractError, "checksum"):
                FACTORY.prepare_analysis_frame(changed, audit_report())

    def test_audit_source_and_selection_plan_must_agree(self) -> None:
        report = audit_report()
        report["source"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(FACTORY.FigureContractError, "selection plan"):
            FACTORY.prepare_analysis_frame(DATA, report)

    def test_blocked_readiness_is_rejected(self) -> None:
        report = audit_report()
        report["readiness"]["activation_7d"]["status"] = "blocked"
        report["readiness"]["activation_7d"]["blocker_ids"] = ["grain:key-conflict"]
        with self.assertRaisesRegex(FACTORY.FigureContractError, "blocked"):
            FACTORY.prepare_analysis_frame(DATA, report)

    def test_selection_plan_cannot_hide_conflicting_duplicate(self) -> None:
        with TemporaryDirectory() as directory:
            changed = Path(directory) / "conflict.csv"
            source = pd.read_csv(DATA, dtype="string", keep_default_na=False)
            duplicate = source[source.duplicated("user_id", keep=False)].index[-1]
            source.loc[duplicate, "activated_7d"] = "false"
            source.to_csv(changed, index=False, lineterminator="\n")
            report = audit_report()
            checksum = FACTORY.sha256_file(changed)
            report["source"]["sha256"] = checksum
            report["readiness"]["activation_7d"]["selection_plan"]["source_sha256"] = checksum
            with self.assertRaisesRegex(FACTORY.FigureContractError, "conflicting"):
                FACTORY.prepare_analysis_frame(changed, report)

    def test_empty_audited_selection_is_rejected(self) -> None:
        report = audit_report()
        plan = report["readiness"]["activation_7d"]["selection_plan"]
        plan["eligibility"]["value"] = 99
        with self.assertRaisesRegex(FACTORY.FigureContractError, "empty"):
            FACTORY.prepare_analysis_frame(DATA, report)

    def test_control_table_exposes_numerator_denominator_and_rate(self) -> None:
        selected = frame()
        table = FACTORY.activation_table(selected)
        self.assertEqual(list(table.columns), FACTORY.CONTROL_COLUMNS)
        self.assertEqual(int(table["eligible_users"].sum()), len(selected))
        self.assertTrue(table["activated_users"].le(table["eligible_users"]).all())
        expected = table["activated_users"] / table["eligible_users"]
        pd.testing.assert_series_equal(
            table["activation_rate"], expected.astype("Float64"), check_names=False
        )

    def test_figure_uses_two_explicit_axes_and_release_marker(self) -> None:
        table = FACTORY.activation_table(frame())
        figure, axes = FACTORY.build_figure(table, release_date=RELEASE_DATE)
        try:
            self.assertEqual(len(figure.axes), 2)
            self.assertEqual(len(axes), 2)
            self.assertEqual(axes[0].get_ylim(), (0.0, 1.0))
            self.assertEqual(axes[1].get_ylabel(), "Подходящие пользователи")
            self.assertEqual(len(axes[0].lines), 2)
            release_x = pd.Timestamp(axes[0].lines[1].get_xdata()[0])
            self.assertEqual(release_x, pd.Timestamp(RELEASE_DATE))
        finally:
            plt.close(figure)

    def test_invalid_release_date_is_rejected(self) -> None:
        with self.assertRaisesRegex(FACTORY.FigureContractError, "YYYY-MM-DD"):
            FACTORY.parse_release_date("02.03.2026")

    def test_rate_outside_domain_is_rejected(self) -> None:
        table = FACTORY.activation_table(frame())
        table.loc[0, "activation_rate"] = 1.1
        with self.assertRaisesRegex(FACTORY.FigureContractError, r"\[0, 1\]"):
            FACTORY.build_figure(table, release_date=RELEASE_DATE)

    def test_export_writes_control_table_images_and_manifest(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory)
            manifest = FACTORY.export_figure(
                frame(),
                output,
                release_date=RELEASE_DATE,
                audit_report=audit_report(),
            )
            self.assertEqual(
                set(manifest["files"]),
                {
                    "activation-overview-control.csv",
                    "activation-overview.png",
                    "activation-overview.svg",
                },
            )
            control = pd.read_csv(output / "activation-overview-control.csv")
            self.assertEqual(list(control.columns), FACTORY.CONTROL_COLUMNS)
            self.assertEqual(int(control["eligible_users"].sum()), 22)
            self.assertTrue((output / "manifest.json").is_file())

    def test_manifest_records_question_runtime_and_audit_evidence(self) -> None:
        with TemporaryDirectory() as directory:
            manifest = FACTORY.export_figure(
                frame(),
                Path(directory),
                release_date=RELEASE_DATE,
                audit_report=audit_report(),
            )
            self.assertEqual(manifest["question"]["release_date"], RELEASE_DATE)
            self.assertEqual(manifest["question"]["numerator"], "activated_users")
            self.assertEqual(manifest["question"]["denominator"], "eligible_users")
            self.assertEqual(manifest["figure"]["svg_hashsalt"], "analyst-tools-06-03")
            self.assertEqual(manifest["data"]["audit"]["readiness"], "ready_with_decisions")
            self.assertEqual(
                manifest["data"]["audit"]["report_sha256"],
                FACTORY.sha256_json(audit_report()),
            )
            self.assertEqual(manifest["runtime"]["matplotlib"], FACTORY.matplotlib.__version__)

    def test_manifest_checksums_match_exported_bytes(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory)
            manifest = FACTORY.export_figure(
                frame(),
                output,
                release_date=RELEASE_DATE,
                audit_report=audit_report(),
            )
            for filename, metadata in manifest["files"].items():
                self.assertEqual(FACTORY.sha256_file(output / filename), metadata["sha256"])

    def test_independent_cli_runs_are_byte_identical(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            audit_path = root / "audit.json"
            write_report(audit_path, audit_report())
            first = root / "first"
            second = root / "second"
            for output in (first, second):
                result = subprocess.run(
                    cli_command(ARTIFACT, audit_path, output),
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
            for filename in (
                "activation-overview-control.csv",
                "activation-overview.png",
                "activation-overview.svg",
                "manifest.json",
            ):
                self.assertEqual((first / filename).read_bytes(), (second / filename).read_bytes())

    def test_artifact_runs_after_copy_without_course_layout(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            copied = root / "figure_factory.py"
            shutil.copyfile(ARTIFACT, copied)
            audit_path = root / "audit.json"
            write_report(audit_path, audit_report())
            output = root / "output"
            result = subprocess.run(
                cli_command(copied, audit_path, output),
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((output / "activation-overview-control.csv").is_file())

    def test_cli_reports_contract_failure_without_traceback(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            report = copy.deepcopy(audit_report())
            report["readiness"]["activation_7d"]["status"] = "blocked"
            report["readiness"]["activation_7d"]["blocker_ids"] = ["schema:missing"]
            audit_path = root / "audit.json"
            write_report(audit_path, report)
            result = subprocess.run(
                cli_command(ARTIFACT, audit_path, root / "output"),
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("blocked", result.stderr)
            self.assertNotIn("Traceback", result.stderr)

    def test_export_closes_pyplot_figure(self) -> None:
        before = set(plt.get_fignums())
        with TemporaryDirectory() as directory:
            FACTORY.export_figure(
                frame(),
                Path(directory),
                release_date=RELEASE_DATE,
                audit_report=audit_report(),
            )
        self.assertEqual(set(plt.get_fignums()), before)


if __name__ == "__main__":
    unittest.main()
