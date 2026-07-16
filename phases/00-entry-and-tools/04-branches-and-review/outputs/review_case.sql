SELECT
    orders.order_date,
    SUM(orders.amount) AS revenue,
    COUNT(order_items.item_id) AS item_count
FROM orders
JOIN order_items
    ON orders.order_id = order_items.order_id
WHERE orders.status = 'paid'
GROUP BY orders.order_date;
