-- Input contract:
-- orders has grain one row per unique non-NULL order_id;
-- status is one of cancelled, paid, pending or refunded for every order;
-- paid orders have non-NULL user_id, ordered_at TIMESTAMPTZ and currency;
-- amount is DECIMAL(18, 2) and may be NULL.
--
-- Output contract:
-- one row per paid order_id;
-- monetary aggregates never mix currencies;
-- every ordered aggregate has an explicit ROWS frame;
-- row and known-value counts make partial frames and NULL denominators visible;
-- AVG(DECIMAL) is delivered as unrounded DOUBLE; presentation rounding is a separate
-- explicit policy.

WITH paid_orders AS (
    SELECT
        order_id,
        user_id,
        ordered_at,
        currency,
        amount
    FROM orders
    WHERE status = 'paid'
),
framed_orders AS (
    SELECT
        order_id,
        user_id,
        ordered_at,
        currency,
        amount,
        sum(amount) OVER currency_partition AS currency_total_known_amount,
        sum(amount) OVER currency_running_rows AS currency_running_known_amount,
        count(*) OVER currency_running_rows AS currency_running_order_rows,
        count(amount) OVER currency_running_rows AS currency_running_known_amounts,
        count(*) OVER currency_recent_3_rows AS recent_3_order_rows,
        count(amount) OVER currency_recent_3_rows AS recent_3_known_amounts,
        avg(amount) OVER currency_recent_3_rows AS recent_3_known_amount_avg,
        count(*) OVER currency_prior_3_rows AS prior_3_order_rows,
        count(amount) OVER currency_prior_3_rows AS prior_3_known_amounts,
        avg(amount) OVER currency_prior_3_rows AS prior_3_known_amount_avg
    FROM paid_orders
    WINDOW
        currency_partition AS (
            PARTITION BY currency
        ),
        currency_running_rows AS (
            PARTITION BY currency
            ORDER BY ordered_at, order_id
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ),
        currency_recent_3_rows AS (
            PARTITION BY currency
            ORDER BY ordered_at, order_id
            ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
        ),
        currency_prior_3_rows AS (
            PARTITION BY currency
            ORDER BY ordered_at, order_id
            ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING
        )
)
SELECT
    order_id,
    user_id,
    ordered_at,
    currency,
    amount,
    currency_total_known_amount,
    currency_running_known_amount,
    currency_running_order_rows,
    currency_running_known_amounts,
    recent_3_order_rows,
    recent_3_known_amounts,
    recent_3_known_amount_avg,
    prior_3_order_rows,
    prior_3_known_amounts,
    prior_3_known_amount_avg
FROM framed_orders
ORDER BY currency, ordered_at, order_id;
