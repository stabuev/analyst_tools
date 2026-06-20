from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "defect_factory.py"
BASELINE = ROOT.parent / "data" / "tiny"
SPEC = importlib.util.spec_from_file_location("defect_factory", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
FACTORY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FACTORY)


class DefectFactoryTest(unittest.TestCase):
    def test_matrix_covers_all_declared_failure_classes(self) -> None:
        report = FACTORY.matrix_report()
        classes = {scenario["class"] for scenario in report["scenarios"]}
        self.assertEqual(report["scenario_count"], 12)
        self.assertTrue(
            {
                "grain",
                "null_key",
                "relationship",
                "schema_drift",
                "type_drift",
                "domain",
                "reconciliation",
                "configuration",
                "regression",
                "freshness",
                "volume",
                "publication",
            }.issubset(classes)
        )

    def test_duplicate_scenario_adds_exactly_one_row(self) -> None:
        with TemporaryDirectory() as directory:
            report = FACTORY.materialize_defect(BASELINE, "duplicate_order_id", directory)
            rows, _ = FACTORY.read_csv(Path(directory) / "orders.csv")
        self.assertEqual(report["row_delta"], 1)
        self.assertEqual(len(rows), 11)
        self.assertEqual(rows[0], rows[-1])

    def test_column_drift_removes_only_currency(self) -> None:
        with TemporaryDirectory() as directory:
            FACTORY.materialize_defect(BASELINE, "missing_currency_column", directory)
            rows, fields = FACTORY.read_csv(Path(directory) / "orders.csv")
        self.assertNotIn("currency", fields)
        self.assertEqual(len(rows), 10)
        baseline_fields = set(FACTORY.read_csv(BASELINE / "orders.csv")[1])
        self.assertEqual(set(fields), baseline_fields - {"currency"})

    def test_unaffected_files_remain_byte_identical(self) -> None:
        with TemporaryDirectory() as directory:
            target = Path(directory)
            FACTORY.materialize_defect(BASELINE, "orphan_user", target)
            self.assertEqual(
                (target / "users.csv").read_bytes(), (BASELINE / "users.csv").read_bytes()
            )
            self.assertEqual(
                (target / "order_items.csv").read_bytes(),
                (BASELINE / "order_items.csv").read_bytes(),
            )

    def test_conceptual_scenario_is_not_silently_materialized(self) -> None:
        with (
            TemporaryDirectory() as directory,
            self.assertRaisesRegex(ValueError, "conceptual"),
        ):
            FACTORY.materialize_defect(BASELINE, "paid_rule_regression", directory)

    def test_cli_writes_manifest_for_minimal_reconciliation_defect(self) -> None:
        with TemporaryDirectory() as directory:
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--baseline-dir",
                    BASELINE,
                    "--scenario",
                    "item_total_mismatch",
                    "--output-dir",
                    directory,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            saved = json.loads((Path(directory) / "defect.json").read_text())
            self.assertEqual(payload, saved)
            self.assertEqual(payload["expected_gates"], ["stage_contract", "sql"])


if __name__ == "__main__":
    unittest.main()
