# Data test project commands

Run from the lesson root:

```bash
dbt run --project-dir outputs/data_test_project --profiles-dir outputs/data_test_project
dbt test --select "test_type:data" --project-dir outputs/data_test_project --profiles-dir outputs/data_test_project
dbt source freshness --project-dir outputs/data_test_project --profiles-dir outputs/data_test_project
python outputs/dbt_test_reporter.py --project outputs/data_test_project --data-contract ../data/contract.json --run-dbt
```

The committed report is static and deterministic:

```bash
python outputs/dbt_test_reporter.py --output outputs/dbt_test_report.json
```
