# Snapshot project commands

Run from the lesson root:

```bash
dbt run --exclude int_subscription_history --project-dir outputs/snapshot_project --profiles-dir outputs/snapshot_project
dbt snapshot --select subscription_status_snapshot --project-dir outputs/snapshot_project --profiles-dir outputs/snapshot_project
dbt run --select int_subscription_history --project-dir outputs/snapshot_project --profiles-dir outputs/snapshot_project
dbt test --select "test_type:data" --project-dir outputs/snapshot_project --profiles-dir outputs/snapshot_project
python outputs/snapshot_history_auditor.py --project outputs/snapshot_project --data-contract ../data/contract.json --run-dbt
```

The committed report is static and deterministic:

```bash
python outputs/snapshot_history_auditor.py --output outputs/snapshot_history_audit_report.json
```
