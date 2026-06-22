# Documentation project commands

Run from the lesson root:

```bash
dbt run --exclude int_subscription_history --project-dir outputs/documentation_project --profiles-dir outputs/documentation_project
dbt snapshot --select subscription_status_snapshot --project-dir outputs/documentation_project --profiles-dir outputs/documentation_project
dbt run --select int_subscription_history --project-dir outputs/documentation_project --profiles-dir outputs/documentation_project
dbt test --select "test_type:data" --project-dir outputs/documentation_project --profiles-dir outputs/documentation_project
dbt docs generate --project-dir outputs/documentation_project --profiles-dir outputs/documentation_project
python outputs/documentation_lineage_auditor.py --project outputs/documentation_project --data-contract ../data/contract.json --run-dbt
```

`dbt docs generate` writes the documentation artifacts into the project target directory:
`target/manifest.json`, `target/catalog.json` and the static docs site files. The lesson
auditor reads the manifest and catalog instead of trusting descriptions by eye.

The committed report is static and deterministic:

```bash
python outputs/documentation_lineage_auditor.py --output outputs/documentation_lineage_report.json
```
