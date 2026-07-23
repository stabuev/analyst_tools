-- Input relation:
--   orders(order_id, user_id, ordered_at, status, currency, amount)
-- Input grain:
--   one row per order, keyed by order_id
--
-- Output grain:
--   one paid RUB order
-- Output order:
--   amount DESC, then order_id ASC as a deterministic tie-breaker

SELECT
    order_id,
    user_id,
    currency,
    amount,
    round(amount * CAST(1.05 AS DECIMAL(4, 2)), 2) AS amount_with_fee,
    CASE
        WHEN amount >= CAST(1300 AS DECIMAL(18, 2)) THEN 'large'
        ELSE 'regular'
    END AS amount_band
FROM orders
WHERE status = 'paid'
  AND currency = 'RUB'
ORDER BY amount DESC, order_id ASC;
