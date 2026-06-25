from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import duckdb
import ibis
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "performance_benchmark_packager.py"
SPEC = importlib.util.spec_from_file_location(
    "performance_benchmark_packager",
    ARTIFACT,
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
PACKAGER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PACKAGER)


class PerformanceBenchmarkPackagerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.directory = tempfile.TemporaryDirectory()
        cls.package_dir = Path(cls.directory.name) / "package"
        cls.report = PACKAGER.build_performance_benchmark_package(
            dataset_profile="tiny",
            rows=1_200,
            users=160,
            seed=42,
            repeat=3,
            warmup=1,
            row_group_size=256,
            output_dir=cls.package_dir,
        )
        cls.parquet_path = cls.package_dir / "data" / "orders.parquet"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.directory.cleanup()

    def test_generation_is_reproducible_and_has_unused_wide_columns(self) -> None:
        first = PACKAGER.generate_customer_revenue_rows(
            rows=512,
            users=64,
            seed=42,
        )
        second = PACKAGER.generate_customer_revenue_rows(
            rows=512,
            users=64,
            seed=42,
        )
        self.assertTrue(first.equals(second))
        self.assertIn("debug_payload", first.columns)
        self.assertIn("raw_event_json", first.columns)

    def test_invalid_generation_parameters_raise_lesson_error(self) -> None:
        with self.assertRaises(PACKAGER.PerformancePackageError):
            PACKAGER.generate_customer_revenue_rows(
                rows=128,
                users=64,
            )
        with self.assertRaises(PACKAGER.PerformancePackageError):
            PACKAGER.generate_customer_revenue_rows(
                rows=512,
                users=800,
            )

    def test_manual_tiny_reference_matches_reviewed_expected_output(self) -> None:
        observed = PACKAGER.run_manual_reference(pd.DataFrame(PACKAGER.TINY_ROWS))
        expected = PACKAGER.normalize_output(pd.DataFrame(PACKAGER.TINY_EXPECTED))
        comparison = PACKAGER.compare_output(
            expected,
            observed,
            engine="manual_reference",
        )
        self.assertTrue(comparison["passed"])
        self.assertEqual(comparison["row_count"], 3)

    def test_native_engines_match_manual_reference(self) -> None:
        frame = pd.read_parquet(self.parquet_path)
        expected = PACKAGER.run_manual_reference(frame)
        connection = duckdb.connect()
        connection.execute("SET TimeZone = 'UTC'")
        try:
            outputs = {
                "pandas": PACKAGER.run_pandas_pipeline(self.parquet_path),
                "duckdb_native": PACKAGER.run_duckdb_pipeline(
                    connection,
                    self.parquet_path,
                ),
                "polars_native": PACKAGER.run_polars_pipeline(self.parquet_path),
            }
        finally:
            connection.close()
        for engine, output in outputs.items():
            with self.subTest(engine=engine):
                self.assertTrue(
                    PACKAGER.compare_output(
                        expected,
                        output,
                        engine=engine,
                    )["passed"]
                )

    def test_ibis_portable_core_executes_on_duckdb_and_polars(self) -> None:
        expected = PACKAGER.run_pandas_pipeline(self.parquet_path)
        duckdb_backend = ibis.duckdb.connect()
        polars_backend = ibis.polars.connect()
        try:
            duckdb_expression = PACKAGER.build_ibis_pipeline(
                duckdb_backend.read_parquet(
                    self.parquet_path,
                    table_name="orders",
                )
            )
            polars_expression = PACKAGER.build_ibis_pipeline(
                polars_backend.read_parquet(
                    self.parquet_path,
                    table_name="orders",
                )
            )
            duckdb_output = PACKAGER.normalize_output(duckdb_backend.execute(duckdb_expression))
            polars_output = PACKAGER.normalize_output(
                polars_backend.execute(
                    polars_expression,
                    engine="streaming",
                )
            )
        finally:
            duckdb_backend.disconnect()
        self.assertTrue(
            PACKAGER.compare_output(
                expected,
                duckdb_output,
                engine="ibis_duckdb",
            )["passed"]
        )
        self.assertTrue(
            PACKAGER.compare_output(
                expected,
                polars_output,
                engine="ibis_polars",
            )["passed"]
        )

    def test_ibis_backends_compile_to_sql_and_lazyframe(self) -> None:
        plan_types = self.report["plans"]
        self.assertEqual(plan_types["ibis_duckdb"]["compiled_type"], "str")
        self.assertEqual(
            plan_types["ibis_polars"]["compiled_type"],
            "LazyFrame",
        )
        self.assertTrue(all(plan_types["ibis_duckdb"]["checks"].values()))
        self.assertTrue(all(plan_types["ibis_polars"]["checks"].values()))

    def test_window_rank_divergence_is_explicit(self) -> None:
        audit = self.report["portability"]
        self.assertTrue(audit["portable_core"]["portable_on_tested_backends"])
        self.assertTrue(audit["window_rank_probe"]["duckdb"]["supported"])
        self.assertFalse(audit["window_rank_probe"]["polars"]["supported"])
        self.assertEqual(
            audit["window_rank_probe"]["polars"]["error_type"],
            "OperationNotDefinedError",
        )
        self.assertTrue(audit["window_rank_probe"]["divergence_detected"])

    def test_equivalence_gate_rejects_mutated_output_before_timing(self) -> None:
        expected = PACKAGER.run_pandas_pipeline(self.parquet_path)
        broken = expected.copy()
        broken.loc[0, "net_revenue_cents"] += 1
        checks = [
            PACKAGER.compare_output(
                expected,
                broken,
                engine="broken",
            )
        ]
        with self.assertRaisesRegex(
            PACKAGER.PerformancePackageError,
            "equivalence gate failed before timing",
        ):
            PACKAGER.enforce_equivalence(checks)

    def test_measurement_uses_warmup_and_three_raw_runs(self) -> None:
        calls = {"count": 0}
        result = PACKAGER.normalize_output(pd.DataFrame(PACKAGER.TINY_EXPECTED))

        def runner() -> pd.DataFrame:
            calls["count"] += 1
            return result

        runs = PACKAGER.measure_runner(
            runner,
            engine="demo",
            repeat=3,
            warmup=2,
        )
        self.assertEqual(calls["count"], 5)
        self.assertEqual(len(runs), 3)
        self.assertTrue(all(run["result_checksum"] == runs[0]["result_checksum"] for run in runs))

    def test_report_has_five_engines_and_allowed_decision(self) -> None:
        summary = self.report["measurements"]["summary"]
        self.assertEqual(
            {row["engine"] for row in summary},
            set(PACKAGER.ENGINE_NAMES),
        )
        self.assertEqual(
            len(self.report["measurements"]["raw_runs"]),
            5 * 3,
        )
        decision = self.report["decision"]
        self.assertIn(
            decision["decision"],
            PACKAGER.ALLOWED_DECISIONS,
        )
        self.assertTrue(decision["evidence"]["measurement_ids"])
        self.assertTrue(decision["evidence"]["limitation_ids"])

    def test_native_plans_show_scan_filter_and_aggregate(self) -> None:
        plans = self.report["plans"]
        self.assertTrue(all(plans["duckdb_native"]["checks"].values()))
        self.assertTrue(all(plans["polars_native"]["checks"].values()))
        polars_plan = (self.package_dir / "profiles" / "polars-plan.txt").read_text(
            encoding="utf-8"
        )
        self.assertIn("PARQUET SCAN", polars_plan.upper())
        self.assertIn("SELECTION:", polars_plan)

    def test_package_contains_required_structure_and_pipeline_snapshots(self) -> None:
        required = [
            "benchmark-plan.json",
            "data/orders.parquet",
            "data-contract/sources.json",
            "data-contract/output-contract.json",
            "data-contract/dtype-policy.json",
            "data-layout/parquet-layout.json",
            "data-layout/partition-summary.json",
            "data-layout/row-group-summary.json",
            "pipelines/pandas_pipeline.py",
            "pipelines/duckdb_pipeline.sql",
            "pipelines/polars_pipeline.py",
            "pipelines/ibis_pipeline.py",
            "profiles/python-profile.json",
            "profiles/memory-profile.json",
            "profiles/duckdb-plan.json",
            "profiles/polars-plan.txt",
            "measurements/raw-runs.csv",
            "measurements/summary.csv",
            "measurements/environment.json",
            "equivalence/output-checks.json",
            "equivalence/reconciliation.csv",
            "reports/engine-decision.md",
            "reports/portability-audit.md",
            "reports/limitations.md",
            "manifest.json",
            "report.json",
        ]
        for relative in required:
            self.assertTrue(
                (self.package_dir / relative).is_file(),
                relative,
            )
        ibis_source = (self.package_dir / "pipelines" / "ibis_pipeline.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("def build_ibis_pipeline", ibis_source)
        self.assertIn("def build_ibis_rank_probe", ibis_source)

    def test_manifest_validation_detects_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            copied = Path(tmp) / "package"
            shutil.copytree(self.package_dir, copied)
            clean = PACKAGER.validate_manifest(copied)
            self.assertTrue(clean["valid"])
            target = copied / "reports" / "limitations.md"
            target.write_text(
                target.read_text(encoding="utf-8") + "\ntampered\n",
                encoding="utf-8",
            )
            broken = PACKAGER.validate_manifest(copied)
        self.assertFalse(broken["valid"])
        self.assertEqual(
            broken["mismatches"][0]["path"],
            "reports/limitations.md",
        )

    def test_large_profile_requires_explicit_opt_in(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            self.assertRaisesRegex(
                PACKAGER.PerformancePackageError,
                "large profile requires",
            ),
        ):
            PACKAGER.build_performance_benchmark_package(
                dataset_profile="large",
                repeat=3,
                output_dir=tmp,
            )

    def test_cli_writes_package_and_prints_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "package"
            result = subprocess.run(
                [
                    sys.executable,
                    str(ARTIFACT),
                    "--profile",
                    "tiny",
                    "--rows",
                    "512",
                    "--users",
                    "64",
                    "--repeat",
                    "3",
                    "--row-group-size",
                    "128",
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
            self.assertTrue(stdout_report["interpretation"]["safe_to_ship"])
            self.assertTrue(PACKAGER.validate_manifest(output_dir)["valid"])

    def test_cli_invalid_input_has_no_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [
                    sys.executable,
                    str(ARTIFACT),
                    "--profile",
                    "tiny",
                    "--rows",
                    "128",
                    "--repeat",
                    "3",
                    "--output-dir",
                    tmp,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 2)
        self.assertIn("performance package error", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
