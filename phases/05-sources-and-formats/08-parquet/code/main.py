from decimal import Decimal

import pyarrow as pa

schema = pa.schema(
    [
        pa.field("order_id", pa.string(), nullable=False),
        pa.field("amount", pa.decimal128(12, 2), nullable=False),
        pa.field("comment", pa.string(), nullable=True),
    ]
)
table = pa.Table.from_pylist(
    [
        {"order_id": "O1", "amount": Decimal("1200.50"), "comment": None},
        {"order_id": "O2", "amount": Decimal("25.99"), "comment": "promo"},
    ],
    schema=schema,
)
print(table.schema)
print("Rows:", table.num_rows, "Null comments:", table.column("comment").null_count)
