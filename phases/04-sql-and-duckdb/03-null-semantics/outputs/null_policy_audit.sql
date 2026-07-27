-- Expects a typed relation:
-- orders(order_id VARCHAR, amount DECIMAL(18, 2), ...)
--
-- The audit keeps every input row so that UNKNOWN remains observable before
-- a WHERE clause can remove it.

SELECT
    order_id,
    amount,
    amount > CAST(100 AS DECIMAL(18, 2)) AS amount_above_threshold,
    NOT (amount > CAST(100 AS DECIMAL(18, 2))) AS amount_not_above_threshold,
    amount IS NULL AS amount_is_missing,
    CASE
        WHEN amount IS NULL THEN 'missing'
        WHEN amount > CAST(100 AS DECIMAL(18, 2)) THEN 'above_threshold'
        ELSE 'at_or_below_threshold'
    END AS amount_state
FROM orders
ORDER BY order_id ASC;
