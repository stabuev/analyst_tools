-- Input contract:
-- users has grain one row per unique non-NULL user_id and contains
-- registered_at TIMESTAMPTZ;
-- events contains non-NULL event_id, user_id, occurred_at TIMESTAMPTZ and
-- event_name; repeated deliveries of one event_id must be exact copies;
-- every events.user_id must exist in users and an event cannot precede the
-- user's registration moment.
--
-- Output contract:
-- grain is one row per cohort_month and period_index;
-- cohort and activity months use the same explicit business timezone;
-- only the named activity events count;
-- one user contributes at most once to one activity month;
-- cohort_size is fixed for every period of one cohort;
-- the grid ends at last_complete_activity_month, so a missing activity row
-- inside the grid is an observed zero rather than an unobserved future period.

WITH settings AS (
    SELECT
        'Europe/Moscow'::VARCHAR AS business_timezone,
        DATE '2026-04-01' AS last_complete_activity_month
),
qualifying_event_names(event_name) AS (
    VALUES
        ('app_open'),
        ('order_paid'),
        ('trial_started')
),
cohort_members AS (
    SELECT
        users.user_id,
        CAST(
            date_trunc(
                'month',
                timezone(settings.business_timezone, users.registered_at)
            )
            AS DATE
        ) AS cohort_month
    FROM users
    CROSS JOIN settings
),
cohort_sizes AS (
    SELECT
        cohort_month,
        count(*) AS cohort_size
    FROM cohort_members
    CROSS JOIN settings
    WHERE cohort_month <= settings.last_complete_activity_month
    GROUP BY cohort_month
),
deduplicated_events AS (
    SELECT DISTINCT
        event_id,
        user_id,
        occurred_at,
        event_name
    FROM events
),
qualifying_activity AS (
    SELECT
        deduplicated_events.user_id,
        CAST(
            date_trunc(
                'month',
                timezone(settings.business_timezone, deduplicated_events.occurred_at)
            )
            AS DATE
        ) AS activity_month
    FROM deduplicated_events
    JOIN qualifying_event_names USING (event_name)
    CROSS JOIN settings
),
user_month_activity AS (
    SELECT DISTINCT
        cohort_members.user_id,
        cohort_members.cohort_month,
        qualifying_activity.activity_month
    FROM cohort_members
    JOIN qualifying_activity USING (user_id)
    CROSS JOIN settings
    WHERE qualifying_activity.activity_month >= cohort_members.cohort_month
      AND qualifying_activity.activity_month
            <= settings.last_complete_activity_month
),
cohort_period_grid AS (
    SELECT
        cohort_sizes.cohort_month,
        CAST(
            cohort_sizes.cohort_month
                + periods.period_index * INTERVAL '1 month'
            AS DATE
        ) AS activity_month,
        periods.period_index,
        cohort_sizes.cohort_size
    FROM cohort_sizes
    CROSS JOIN settings
    CROSS JOIN LATERAL range(
        0,
        date_diff(
            'month',
            cohort_sizes.cohort_month,
            settings.last_complete_activity_month
        ) + 1
    ) AS periods(period_index)
),
active_users AS (
    SELECT
        cohort_month,
        activity_month,
        count(*) AS active_users
    FROM user_month_activity
    GROUP BY cohort_month, activity_month
)
SELECT
    cohort_period_grid.cohort_month,
    cohort_period_grid.activity_month,
    cohort_period_grid.period_index,
    cohort_period_grid.cohort_size,
    coalesce(active_users.active_users, 0) AS active_users,
    round(
        coalesce(active_users.active_users, 0)::DOUBLE
            / cohort_period_grid.cohort_size,
        4
    ) AS activity_rate,
    settings.business_timezone,
    settings.last_complete_activity_month
FROM cohort_period_grid
LEFT JOIN active_users
  ON cohort_period_grid.cohort_month = active_users.cohort_month
 AND cohort_period_grid.activity_month = active_users.activity_month
CROSS JOIN settings
ORDER BY cohort_period_grid.cohort_month, cohort_period_grid.period_index;
