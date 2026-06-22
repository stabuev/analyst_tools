# Macro project commands

Run from the lesson root:

```bash
dbt compile --project-dir outputs/macro_project --profiles-dir outputs/macro_project
dbt run --project-dir outputs/macro_project --profiles-dir outputs/macro_project
dbt test --select "test_type:data" --project-dir outputs/macro_project --profiles-dir outputs/macro_project
python outputs/macro_review_auditor.py --project outputs/macro_project --data-contract ../data/contract.json --run-dbt
```

The committed report is static and deterministic:

```bash
python outputs/macro_review_auditor.py --output outputs/macro_review_report.json
```
