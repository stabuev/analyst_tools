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
DATA = ROOT.parent / "data" / "tiny"
ARTIFACT = ROOT / "outputs" / "sampling_frame_auditor.py"
SPEC_PATH = ROOT / "outputs" / "sampling_spec.json"
CODE = ROOT / "code" / "main.py"

MODULE_SPEC = importlib.util.spec_from_file_location("sampling_frame_auditor", ARTIFACT)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
AUDITOR = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(AUDITOR)


def check(report: dict, check_id: str) -> dict:
    return next(item for item in report["checks"] if item["id"] == check_id)


def run_tiny() -> dict:
    return AUDITOR.run(
        DATA / "population_users.csv",
        DATA / "sampling_frame.csv",
        DATA / "sample_observations.csv",
        DATA / "segment_reference.csv",
        SPEC_PATH,
    )


def copy_csv_with_mutation(source: Path, target: Path, mutate) -> None:
    rows = AUDITOR.read_csv(source)
    mutate(rows)
    with target.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


class SamplingFrameAuditorTest(unittest.TestCase):
    def test_tiny_audit_is_structurally_valid_but_warns_about_sampling_risks(self) -> None:
        report = run_tiny()
        self.assertTrue(report["valid"])
        self.assertEqual(report["summary"]["eligible_population_users"], 8)
        self.assertEqual(report["summary"]["frame_users"], 7)
        self.assertEqual(report["summary"]["sample_rows"], 6)
        self.assertEqual(report["summary"]["warning_count"], 3)
        coverage = check(report, "frame_segment_coverage")
        self.assertEqual(coverage["severity"], "warning")
        self.assertFalse(coverage["valid"])
        self.assertIn(
            {
                "dimension": "device_tier",
                "level": "low",
                "eligible_users": 2,
                "frame_users": 1,
                "coverage_rate": 0.5,
            },
            coverage["sample"],
        )

    def test_response_warning_is_segment_level_not_just_overall_rate(self) -> None:
        report = run_tiny()
        self.assertEqual(report["summary"]["overall_response_rate"], 0.833333)
        response = check(report, "sample_segment_response")
        self.assertFalse(response["valid"])
        self.assertIn(
            {
                "dimension": "platform",
                "level": "android",
                "sampled_users": 3,
                "respondents": 2,
                "response_rate": 0.666667,
            },
            response["sample"],
        )

    def test_code_example_exposes_missing_frame_user_before_estimation(self) -> None:
        result = subprocess.run(
            [sys.executable, CODE],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(result.stdout)
        self.assertEqual(payload["manual_missing_from_frame"], ["U006"])
        self.assertTrue(payload["audit_valid"])
        self.assertIn("frame_segment_coverage", payload["warnings"])

    def test_duplicate_sample_user_breaks_sampling_unit_grain(self) -> None:
        with TemporaryDirectory() as directory:
            sample_path = Path(directory) / "sample.csv"

            def duplicate_first(rows: list[dict[str, str]]) -> None:
                rows.append(dict(rows[0]))

            copy_csv_with_mutation(DATA / "sample_observations.csv", sample_path, duplicate_first)
            report = AUDITOR.run(
                DATA / "population_users.csv",
                DATA / "sampling_frame.csv",
                sample_path,
                DATA / "segment_reference.csv",
                SPEC_PATH,
            )
            self.assertFalse(report["valid"])
            self.assertEqual(check(report, "sample_key_unique")["sample"], ["U001"])

    def test_sample_user_must_exist_in_sampling_frame(self) -> None:
        with TemporaryDirectory() as directory:
            sample_path = Path(directory) / "sample.csv"

            def unknown_user(rows: list[dict[str, str]]) -> None:
                rows[0]["user_id"] = "U404"

            copy_csv_with_mutation(DATA / "sample_observations.csv", sample_path, unknown_user)
            report = AUDITOR.run(
                DATA / "population_users.csv",
                DATA / "sampling_frame.csv",
                sample_path,
                DATA / "segment_reference.csv",
                SPEC_PATH,
            )
            self.assertFalse(report["valid"])
            self.assertEqual(check(report, "sample_users_exist_in_frame")["sample"], ["U404"])

    def test_incomplete_observation_window_blocks_estimation(self) -> None:
        with TemporaryDirectory() as directory:
            sample_path = Path(directory) / "sample.csv"

            def incomplete_window(rows: list[dict[str, str]]) -> None:
                rows[0]["observed_days"] = "3"

            copy_csv_with_mutation(DATA / "sample_observations.csv", sample_path, incomplete_window)
            report = AUDITOR.run(
                DATA / "population_users.csv",
                DATA / "sampling_frame.csv",
                sample_path,
                DATA / "segment_reference.csv",
                SPEC_PATH,
            )
            self.assertFalse(report["valid"])
            self.assertEqual(
                check(report, "sample_complete_observation_windows")["sample"],
                [{"user_id": "U001", "observed_days": 3}],
            )

    def test_invalid_probability_and_weight_are_errors(self) -> None:
        with TemporaryDirectory() as directory:
            sample_path = Path(directory) / "sample.csv"

            def invalid_weight(rows: list[dict[str, str]]) -> None:
                rows[0]["inclusion_probability"] = "1.2"
                rows[1]["sample_weight"] = "99"

            copy_csv_with_mutation(DATA / "sample_observations.csv", sample_path, invalid_weight)
            report = AUDITOR.run(
                DATA / "population_users.csv",
                DATA / "sampling_frame.csv",
                sample_path,
                DATA / "segment_reference.csv",
                SPEC_PATH,
            )
            self.assertFalse(report["valid"])
            self.assertFalse(check(report, "sample_probabilities_in_domain")["valid"])
            self.assertFalse(check(report, "sample_weights_match_inclusion_probability")["valid"])

    def test_sampling_spec_must_declare_supported_unit(self) -> None:
        with TemporaryDirectory() as directory:
            spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
            spec["sampling_unit"] = "session_id"
            spec_path = Path(directory) / "sampling_spec.json"
            spec_path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
            report = AUDITOR.run(
                DATA / "population_users.csv",
                DATA / "sampling_frame.csv",
                DATA / "sample_observations.csv",
                DATA / "segment_reference.csv",
                spec_path,
            )
            self.assertFalse(report["valid"])
            self.assertEqual(check(report, "sampling_unit_supported")["observed"], "session_id")

    def test_cli_writes_report_and_returns_zero_for_warning_only_audit(self) -> None:
        with TemporaryDirectory() as directory:
            output_path = Path(directory) / "sampling-audit.json"
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--population",
                    DATA / "population_users.csv",
                    "--frame",
                    DATA / "sampling_frame.csv",
                    "--sample",
                    DATA / "sample_observations.csv",
                    "--segments",
                    DATA / "segment_reference.csv",
                    "--spec",
                    SPEC_PATH,
                    "--output",
                    output_path,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), json.loads(output_path.read_text()))

    def test_cli_returns_one_for_blocking_error(self) -> None:
        with TemporaryDirectory() as directory:
            sample_path = Path(directory) / "sample.csv"

            def duplicate_first(rows: list[dict[str, str]]) -> None:
                rows.append(dict(rows[0]))

            copy_csv_with_mutation(DATA / "sample_observations.csv", sample_path, duplicate_first)
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--population",
                    DATA / "population_users.csv",
                    "--frame",
                    DATA / "sampling_frame.csv",
                    "--sample",
                    sample_path,
                    "--segments",
                    DATA / "segment_reference.csv",
                    "--spec",
                    SPEC_PATH,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertFalse(json.loads(result.stdout)["valid"])


if __name__ == "__main__":
    unittest.main()
