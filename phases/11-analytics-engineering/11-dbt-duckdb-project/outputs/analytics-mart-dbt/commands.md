# analytics-mart-dbt commands

Run the project locally with the lesson fixture data loaded into DuckDB by the packager:

```bash
python ../analytics_mart_packager.py --project . --build-package
```

The packager runs the full local gate:

```bash
dbt parse
dbt run --exclude int_subscription_history
dbt snapshot --select subscription_status_snapshot
dbt run --select int_subscription_history
dbt test --select test_type:data
dbt docs generate
python -m sqlfluff lint models tests snapshots --format json
```

The committed `.sqlfluff` uses `dialect = duckdb` and `templater = dbt`, with `profile = analytics_mart_dbt`.
Generated artifacts are excluded by `.sqlfluffignore`: `target/`, `logs/`, `dbt_packages/`, and `*.duckdb`.

The package handoff files are:

- `target-artifacts/manifest.json`
- `target-artifacts/catalog.json`
- `target-artifacts/run_results.json`
- `target-artifacts/lineage-summary.json`
- `quality/dbt-test-report.json`
- `quality/source-freshness.json`
- `quality/sqlfluff-report.json`
- `quality/contract-audit.json`
- `report.md`
- `manifest.json`
