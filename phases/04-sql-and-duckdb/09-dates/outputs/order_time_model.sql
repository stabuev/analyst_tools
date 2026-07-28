-- Input contract:
-- orders_source has grain one row per unique non-NULL order_id;
-- ordered_at is VARCHAR and may contain an ISO 8601 timestamp with an explicit
-- UTC offset, a missing value or a malformed value.
--
-- Output contract:
-- every source order remains one row;
-- ordered_at_instant is the parsed TIMESTAMPTZ and does not preserve the
-- source offset as metadata;
-- business calendar fields are derived only after the instant is displayed
-- in the explicit business_timezone;
-- missing and invalid source values remain distinguishable;
-- dates and timestamps stay typed rather than being formatted as strings.

WITH settings AS (
    SELECT 'Europe/Moscow'::VARCHAR AS business_timezone
),
classified_orders AS (
    SELECT
        order_id,
        ordered_at,
        ordered_at IS NULL OR trim(ordered_at) = '' AS source_is_missing,
        coalesce(
            regexp_matches(
                trim(ordered_at),
                '(Z|[+-][0-9]{2}:[0-9]{2})$',
                'i'
            ),
            false
        ) AS source_has_explicit_offset
    FROM orders_source
),
normalized_orders AS (
    SELECT
        order_id,
        ordered_at AS source_timestamp,
        CASE
            WHEN source_is_missing THEN 'missing'
            WHEN NOT source_has_explicit_offset THEN 'invalid'
            WHEN try_cast(ordered_at AS TIMESTAMPTZ) IS NULL THEN 'invalid'
            ELSE 'valid'
        END AS timestamp_status,
        CASE
            WHEN source_has_explicit_offset
                THEN try_cast(ordered_at AS TIMESTAMPTZ)
        END AS ordered_at_instant
    FROM classified_orders
),
localized_orders AS (
    SELECT
        normalized_orders.order_id,
        normalized_orders.source_timestamp,
        normalized_orders.timestamp_status,
        normalized_orders.ordered_at_instant,
        settings.business_timezone,
        timezone(
            settings.business_timezone,
            normalized_orders.ordered_at_instant
        ) AS business_local_time
    FROM normalized_orders
    CROSS JOIN settings
)
SELECT
    order_id,
    source_timestamp,
    timestamp_status,
    ordered_at_instant,
    business_timezone,
    business_local_time,
    cast(business_local_time AS DATE) AS business_date,
    cast(date_trunc('month', business_local_time) AS DATE) AS business_month
FROM localized_orders
ORDER BY order_id;
