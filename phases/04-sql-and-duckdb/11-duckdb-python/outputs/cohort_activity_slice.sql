-- This is a reviewed SQL asset. Parameters supply values, not SQL structure.
--
-- Input contract:
-- cohort_activity is a registered pandas DataFrame with the output grain and
-- schema of lesson 04/10: one row per (cohort_month, period_index).
--
-- Output contract:
-- one named cohort only;
-- one row per period_index from period 0 through max_period, if observed;
-- deterministic order by period_index;
-- a compact result suitable for materialization as a pandas DataFrame.

SELECT
    cohort_month,
    activity_month,
    period_index::BIGINT AS period_index,
    cohort_size::BIGINT AS cohort_size,
    active_users::BIGINT AS active_users,
    activity_rate::DOUBLE AS activity_rate
FROM cohort_activity
WHERE cohort_month = $cohort_month::DATE
  AND period_index <= $max_period::BIGINT
ORDER BY period_index;
