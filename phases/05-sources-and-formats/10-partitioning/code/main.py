records = [
    {"date": "2026-05-01", "currency": "RUB"},
    {"date": "2026-05-02", "currency": "RUB"},
    {"date": "2026-05-03", "currency": "EUR"},
    {"date": "2026-05-04", "currency": "RUB"},
    {"date": "2026-05-05", "currency": "RUB"},
]

daily = {(row["date"], row["currency"]) for row in records}
monthly = {(row["date"][:7], row["currency"]) for row in records}
print("day/currency partitions:", len(daily))
print("month/currency partitions:", len(monthly))
print("EUR query needs partitions:", [value for value in monthly if value[1] == "EUR"])
