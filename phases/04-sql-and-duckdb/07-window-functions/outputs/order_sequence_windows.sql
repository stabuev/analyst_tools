-- Input contract:
-- orders has grain one row per unique non-NULL order_id;
-- status is one of cancelled, paid, pending or refunded for every order;
-- paid orders have non-NULL user_id, ordered_at TIMESTAMPTZ and currency;
-- amount is DECIMAL(18, 2) and may be NULL.
--
-- Output contract:
-- one row per paid order_id; window functions add columns without changing grain.
-- Unknown amount keeps both rank columns NULL: a technical NULLS LAST position is not
-- a business rank.

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
sequenced_orders AS (
    SELECT
        order_id,
        user_id,
        ordered_at,
        currency,
        amount,
        row_number() OVER user_chronology AS user_order_number,
        row_number() OVER user_reverse_chronology AS latest_order_number,
        CASE
            WHEN amount IS NOT NULL
            THEN rank() OVER currency_amount_peers
        END AS amount_rank_in_currency,
        CASE
            WHEN amount IS NOT NULL
            THEN dense_rank() OVER currency_amount_peers
        END AS amount_dense_rank_in_currency,
        lag(order_id) OVER user_chronology AS previous_order_id,
        lag(currency) OVER user_chronology AS previous_currency,
        lag(amount) OVER user_chronology AS previous_amount,
        lead(order_id) OVER user_chronology AS next_order_id
    FROM paid_orders
    WINDOW
        user_chronology AS (
            PARTITION BY user_id
            ORDER BY ordered_at, order_id
        ),
        user_reverse_chronology AS (
            PARTITION BY user_id
            ORDER BY ordered_at DESC, order_id DESC
        ),
        currency_amount_peers AS (
            PARTITION BY currency
            ORDER BY amount DESC NULLS LAST
        )
)
SELECT
    order_id,
    user_id,
    ordered_at,
    currency,
    amount,
    user_order_number,
    latest_order_number,
    amount_rank_in_currency,
    amount_dense_rank_in_currency,
    previous_order_id,
    previous_currency,
    previous_amount,
    next_order_id
FROM sequenced_orders
ORDER BY user_id, ordered_at, order_id;
