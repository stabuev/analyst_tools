from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd
import pyarrow as pa

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "interoperability_audit.py"
SPEC = importlib.util.spec_from_file_location(
    "interoperability_audit",
    ARTIFACT,
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


def boundary(report: dict, boundary_id: str) -> dict:
    return next(item for item in report["boundaries"] if item["boundary_id"] == boundary_id)


class InteroperabilityAuditTest(unittest.TestCase):
    def test_canonical_table_is_reproducible_and_chunked(self) -> None:
        first = AUDIT.build_canonical_arrow_table(
            rows=24,
            chunk_size=8,
            seed=42,
        )
        second = AUDIT.build_canonical_arrow_table(
            rows=24,
            chunk_size=8,
            seed=42,
        )
        self.assertEqual(AUDIT.semantic_records(first), AUDIT.semantic_records(second))
        self.assertEqual(first.column_names, AUDIT.COLUMN_ORDER)
        self.assertEqual(first["gross_revenue_cents"].num_chunks, 3)

    def test_canonical_contract_has_decimal_timezone_and_ordered_category(self) -> None:
        table = AUDIT.build_canonical_arrow_table()
        self.assertTrue(pa.types.is_decimal(table.schema.field("net_revenue_rub").type))
        self.assertEqual(table.schema.field("event_at").type.tz, "UTC")
        plan_type = table.schema.field("plan_tier").type
        self.assertTrue(pa.types.is_dictionary(plan_type))
        self.assertTrue(plan_type.ordered)

    def test_invalid_generation_parameters_raise_lesson_error(self) -> None:
        with self.assertRaises(AUDIT.InteroperabilityAuditError):
            AUDIT.build_canonical_arrow_table(rows=4)
        with self.assertRaises(AUDIT.InteroperabilityAuditError):
            AUDIT.build_canonical_arrow_table(rows=24, chunk_size=1)

    def test_pandas_boundary_uses_arrow_dtypes_and_reuses_buffers(self) -> None:
        source = AUDIT.build_canonical_arrow_table()
        frame, storage, _roundtrip = AUDIT.pandas_boundary(source)
        audit = AUDIT.assess_boundary(
            boundary_id="test",
            source_engine="pyarrow",
            target_engine="pandas-arrow",
            api="test",
            source=source,
            target=storage,
        )
        self.assertTrue(all(isinstance(dtype, pd.ArrowDtype) for dtype in frame.dtypes))
        self.assertTrue(audit["checks"]["semantic_safe"])
        self.assertEqual(
            set(audit["buffer_reuse"]["columns_with_full_source_reuse"]),
            set(AUDIT.COLUMN_ORDER),
        )

    def test_pandas_roundtrip_preserves_types_but_not_schema_contract(self) -> None:
        source = AUDIT.build_canonical_arrow_table()
        _frame, _storage, roundtrip = AUDIT.pandas_boundary(source)
        audit = AUDIT.assess_boundary(
            boundary_id="test",
            source_engine="pandas-arrow",
            target_engine="pyarrow",
            api="test",
            source=source,
            target=roundtrip,
        )
        self.assertTrue(audit["checks"]["exact_arrow_types_match"])
        self.assertFalse(audit["checks"]["field_nullability_match"])
        self.assertFalse(audit["checks"]["schema_metadata_match"])
        self.assertTrue(audit["checks"]["semantic_safe"])

    def test_polars_preserves_semantics_and_reuses_primitive_buffers(self) -> None:
        source = AUDIT.build_canonical_arrow_table()
        _frame, roundtrip = AUDIT.polars_boundary(source)
        audit = AUDIT.assess_boundary(
            boundary_id="test",
            source_engine="pyarrow",
            target_engine="polars",
            api="test",
            source=source,
            target=roundtrip,
        )
        reused = set(audit["buffer_reuse"]["columns_with_any_reuse"])
        self.assertTrue(audit["checks"]["semantic_safe"])
        self.assertTrue(
            {
                "event_at",
                "gross_revenue_cents",
                "refund_amount_cents",
                "net_revenue_rub",
                "support_ticket_count",
            }.issubset(reused)
        )

    def test_polars_reencodes_strings_and_loses_ordered_category_metadata(self) -> None:
        source = AUDIT.build_canonical_arrow_table()
        _frame, roundtrip = AUDIT.polars_boundary(source)
        audit = AUDIT.assess_boundary(
            boundary_id="test",
            source_engine="pyarrow",
            target_engine="polars",
            api="test",
            source=source,
            target=roundtrip,
        )
        self.assertFalse(audit["checks"]["exact_arrow_types_match"])
        self.assertFalse(audit["checks"]["category_ordering_match"])
        self.assertEqual(
            audit["column_type_checks"]["plan_tier"]["target_family"],
            "categorical",
        )
        self.assertTrue(audit["checks"]["category_values_match"])

    def test_duckdb_utc_boundary_preserves_values_but_decodes_dictionary(self) -> None:
        source = AUDIT.build_canonical_arrow_table()
        target = AUDIT.duckdb_boundary(source, timezone_name="UTC")
        audit = AUDIT.assess_boundary(
            boundary_id="test",
            source_engine="pyarrow",
            target_engine="duckdb",
            api="test",
            source=source,
            target=target,
        )
        self.assertTrue(audit["checks"]["semantic_safe"])
        self.assertEqual(target.schema.field("event_at").type.tz, "UTC")
        self.assertEqual(
            audit["column_type_checks"]["plan_tier"]["target_family"],
            "string",
        )
        self.assertEqual(audit["buffer_reuse"]["columns_with_any_reuse"], [])

    def test_duckdb_timezone_session_changes_label_not_instant(self) -> None:
        source = AUDIT.build_canonical_arrow_table()
        target = AUDIT.duckdb_boundary(
            source,
            timezone_name="Europe/Moscow",
        )
        audit = AUDIT.assess_boundary(
            boundary_id="test",
            source_engine="pyarrow",
            target_engine="duckdb",
            api="test",
            source=source,
            target=target,
        )
        self.assertTrue(audit["checks"]["values_match"])
        self.assertFalse(audit["column_type_checks"]["event_at"]["exact_type_match"])
        self.assertEqual(
            target.schema.field("event_at").type.tz,
            "Europe/Moscow",
        )

    def test_matrix_contains_four_engine_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = AUDIT.build_interoperability_report(output_dir=tmp)
        self.assertEqual(
            {item["boundary_id"] for item in report["boundaries"]},
            {
                "arrow_to_pandas",
                "pandas_to_arrow",
                "arrow_to_polars",
                "arrow_to_duckdb",
            },
        )

    def test_decision_selects_one_columnar_engine_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = AUDIT.build_interoperability_report(output_dir=tmp)
        self.assertEqual(
            report["decision"]["selected_path"],
            "pyarrow -> polars -> pyarrow",
        )
        self.assertTrue(report["decision"]["timezone_counterexample_detected"])
        self.assertIn("polars", report["decision"]["known_drifts"])

    def test_report_is_safe_when_drift_is_classified(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = AUDIT.build_interoperability_report(output_dir=tmp)
        self.assertTrue(report["interpretation"]["safe_to_ship"])
        self.assertTrue(all(report["interpretation"]["checks"].values()))

    def test_cli_writes_matrix_arrow_files_decision_and_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "package"
            result = subprocess.run(
                [
                    sys.executable,
                    str(ARTIFACT),
                    "--rows",
                    "24",
                    "--chunk-size",
                    "8",
                    "--seed",
                    "42",
                    "--output-dir",
                    str(output_dir),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            stdout_report = json.loads(result.stdout)
            file_report = json.loads((output_dir / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(
                stdout_report["scenario"]["scenario_id"],
                file_report["scenario"]["scenario_id"],
            )
            for relative in [
                "canonical-input.arrow",
                "pandas-roundtrip.arrow",
                "polars-roundtrip.arrow",
                "duckdb-utc-output.arrow",
                "interoperability-matrix.csv",
                "conversion-audit.json",
                "engine-boundary-decision.md",
            ]:
                self.assertTrue((output_dir / relative).is_file(), relative)

    def test_cli_invalid_input_has_no_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [
                    sys.executable,
                    str(ARTIFACT),
                    "--rows",
                    "4",
                    "--output-dir",
                    tmp,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 2)
        self.assertIn("interoperability audit error", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
