-- Filtering a window result requires a later query stage.
-- Input contract is the same as in order_sequence_windows.sql.

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
numbered_orders AS (
    SELECT
        order_id,
        user_id,
        ordered_at,
        currency,
        amount,
        row_number() OVER (
            PARTITION BY user_id
            ORDER BY ordered_at DESC, order_id DESC
        ) AS latest_order_number
    FROM paid_orders
)
SELECT
    order_id,
    user_id,
    ordered_at,
    currency,
    amount
FROM numbered_orders
WHERE latest_order_number = 1
ORDER BY user_id;
