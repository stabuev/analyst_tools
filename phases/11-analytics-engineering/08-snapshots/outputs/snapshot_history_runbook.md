# Snapshot history runbook

## Snapshot contract

- Snapshot: `subscription_status_snapshot`
- Source relation: `ref('stg_subscriptions')`
- `unique_key`: `subscription_id`
- Strategy: `check`
- `updated_at`: `updated_at`
- `check_cols`: `plan`, `status`, `started_at`, `ended_at`
- Noisy columns excluded from change detection: `updated_at`
- Current-row marker: `dbt_valid_to = 9999-12-31`

## Normal run order

Run snapshots after the raw subscription refresh and before any history-dependent marts:

```bash
dbt run --exclude int_subscription_history
dbt snapshot --select subscription_status_snapshot
dbt run --select int_subscription_history
dbt test --select int_subscription_history
dbt test --select assert_subscription_history_has_one_current_row assert_subscription_history_windows_do_not_overlap assert_snapshot_does_not_version_noisy_updated_at
```

The downstream history model exposes:

- `valid_from` from `dbt_valid_from`;
- `valid_to` from `dbt_valid_to`;
- `is_current` from the configured current-row sentinel;
- `dbt_scd_id` for unique physical snapshot versions.

## Schedule

Run `dbt snapshot` on the same cadence as the mutable source is expected to change, normally daily for this lesson. A snapshot table only records states observed at run time. If the source changes from active to cancelled and back to active between two snapshot runs, the intermediate cancelled state is not recoverable from dbt alone.

## Noisy updates

Do not use `check_cols: all` for this snapshot. `updated_at` is excluded from `check_cols` because it can move when the source row is reloaded without a business-state change. The column is still configured as `updated_at` so new versions use the source change timestamp instead of the snapshot execution timestamp.

## Hard delete policy

Hard deletes are not tracked in this lesson snapshot. If the upstream system can delete subscriptions, choose an explicit policy before production use:

- soft-delete in source and include the business deletion marker in `check_cols`;
- or configure a dbt hard delete policy and add tests for the delete meta-field.

## Migration checklist

1. Back up the existing snapshot table before changing `dbt_valid_to_current`, meta-field names, strategy or `check_cols`.
2. Run the changed snapshot in a staging target.
3. Confirm every `subscription_id` has exactly one current row.
4. Confirm closed validity windows end at the next version's `valid_from`.
5. Confirm noisy `updated_at`-only source changes do not create new versions.
