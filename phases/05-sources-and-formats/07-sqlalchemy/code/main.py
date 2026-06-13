import sqlite3
from pathlib import Path

from sqlalchemy import MetaData, Table, bindparam, create_engine, select

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT.parent / "data" / "tiny" / "analytics.sqlite"

with sqlite3.connect(DATABASE) as connection:
    manual = connection.execute(
        "SELECT order_id, amount FROM orders WHERE amount >= ? ORDER BY order_id",
        (900,),
    ).fetchall()
print("DB-API placeholders:", manual)

engine = create_engine(f"sqlite:///{DATABASE}")
metadata = MetaData()
orders = Table("orders", metadata, autoload_with=engine)
statement = select(orders.c.order_id, orders.c.amount).where(
    orders.c.amount >= bindparam("min_amount")
)
with engine.connect() as connection:
    rows = connection.execute(statement, {"min_amount": 900}).mappings().all()
print("SQLAlchemy Core:", [dict(row) for row in rows])
engine.dispose()
