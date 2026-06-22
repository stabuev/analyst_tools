# Materialization project commands

Run from the lesson root:

```bash
dbt parse --project-dir outputs/materialization_project --profiles-dir outputs/materialization_project
dbt compile --select "mart_customer_revenue_health" --project-dir outputs/materialization_project --profiles-dir outputs/materialization_project
dbt run --project-dir outputs/materialization_project --profiles-dir outputs/materialization_project
python outputs/materialization_reporter.py --project outputs/materialization_project --data-contract ../data/contract.json --run-dbt
```

The committed report is static and deterministic:

```bash
python outputs/materialization_reporter.py --output outputs/materialization_report.json
```
