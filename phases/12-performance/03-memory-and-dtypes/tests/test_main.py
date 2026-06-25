from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "dtype_policy.py"
SPEC = importlib.util.spec_from_file_location("dtype_policy", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
DTYPE_POLICY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DTYPE_POLICY)


class DtypePolicyTest(unittest.TestCase):
    def test_generation_is_reproducible_and_has_expected_columns(self) -> None:
        first = DTYPE_POLICY.generate_revenue_extract(rows=50, seed=42)
        second = DTYPE_POLICY.generate_revenue_extract(rows=50, seed=42)
        self.assertTrue(first.equals(second))
        self.assertEqual(
            list(first.columns),
            [
                "order_id",
                "line_number",
                "user_id",
                "week_start",
                "platform",
                "acquisition_channel",
                "region",
                "plan",
                "paid_orders",
                "gross_revenue_cents",
                "refund_amount_cents",
                "net_revenue_cents",
                "active_subscription_days",
                "support_ticket_count",
                "first_paid_order_age_days",
                "activated_7d",
            ],
        )

    def test_policy_uses_categories_for_dimensions_not_identifiers(self) -> None:
        frame = DTYPE_POLICY.generate_revenue_extract(rows=1_000, seed=42)
        policy = {row.column: row for row in DTYPE_POLICY.build_dtype_policy(frame)}
        self.assertEqual(policy["platform"].target_dtype, "category")
        self.assertEqual(policy["plan"].target_dtype, "category")
        self.assertEqual(policy["order_id"].target_dtype, "string[pyarrow]")
        self.assertEqual(policy["order_id"].role, "identifier")

    def test_optimization_reduces_memory_and_preserves_semantics(self) -> None:
        frame = DTYPE_POLICY.generate_revenue_extract(rows=2_000, seed=42)
        optimized, report = DTYPE_POLICY.optimize_dataframe(frame, memory_budget_mb=2.0)
        self.assertLess(report["optimized"]["total_bytes"], report["baseline"]["total_bytes"])
        self.assertLess(report["optimized"]["reduction_ratio"], 0.5)
        self.assertTrue(all(check["passed"] for check in report["semantic_checks"]))
        self.assertTrue(report["interpretation"]["safe_to_ship"])
        self.assertEqual(str(optimized["platform"].dtype), "category")

    def test_nullable_fields_preserve_missing_semantics(self) -> None:
        frame = DTYPE_POLICY.generate_revenue_extract(rows=1_000, seed=7)
        optimized, report = DTYPE_POLICY.optimize_dataframe(frame, memory_budget_mb=2.0)
        self.assertEqual(
            int(frame["first_paid_order_age_days"].isna().sum()),
            int(optimized["first_paid_order_age_days"].isna().sum()),
        )
        self.assertEqual(
            int(frame["activated_7d"].isna().sum()),
            int(optimized["activated_7d"].isna().sum()),
        )
        self.assertEqual(str(optimized["first_paid_order_age_days"].dtype), "UInt16")
        self.assertEqual(str(optimized["activated_7d"].dtype), "boolean")
        check_ids = {row["id"] for row in report["semantic_checks"]}
        self.assertIn("activated_7d_missing_count_preserved", check_ids)

    def test_money_columns_stay_integer_and_totals_are_preserved(self) -> None:
        frame = DTYPE_POLICY.generate_revenue_extract(rows=1_500, seed=99)
        optimized, report = DTYPE_POLICY.optimize_dataframe(frame, memory_budget_mb=2.0)
        for column in DTYPE_POLICY.MONEY_COLUMNS:
            self.assertNotIn("float", str(optimized[column].dtype).lower())
            source_total = int(frame[column].sum())
            optimized_total = int(optimized[column].sum())
            self.assertEqual(source_total, optimized_total)
            check = next(row for row in report["semantic_checks"] if row["id"] == f"{column}_not_float")
            self.assertTrue(check["passed"])

    def test_unknown_category_is_rejected_before_casting(self) -> None:
        frame = DTYPE_POLICY.generate_revenue_extract(rows=100, seed=1)
        frame.loc[0, "platform"] = "console"
        with self.assertRaisesRegex(DTYPE_POLICY.DtypePolicyError, "unknown categories"):
            DTYPE_POLICY.optimize_dataframe(frame, memory_budget_mb=2.0)

    def test_fractional_integer_value_is_rejected(self) -> None:
        frame = DTYPE_POLICY.generate_revenue_extract(rows=100, seed=1)
        frame["support_ticket_count"] = frame["support_ticket_count"].astype("float64")
        frame.loc[0, "support_ticket_count"] = 1.5
        with self.assertRaisesRegex(DTYPE_POLICY.DtypePolicyError, "fractional values"):
            DTYPE_POLICY.optimize_dataframe(frame, memory_budget_mb=2.0)

    def test_negative_unsigned_value_is_rejected(self) -> None:
        frame = DTYPE_POLICY.generate_revenue_extract(rows=100, seed=1)
        frame.loc[0, "gross_revenue_cents"] = -1
        with self.assertRaisesRegex(DTYPE_POLICY.DtypePolicyError, "unsigned dtype"):
            DTYPE_POLICY.optimize_dataframe(frame, memory_budget_mb=2.0)

    def test_memory_budget_can_block_shipping(self) -> None:
        frame = DTYPE_POLICY.generate_revenue_extract(rows=1_000, seed=42)
        _optimized, report = DTYPE_POLICY.optimize_dataframe(frame, memory_budget_mb=0.000001)
        self.assertFalse(report["memory_budget"]["passed"])
        self.assertEqual(report["memory_budget"]["severity"], "block")
        self.assertFalse(report["interpretation"]["safe_to_ship"])

    def test_cli_writes_json_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "dtype-policy.json"
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--rows",
                    "1000",
                    "--seed",
                    "42",
                    "--memory-budget-mb",
                    "2",
                    "--output",
                    str(output),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            stdout_report = json.loads(result.stdout)
            file_report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(stdout_report["scenario"], file_report["scenario"])
            self.assertEqual(file_report["scenario"]["scenario_id"], "dtype-policy-memory-plan")

    def test_cli_invalid_input_has_no_traceback(self) -> None:
        result = subprocess.run(
            [sys.executable, ARTIFACT, "--rows", "0"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("dtype policy error", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
