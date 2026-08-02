from collections import Counter

records = [
    {"order_id": "O1", "order_date": "2026-05-01", "currency": "RUB"},
    {"order_id": "O2", "order_date": "2026-05-02", "currency": "RUB"},
    {"order_id": "O3", "order_date": "2026-05-03", "currency": "EUR"},
    {"order_id": "O4", "order_date": "2026-05-04", "currency": "RUB"},
    {"order_id": "O5", "order_date": "2026-05-05", "currency": "RUB"},
]

for row in records:
    row["order_month"] = row["order_date"][:7]

candidates = {
    "month": ("order_month",),
    "month_currency": ("order_month", "currency"),
    "day_currency": ("order_date", "currency"),
    "order": ("order_id",),
}
workload = {
    "monthly_orders": {"order_month"},
    "currency_orders": {"currency"},
    "monthly_currency_orders": {"order_month", "currency"},
}

for candidate_name, partition_by in candidates.items():
    distribution = Counter(tuple(row[key] for key in partition_by) for row in records)
    print(f"\n{candidate_name}: partition_by={partition_by}")
    print("  rows per partition:", sorted(distribution.values()))
    for query_name, filter_columns in workload.items():
        partition_filters = filter_columns & set(partition_by)
        residual_filters = filter_columns - set(partition_by)
        print(
            f"  {query_name}: partition={sorted(partition_filters)}, "
            f"residual={sorted(residual_filters)}"
        )
