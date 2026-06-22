# Customer Revenue Health Mart Contract

## Scope

`analytics_mart_dbt` is a local dbt-duckdb release package for the customer revenue health mart.
It uses only fixture CSV extracts loaded into the `raw` DuckDB schema and does not require an external warehouse.

## Raw Boundary

Raw relations are declared only in `models/sources.yml` under `source('raw_app', ...)`.
Model SQL must depend on `source()` at the staging boundary and on `ref()` everywhere downstream.
Direct references such as `raw.raw_orders` or `raw_orders` inside model SQL are release blockers.

## Layers And Grain

- `staging`: source-shaped views with typed columns and normalized categorical values.
- `intermediate`: reusable join and aggregation logic. Ephemeral models are allowed only when the compiled SQL remains readable.
- `marts`: consumer tables and incremental facts.
- `snapshots`: type-2 subscription history with non-overlapping validity windows.

Key marts:

- `mart_customer_revenue_health`: one active, non-deleted user.
- `fct_order_revenue_daily`: one revenue date, incremental by `revenue_date`.
- `int_subscription_history`: one subscription version with point-in-time validity columns.

## Quality Gates

Blocking gates:

- `assert_paid_revenue_reconciles`
- `assert_daily_revenue_reconciles`
- `assert_no_many_to_many_revenue_join`
- `assert_subscription_history_has_one_current_row`
- `assert_subscription_history_windows_do_not_overlap`
- `assert_snapshot_does_not_version_noisy_updated_at`

Warning diagnostics:

- `warn_customers_without_subscription`

Warnings must remain visible in `quality/dbt-test-report.json`, but they do not block the package.

## Release Evidence

Each release includes:

- dbt artifacts in `target-artifacts/`
- quality reports in `quality/`
- decision traceability in `report.md`
- SHA-256 file checksums and tool versions in `manifest.json`

The package is complete only when `analytics_mart_packager.py --build-package` refreshes these files and validates the checksum manifest.
