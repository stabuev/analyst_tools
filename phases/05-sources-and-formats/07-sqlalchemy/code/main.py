from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT.parent / "data" / "tiny" / "analytics.sqlite"
CONTRACT = ROOT.parent / "data" / "db_contract.json"
ARTIFACT = ROOT / "outputs" / "db_reader.py"

with sqlite3.connect(f"file:{DATABASE}?mode=ro", uri=True) as connection:
    cursor = connection.execute(
        "SELECT order_id, amount FROM orders WHERE amount >= ? ORDER BY order_id",
        (900,),
    )
    print("DB-API columns:", [column[0] for column in cursor.description])
    print("DB-API rows:", cursor.fetchall())

spec = importlib.util.spec_from_file_location("db_reader", ARTIFACT)
if spec is None or spec.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT.name}")
reader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reader)

engine = reader.build_sqlite_read_only_engine(DATABASE)
try:
    print(
        "SQLAlchemy boundary:",
        {
            "dialect": engine.dialect.name,
            "driver": engine.driver,
            "pool": type(engine.pool).__name__,
        },
    )
    result = reader.read_orders(
        engine,
        CONTRACT,
        min_amount=900,
        status="paid",
    )
    print("Verified rows:", result["result"]["rows"])
    print("Checks:", result["checks"])

    with engine.connect() as connection:
        print(
            "The caller can reuse its Engine:", connection.execute(text("SELECT 42")).scalar_one()
        )
finally:
    engine.dispose()
