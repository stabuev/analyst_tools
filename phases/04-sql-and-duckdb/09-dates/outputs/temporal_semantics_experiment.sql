-- A calendar step and an elapsed duration answer different questions.
-- Europe/Berlin switches from UTC+01 to UTC+02 on 2026-03-29.

WITH local_noons AS (
    SELECT
        TIMESTAMP '2026-03-28 12:00:00' AS start_local_time,
        TIMESTAMP '2026-03-29 12:00:00' AS next_calendar_noon
),
instants AS (
    SELECT
        start_local_time,
        next_calendar_noon,
        start_local_time AT TIME ZONE 'Europe/Berlin' AS start_instant,
        next_calendar_noon AT TIME ZONE 'Europe/Berlin' AS end_instant
    FROM local_noons
)
SELECT
    start_local_time,
    next_calendar_noon,
    end_instant - start_instant AS elapsed_duration,
    (start_instant + INTERVAL '24 hours')
        AT TIME ZONE 'Europe/Berlin' AS after_24_hours_local_time,
    date_diff(
        'day',
        cast(start_local_time AS DATE),
        cast(next_calendar_noon AS DATE)
    ) AS calendar_day_boundaries,
    date_diff(
        'month',
        DATE '2026-01-31',
        DATE '2026-02-01'
    ) AS month_boundaries
FROM instants;
