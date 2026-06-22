# Incremental project commands

Run from the lesson root:

```bash
dbt compile --project-dir outputs/incremental_project --profiles-dir outputs/incremental_project
dbt run --project-dir outputs/incremental_project --profiles-dir outputs/incremental_project
dbt test --select "test_type:data" --project-dir outputs/incremental_project --profiles-dir outputs/incremental_project
dbt run --full-refresh --select fct_order_revenue_daily --project-dir outputs/incremental_project --profiles-dir outputs/incremental_project
python outputs/incremental_model_auditor.py --project outputs/incremental_project --data-contract ../data/contract.json --run-dbt
```

The committed report is static and deterministic:

```bash
python outputs/incremental_model_auditor.py --output outputs/incremental_audit_report.json
```
