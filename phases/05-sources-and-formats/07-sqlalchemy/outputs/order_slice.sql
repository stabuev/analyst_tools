SELECT
    orders.order_id,
    orders.user_id,
    orders.ordered_at,
    orders.amount,
    orders.status,
    users.segment
FROM orders
LEFT JOIN users
    ON orders.user_id = users.user_id
WHERE orders.amount >= :min_amount
  AND (:status IS NULL OR orders.status = :status)
ORDER BY orders.order_id
LIMIT :fetch_limit;
