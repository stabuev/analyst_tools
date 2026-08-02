from __future__ import annotations

import copy
import importlib.util
import json
import shutil
import sqlite3
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from sqlalchemy import text
from sqlalchemy.exc import OperationalError

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "db_reader.py"
SQL = ROOT / "outputs" / "order_slice.sql"
DATA = ROOT.parent / "data"
DATABASE = DATA / "tiny" / "analytics.sqlite"
CONTRACT = DATA / "db_contract.json"
SPEC = importlib.util.spec_from_file_location("db_reader", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
READER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(READER)


class DatabaseReaderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = json.loads(CONTRACT.read_text(encoding="utf-8"))

    def read(
        self,
        database: Path = DATABASE,
        *,
        contract: Path = CONTRACT,
        sql: Path = SQL,
        **kwargs,
    ) -> dict:
        engine = READER.build_sqlite_read_only_engine(database)
        try:
            return READER.read_orders(
                engine,
                contract,
                sql_path=sql,
                database_source={"file_name": database.name},
                **kwargs,
            )
        finally:
            engine.dispose()

    def write_contract(self, directory: Path, contract: dict) -> Path:
        path = directory / "contract.json"
        path.write_text(json.dumps(contract, ensure_ascii=False), encoding="utf-8")
        return path

    def copy_database(self, directory: Path) -> Path:
        path = directory / "analytics.sqlite"
        shutil.copy2(DATABASE, path)
        return path

    def test_parameterized_slice_returns_expected_rows(self) -> None:
        result = self.read(min_amount=900, status="paid")
        self.assertTrue(result["summary"]["valid"])
        self.assertEqual(
            [row["order_id"] for row in result["result"]["rows"]],
            ["O2501", "O2502", "O2505"],
        )

    def test_result_order_is_deterministic(self) -> None:
        result = self.read()
        self.assertEqual(
            [row["order_id"] for row in result["result"]["rows"]],
            ["O2501", "O2502", "O2503", "O2504", "O2505"],
        )

    def test_filters_change_values_without_changing_sql_asset(self) -> None:
        paid = self.read(status="paid")
        cancelled = self.read(status="cancelled")
        self.assertEqual(paid["query"]["sha256"], cancelled["query"]["sha256"])
        self.assertEqual(paid["summary"]["row_count"], 3)
        self.assertEqual(cancelled["summary"]["row_count"], 1)

    def test_empty_result_keeps_actual_result_metadata(self) -> None:
        result = self.read(status="does-not-exist")
        self.assertTrue(result["summary"]["valid"])
        self.assertEqual(result["result"]["columns"], self.contract["result"]["columns"])
        self.assertEqual(result["result"]["rows"], [])

    def test_injection_payload_remains_a_bound_value(self) -> None:
        payload = "paid' OR 1=1 --"
        result = self.read(status=payload)
        self.assertTrue(result["summary"]["valid"])
        self.assertEqual(result["result"]["rows"], [])
        with sqlite3.connect(DATABASE) as connection:
            count = connection.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        self.assertEqual(count, 5)

    def test_value_equal_to_identifier_does_not_cause_false_alarm(self) -> None:
        result = self.read(status="orders")
        self.assertTrue(result["summary"]["valid"])
        self.assertEqual(result["result"]["rows"], [])

    def test_query_bind_names_match_contract_and_runtime_parameters(self) -> None:
        result = self.read(status="paid")
        self.assertEqual(result["query"]["bind_names"], ["fetch_limit", "min_amount", "status"])
        self.assertTrue(result["checks"]["query_bind_names_match"])
        self.assertNotIn("paid", result["query"]["compiled"])

    def test_safety_limit_detects_incomplete_result(self) -> None:
        result = self.read(max_rows=2)
        self.assertFalse(result["summary"]["valid"])
        self.assertFalse(result["checks"]["result_complete_within_limit"])
        self.assertEqual(result["summary"]["row_count"], 2)
        self.assertEqual(result["summary"]["rows_fetched_for_limit_check"], 3)

    def test_contract_grain_is_applied_instead_of_hardcoded(self) -> None:
        with TemporaryDirectory() as directory:
            contract = copy.deepcopy(self.contract)
            contract["result"]["grain"] = ["status"]
            path = self.write_contract(Path(directory), contract)
            result = self.read(contract=path)
        self.assertFalse(result["checks"]["result_grain_unique"])
        self.assertFalse(result["summary"]["valid"])

    def test_left_join_keeps_orphan_visible_and_fails_relationship_check(self) -> None:
        with TemporaryDirectory() as directory:
            database = self.copy_database(Path(directory))
            with sqlite3.connect(database) as connection:
                connection.execute(
                    "INSERT INTO orders VALUES (?, ?, ?, ?, ?)",
                    ("O9999", "UNKNOWN", "2026-05-06T00:00:00Z", 500.0, "paid"),
                )
            result = self.read(database)
        orphan = next(row for row in result["result"]["rows"] if row["order_id"] == "O9999")
        self.assertIsNone(orphan["segment"])
        self.assertFalse(result["checks"]["relationships_complete"])
        self.assertFalse(result["summary"]["valid"])

    def test_unknown_domain_value_in_selected_slice_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            database = self.copy_database(Path(directory))
            with sqlite3.connect(database) as connection:
                connection.execute("UPDATE orders SET status = 'mystery' WHERE order_id = 'O2503'")
            result = self.read(database)
        self.assertFalse(result["checks"]["result_domains_valid"])

    def test_wrong_result_contract_fails_even_for_empty_slice(self) -> None:
        with TemporaryDirectory() as directory:
            contract = copy.deepcopy(self.contract)
            contract["result"]["columns"] = ["imaginary"]
            contract["result"]["grain"] = ["imaginary"]
            contract["result"]["fields"] = {"imaginary": {"type": "string", "nullable": False}}
            contract["result"]["domains"] = {}
            contract["result"]["relationship_fields"] = []
            path = self.write_contract(Path(directory), contract)
            result = self.read(contract=path, status="does-not-exist")
        self.assertFalse(result["checks"]["result_columns_match"])

    def test_missing_required_source_column_is_reported_before_query(self) -> None:
        with TemporaryDirectory() as directory:
            contract = copy.deepcopy(self.contract)
            contract["source"]["tables"]["orders"]["required_columns"].append("currency")
            path = self.write_contract(Path(directory), contract)
            result = self.read(contract=path)
        self.assertFalse(result["checks"]["source_columns_present"])
        self.assertEqual(result["result"]["rows"], [])

    def test_primary_key_contract_is_checked(self) -> None:
        with TemporaryDirectory() as directory:
            contract = copy.deepcopy(self.contract)
            contract["source"]["tables"]["orders"]["primary_key"] = ["user_id"]
            path = self.write_contract(Path(directory), contract)
            result = self.read(contract=path)
        self.assertFalse(result["checks"]["source_primary_keys_match"])

    def test_source_nullability_contract_matches_fixture(self) -> None:
        result = self.read()
        self.assertTrue(result["checks"]["source_nullability_matches"])
        order_columns = {item["name"]: item for item in result["schema"]["orders"]["columns"]}
        self.assertFalse(order_columns["order_id"]["nullable"])

    def test_missing_table_is_a_quality_failure_not_a_traceback(self) -> None:
        with TemporaryDirectory() as directory:
            database = Path(directory) / "incomplete.sqlite"
            with sqlite3.connect(database) as connection:
                connection.execute("CREATE TABLE orders (order_id TEXT NOT NULL PRIMARY KEY)")
            result = self.read(database)
        self.assertFalse(result["checks"]["source_tables_present"])
        self.assertFalse(result["summary"]["valid"])

    def test_result_field_type_is_checked(self) -> None:
        with TemporaryDirectory() as directory:
            database = self.copy_database(Path(directory))
            with sqlite3.connect(database) as connection:
                connection.execute(
                    "UPDATE orders SET amount = 'not-a-number' WHERE order_id = 'O2501'"
                )
            result = self.read(database)
        self.assertFalse(result["checks"]["result_fields_valid"])

    def test_caller_owned_engine_is_reused_and_not_disposed(self) -> None:
        engine = READER.build_sqlite_read_only_engine(DATABASE)
        original_pool = engine.pool
        try:
            READER.read_orders(engine, CONTRACT)
            self.assertIs(engine.pool, original_pool)
            with engine.connect() as connection:
                self.assertEqual(connection.execute(text("SELECT 42")).scalar_one(), 42)
        finally:
            engine.dispose()

    def test_connection_is_returned_to_pool_after_read(self) -> None:
        engine = READER.build_sqlite_read_only_engine(DATABASE)
        try:
            READER.read_orders(engine, CONTRACT)
            self.assertEqual(engine.pool.checkedout(), 0)
        finally:
            engine.dispose()

    def test_sqlite_engine_rejects_writes(self) -> None:
        engine = READER.build_sqlite_read_only_engine(DATABASE)
        try:
            with engine.connect() as connection, self.assertRaises(OperationalError):
                connection.execute(text("INSERT INTO users VALUES ('U999', 'new')"))
        finally:
            engine.dispose()

    def test_missing_database_does_not_create_a_file(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "missing.sqlite"
            with self.assertRaisesRegex(READER.DatabaseReadError, "does not exist"):
                READER.build_sqlite_read_only_engine(path)
            self.assertFalse(path.exists())

    def test_provenance_has_versions_and_hashes_without_absolute_path(self) -> None:
        result = READER.read_sqlite_orders(DATABASE, CONTRACT)
        serialized = json.dumps(result, ensure_ascii=False)
        self.assertEqual(result["source"]["dialect"], "sqlite")
        self.assertEqual(result["source"]["driver"], "pysqlite")
        self.assertEqual(len(result["source"]["database"]["sha256"]), 64)
        self.assertEqual(len(result["query"]["sha256"]), 64)
        self.assertNotIn(str(DATA.resolve()), serialized)

    def test_contract_rejects_version_unknown_keys_and_duplicate_keys(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            wrong_version = copy.deepcopy(self.contract)
            wrong_version["version"] = "9.0.0"
            with self.assertRaisesRegex(READER.DatabaseReadError, "unsupported contract version"):
                READER.load_contract(self.write_contract(root, wrong_version))

            unknown = copy.deepcopy(self.contract)
            unknown["surprise"] = True
            with self.assertRaisesRegex(READER.DatabaseReadError, "unknown keys"):
                READER.load_contract(self.write_contract(root, unknown))

            duplicate = CONTRACT.read_text(encoding="utf-8").replace(
                '"version": "2.0.0",', '"version": "2.0.0",\n  "version": "2.0.0",'
            )
            duplicate_path = root / "duplicate.json"
            duplicate_path.write_text(duplicate, encoding="utf-8")
            with self.assertRaisesRegex(READER.DatabaseReadError, "duplicate JSON key"):
                READER.load_contract(duplicate_path)

    def test_invalid_runtime_parameters_are_controlled_errors(self) -> None:
        engine = READER.build_sqlite_read_only_engine(DATABASE)
        try:
            for kwargs in [
                {"max_rows": 0},
                {"min_amount": float("nan")},
                {"status": " "},
            ]:
                with self.subTest(kwargs=kwargs), self.assertRaises(READER.DatabaseReadError):
                    READER.read_orders(engine, CONTRACT, **kwargs)
        finally:
            engine.dispose()

    def test_sql_bind_drift_is_reported_without_execution(self) -> None:
        with TemporaryDirectory() as directory:
            sql = Path(directory) / "wrong.sql"
            sql.write_text(
                "SELECT order_id FROM orders WHERE amount >= :min_amount", encoding="utf-8"
            )
            result = self.read(sql=sql)
        self.assertFalse(result["checks"]["query_bind_names_match"])
        self.assertEqual(result["result"]["rows"], [])

    def test_empty_result_policy_can_require_at_least_one_row(self) -> None:
        with TemporaryDirectory() as directory:
            contract = copy.deepcopy(self.contract)
            contract["result"]["allow_empty"] = False
            path = self.write_contract(Path(directory), contract)
            result = self.read(contract=path, status="does-not-exist")
        self.assertFalse(result["checks"]["result_empty_allowed"])

    def test_publish_snapshot_is_self_contained_and_atomic(self) -> None:
        result = READER.read_sqlite_orders(DATABASE, CONTRACT)
        with TemporaryDirectory() as directory:
            output = Path(directory) / "orders_snapshot.json"
            READER.publish_snapshot(result, output)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual([path.name for path in Path(directory).iterdir()], [output.name])
        self.assertTrue(payload["summary"]["published"])
        self.assertIn("LEFT JOIN", payload["query"]["statement"])
        self.assertEqual(payload["contract"]["version"], "2.0.0")

    def test_invalid_result_cannot_replace_previous_snapshot(self) -> None:
        result = self.read(max_rows=2)
        with TemporaryDirectory() as directory:
            output = Path(directory) / "orders_snapshot.json"
            output.write_text("previous\n", encoding="utf-8")
            with self.assertRaisesRegex(READER.DatabaseReadError, "cannot be published"):
                READER.publish_snapshot(result, output)
            self.assertEqual(output.read_text(encoding="utf-8"), "previous\n")

    def test_cli_publishes_valid_snapshot(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "snapshot.json"
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--database",
                    DATABASE,
                    "--contract",
                    CONTRACT,
                    "--status",
                    "paid",
                    "--output",
                    output,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(output.is_file())
            self.assertTrue(json.loads(result.stdout)["summary"]["published"])

    def test_cli_incomplete_result_does_not_publish(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "snapshot.json"
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--database",
                    DATABASE,
                    "--contract",
                    CONTRACT,
                    "--max-rows",
                    "2",
                    "--output",
                    output,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
