# analytics-mart-dbt Release Report

Generated at: `2026-06-22T11:07:05Z`

## Decision Claims

- `customer_health_segment_supported`: models `model.analytics_mart_dbt.mart_customer_revenue_health`; tests `test.analytics_mart_dbt.assert_paid_revenue_reconciles`, `test.analytics_mart_dbt.warn_customers_without_subscription`.
- `daily_paid_revenue_reconciles`: models `model.analytics_mart_dbt.fct_order_revenue_daily`; tests `test.analytics_mart_dbt.assert_daily_revenue_reconciles`.
- `subscription_history_is_point_in_time`: models `model.analytics_mart_dbt.int_subscription_history`; tests `test.analytics_mart_dbt.assert_snapshot_does_not_version_noisy_updated_at`, `test.analytics_mart_dbt.assert_subscription_history_has_one_current_row`, `test.analytics_mart_dbt.assert_subscription_history_windows_do_not_overlap`.

## Quality Gates

- dbt tests: `pass` with 87 tests and 0 blocking failures.
- SQLFluff: `pass` with 0 violations across 22 files.
- Source freshness extract: `pass` across 8 sources.

## Source Freshness

- `source.analytics_mart_dbt.raw_app.currency_rates`: 4 rows, max `loaded_at` = `2026-05-07 00:10:00+03:00`.
- `source.analytics_mart_dbt.raw_app.events`: 5 rows, max `received_at` = `2026-05-06 15:00:02+03:00`.
- `source.analytics_mart_dbt.raw_app.order_items`: 5 rows, max `loaded_at` = `2026-05-07 19:22:00+03:00`.
- `source.analytics_mart_dbt.raw_app.orders`: 4 rows, max `updated_at` = `2026-05-07 19:21:00+03:00`.
- `source.analytics_mart_dbt.raw_app.refunds`: 1 rows, max `refunded_at` = `2026-05-06 09:00:00+03:00`.
- `source.analytics_mart_dbt.raw_app.subscriptions`: 4 rows, max `updated_at` = `2026-05-20 10:00:00+03:00`.
- `source.analytics_mart_dbt.raw_app.support_tickets`: 2 rows, max `created_at` = `2026-05-06 17:30:00+03:00`.
- `source.analytics_mart_dbt.raw_app.users`: 5 rows, max `updated_at` = `2026-05-20 10:00:00+03:00`.

## Handoff

The package is reproducible with `python ../analytics_mart_packager.py --project . --build-package`.
Checksum evidence is stored in `manifest.json`.
