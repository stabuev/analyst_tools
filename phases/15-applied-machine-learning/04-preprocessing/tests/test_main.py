from __future__ import annotations

import csv
import json
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

LESSON_ROOT = Path(__file__).resolve().parents[1]
PHASE_ROOT = LESSON_ROOT.parent
DATA_ROOT = PHASE_ROOT / "data" / "tiny"
ARTIFACT = LESSON_ROOT / "outputs" / "preprocessing_contract_checker.py"
CODE = LESSON_ROOT / "code" / "main.py"
GENERATOR = PHASE_ROOT / "data" / "generate_data.py"
sys.path.insert(0, str(LESSON_ROOT / "outputs"))

from preprocessing_contract_checker import run  # noqa: E402


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def check(report: dict, check_id: str) -> dict:
    return next(item for item in report["checks"] if item["id"] == check_id)


class PreprocessingContractCheckerTest(TestCase):
    def audit(self, root: Path = DATA_ROOT, **outputs: Path) -> dict:
        return run(
            spec_path=root / "problem_spec.json",
            contract_path=root / "preprocessing_contract.json",
            features_path=root / "ml_raw_features.csv",
            manifest_path=root / "ml_split_manifest.csv",
            **outputs,
        )

    def copy_profile(self, directory: Path) -> Path:
        target = directory / "tiny"
        shutil.copytree(DATA_ROOT, target)
        return target

    def test_valid_contract_builds_train_fitted_state_and_matrix(self) -> None:
        report = self.audit()

        self.assertTrue(report["valid"])
        self.assertEqual(report["summary"]["contract_id"], "trial-churn-preprocessing-v0")
        self.assertEqual(report["summary"]["fit_split"], "train")
        self.assertEqual(report["summary"]["fit_row_count"], 4)
        self.assertEqual(report["summary"]["transformed_row_count"], 12)
        self.assertEqual(report["summary"]["transformed_feature_count"], 23)
        self.assertEqual(report["summary"]["blocking_errors"], [])
        self.assertEqual(
            report["summary"]["warnings"],
            ["unknown_categories_bucketed", "tiny_preprocessing_sample_expected"],
        )
        self.assertEqual(report["summary"]["readiness_status"], "ready_for_pipeline_lesson")

    def test_numeric_statistics_are_fit_on_train_only(self) -> None:
        report = self.audit()
        state = report["preprocessing_state"]["numeric_features"]

        self.assertEqual(state["sessions_14d"]["fill_value"], 4.0)
        self.assertEqual(state["sessions_14d"]["mean"], 4.5)
        self.assertEqual(state["sessions_14d"]["scale"], 2.179449)
        self.assertEqual(state["active_days_14d"]["fill_value"], 2.5)
        self.assertEqual(state["days_since_signup"]["mean"], 7.0)
        self.assertEqual(state["days_since_signup"]["scale"], 2.236068)
        self.assertEqual(
            report["preprocessing_state"]["fit_snapshot_ids"],
            ["S001", "S002", "S003", "S004"],
        )

    def test_categorical_schema_has_train_categories_missing_and_unknown_buckets(self) -> None:
        report = self.audit()
        categorical = report["preprocessing_state"]["categorical_features"]

        self.assertEqual(
            categorical["acquisition_channel"]["observed_train_categories"],
            ["organic", "paid_search", "referral"],
        )
        self.assertEqual(
            categorical["acquisition_channel"]["encoded_categories"],
            ["organic", "paid_search", "referral", "__missing__", "__unknown__"],
        )
        self.assertIn("cat__acquisition_channel=__unknown__", report["summary"]["feature_names"])
        self.assertIn("cat__platform=web", report["summary"]["feature_names"])

    def test_unknown_validation_and_test_categories_are_visible_not_silent(self) -> None:
        report = self.audit()
        unknown = report["summary"]["unknown_category_events"]

        self.assertEqual(len(unknown), 2)
        self.assertEqual({item["value"] for item in unknown}, {"influencer", "partnership"})
        warning = check(report, "unknown_categories_bucketed")
        self.assertEqual(warning["severity"], "warning")
        self.assertFalse(warning["valid"])
        self.assertEqual(check(report, "unknown_categories_have_explicit_policy")["valid"], True)

    def test_matrix_output_uses_stable_numeric_feature_names(self) -> None:
        with TemporaryDirectory() as directory:
            matrix_path = Path(directory) / "matrix.csv"
            state_path = Path(directory) / "state.json"
            report = self.audit(matrix_output_path=matrix_path, state_output_path=state_path)
            rows = read_csv(matrix_path)
            state = read_json(state_path)

        s004 = next(row for row in rows if row["snapshot_id"] == "S004")
        s006 = next(row for row in rows if row["snapshot_id"] == "S006")
        self.assertTrue(report["valid"])
        self.assertEqual(float(s004["num__sessions_14d"]), -0.229416)
        self.assertEqual(float(s006["cat__acquisition_channel=__unknown__"]), 1.0)
        self.assertNotIn("cat__acquisition_channel=influencer", s006)
        self.assertEqual(len(state["feature_names"]), 23)

    def test_code_example_writes_report_matrix_and_state(self) -> None:
        report_path = LESSON_ROOT / "outputs" / "preprocessing_report.json"
        matrix_path = LESSON_ROOT / "outputs" / "preprocessed_feature_matrix.csv"
        state_path = LESSON_ROOT / "outputs" / "preprocessing_state.json"
        result = subprocess.run([sys.executable, CODE], check=True, capture_output=True, text=True)
        payload = json.loads(result.stdout)

        self.assertTrue(payload["audit_valid"])
        self.assertEqual(payload["fit_split"], "train")
        self.assertEqual(payload["transformed_feature_count"], 23)
        self.assertEqual(payload["unknown_category_events"], 2)
        self.assertEqual(
            read_json(report_path)["summary"]["readiness_status"], "ready_for_pipeline_lesson"
        )
        self.assertEqual(len(read_csv(matrix_path)), 12)
        self.assertEqual(read_json(state_path)["fit_split"], "train")

    def test_data_generator_check_rebuilds_committed_preprocessing_inputs(self) -> None:
        result = subprocess.run(
            [sys.executable, GENERATOR, "--check", "--output", DATA_ROOT],
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertIn("reproducible", result.stdout)

    def test_missing_feature_row_blocks_preprocessing(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            rows = [
                row
                for row in read_csv(root / "ml_raw_features.csv")
                if row["snapshot_id"] != "S006"
            ]
            write_csv(root / "ml_raw_features.csv", rows)

            report = self.audit(root)

        population = check(report, "raw_feature_schema_and_population_match_manifest")
        self.assertFalse(report["valid"])
        self.assertFalse(population["valid"])
        self.assertEqual(population["sample"][0]["reason"], "manifest rows missing features")
        self.assertIn("S006", population["sample"][0]["sample"])

    def test_duplicate_feature_row_blocks_preprocessing(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            rows = read_csv(root / "ml_raw_features.csv")
            rows.append(dict(rows[0]))
            write_csv(root / "ml_raw_features.csv", rows)

            report = self.audit(root)

        population = check(report, "raw_feature_schema_and_population_match_manifest")
        self.assertFalse(report["valid"])
        self.assertEqual(population["sample"][0]["reason"], "duplicate feature rows")

    def test_extra_ineligible_feature_row_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            rows = read_csv(root / "ml_raw_features.csv")
            extra = dict(rows[0])
            extra["snapshot_id"] = "S008"
            rows.append(extra)
            write_csv(root / "ml_raw_features.csv", rows)

            report = self.audit(root)

        population = check(report, "raw_feature_schema_and_population_match_manifest")
        self.assertFalse(report["valid"])
        self.assertEqual(population["sample"][0]["reason"], "feature rows outside split manifest")
        self.assertIn("S008", population["sample"][0]["sample"])

    def test_forbidden_target_column_in_raw_features_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            rows = read_csv(root / "ml_raw_features.csv")
            for row in rows:
                row["churned_14d"] = "false"
            write_csv(root / "ml_raw_features.csv", rows)

            report = self.audit(root)

        population = check(report, "raw_feature_schema_and_population_match_manifest")
        self.assertFalse(report["valid"])
        self.assertEqual(population["sample"][0]["reason"], "forbidden columns present")
        self.assertIn("churned_14d", population["sample"][0]["sample"])

    def test_fit_split_cannot_be_validation_or_all_data(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            contract = read_json(root / "preprocessing_contract.json")
            contract["fit_split"] = "validation"
            write_json(root / "preprocessing_contract.json", contract)

            report = self.audit(root)

        contract_check = check(report, "preprocessing_contract_is_explicit")
        self.assertFalse(report["valid"])
        self.assertFalse(contract_check["valid"])
        self.assertEqual(contract_check["sample"][0]["field"], "fit_split")

    def test_transform_splits_must_include_test(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            contract = read_json(root / "preprocessing_contract.json")
            contract["transform_splits"] = ["train", "validation"]
            write_json(root / "preprocessing_contract.json", contract)

            report = self.audit(root)

        contract_check = check(report, "preprocessing_contract_is_explicit")
        self.assertFalse(report["valid"])
        self.assertEqual(contract_check["sample"][0]["field"], "transform_splits")

    def test_numeric_missing_values_need_explicit_imputation(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            contract = read_json(root / "preprocessing_contract.json")
            del contract["numeric_features"][0]["impute"]
            write_json(root / "preprocessing_contract.json", contract)

            report = self.audit(root)

        contract_check = check(report, "preprocessing_contract_is_explicit")
        self.assertFalse(report["valid"])
        self.assertFalse(contract_check["valid"])
        self.assertEqual(
            contract_check["sample"][0]["field"], "numeric_features.sessions_14d.impute"
        )

    def test_unknown_category_policy_cannot_be_silent_ignore(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            contract = read_json(root / "preprocessing_contract.json")
            contract["categorical_features"][3]["handle_unknown"] = "ignore"
            write_json(root / "preprocessing_contract.json", contract)

            report = self.audit(root)

        contract_check = check(report, "preprocessing_contract_is_explicit")
        self.assertFalse(report["valid"])
        self.assertFalse(contract_check["valid"])
        self.assertEqual(
            contract_check["sample"][0]["field"],
            "categorical_features.acquisition_channel.handle_unknown",
        )

    def test_manifest_role_boundary_is_checked_before_fit(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            rows = read_csv(root / "ml_split_manifest.csv")
            for row in rows:
                if row["split"] == "test":
                    row["role"] = "fit_preprocessing_and_estimator"
                    break
            write_csv(root / "ml_split_manifest.csv", rows)

            report = self.audit(root)

        roles = check(report, "split_manifest_supports_preprocessing_roles")
        self.assertFalse(report["valid"])
        self.assertFalse(roles["valid"])
        self.assertEqual(roles["sample"][0]["field"], "role")

    def test_cli_writes_report_and_returns_nonzero_for_invalid_contract(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            contract = read_json(root / "preprocessing_contract.json")
            contract["fit_split"] = "test"
            write_json(root / "preprocessing_contract.json", contract)
            output = Path(directory) / "report.json"
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--spec",
                    root / "problem_spec.json",
                    "--contract",
                    root / "preprocessing_contract.json",
                    "--features",
                    root / "ml_raw_features.csv",
                    "--manifest",
                    root / "ml_split_manifest.csv",
                    "--output",
                    output,
                ],
                capture_output=True,
                text=True,
            )
            payload = read_json(output)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(payload["valid"])

    def test_cli_can_fail_on_warning_for_strict_gate(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                ARTIFACT,
                "--spec",
                DATA_ROOT / "problem_spec.json",
                "--contract",
                DATA_ROOT / "preprocessing_contract.json",
                "--features",
                DATA_ROOT / "ml_raw_features.csv",
                "--manifest",
                DATA_ROOT / "ml_split_manifest.csv",
                "--fail-on-warning",
            ],
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unknown_categories_bucketed", result.stdout)
