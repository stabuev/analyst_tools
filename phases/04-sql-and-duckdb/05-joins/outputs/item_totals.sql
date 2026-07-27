SELECT
    order_id,
    count(*) AS item_rows,
    count(quantity * unit_price) AS known_item_amount_rows,
    sum(quantity * unit_price) AS item_total,
    count(*) = count(quantity * unit_price) AS item_amount_complete
FROM order_items
GROUP BY order_id
ORDER BY order_id;
