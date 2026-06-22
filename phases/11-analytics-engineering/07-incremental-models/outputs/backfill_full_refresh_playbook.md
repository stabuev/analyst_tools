# Incremental model backfill and full-refresh playbook

## Model contract

- Model: `fct_order_revenue_daily`
- Grain: one row per `revenue_date`
- `unique_key`: `revenue_date`
- Incremental strategy: `delete+insert`
- Late-arriving window: reprocess `max(revenue_date) - interval '2 days'`
- Schema change policy: `on_schema_change='fail'`

## Normal incremental run

Use the normal run after new raw data lands and the schema, grain and revenue logic are unchanged:

```bash
dbt run --select fct_order_revenue_daily
dbt test --select fct_order_revenue_daily
dbt test --select assert_daily_revenue_reconciles
```

Expected behavior:

- new dates are inserted;
- dates inside the late-arriving window are recalculated;
- existing rows with the same `unique_key` are deleted and inserted again;
- duplicate `revenue_date` rows must not survive data tests.

## Full refresh

Run full refresh when the historical result may be wrong outside the late-arriving window:

```bash
dbt run --full-refresh --select fct_order_revenue_daily
dbt test --select fct_order_revenue_daily
dbt test --select assert_daily_revenue_reconciles
```

Required full-refresh triggers:

- changed grain or `unique_key`;
- changed currency conversion or paid/refund logic;
- changed late-arriving data window;
- changed schema of published columns;
- warehouse migration or adapter strategy change;
- explicit backfill request for historical dates.

## Schema change response

The model uses `on_schema_change='fail'`. If a source or model change adds, drops or changes a published column, stop the incremental run, update the model contract and perform a reviewed full refresh. Do not rely on incremental schema sync to backfill historical values.

## Backfill checklist

1. Confirm the historical date range and the business reason for the backfill.
2. Check downstream users of `fct_order_revenue_daily`.
3. Run the full-refresh command in a staging target first.
4. Compare row count, duplicate count by `unique_key`, and paid revenue against the source-level reconciliation test.
5. Run the same full refresh in production and attach the dbt run artifact to the change record.
