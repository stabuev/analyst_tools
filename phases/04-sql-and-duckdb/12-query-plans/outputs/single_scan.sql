-- Input relation: cohort_activity, one row per (cohort_month, period_index).
-- Output grain: exactly one summary row for the selected cohort.
-- Both filtered aggregates are computed from one input branch.
SELECT
    count(*) FILTER (
        WHERE cohort_month = $cohort_month::DATE
    ) AS cohort_period_rows,
    CAST(
        sum(active_users) FILTER (
            WHERE cohort_month = $cohort_month::DATE
        ) AS BIGINT
    ) AS active_user_period_sum
FROM cohort_activity;
