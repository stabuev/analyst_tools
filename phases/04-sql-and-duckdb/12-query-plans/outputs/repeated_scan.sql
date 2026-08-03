-- Input relation: cohort_activity, one row per (cohort_month, period_index).
-- Output grain: exactly one summary row for the selected cohort.
-- The two independent scalar subqueries intentionally create two input branches.
SELECT
    (
        SELECT count(*)
        FROM cohort_activity
        WHERE cohort_month = $cohort_month::DATE
    ) AS cohort_period_rows,
    (
        SELECT sum(active_users)::BIGINT
        FROM cohort_activity
        WHERE cohort_month = $cohort_month::DATE
    ) AS active_user_period_sum;
