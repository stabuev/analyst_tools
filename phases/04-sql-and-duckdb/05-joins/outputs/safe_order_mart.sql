SELECT
    o.order_id,
    o.user_id,
    o.status,
    o.currency,
    o.amount,
    i.item_rows,
    i.known_item_amount_rows,
    i.item_total,
    i.item_amount_complete,
    CASE
        WHEN i.order_id IS NULL THEN 'no_items'
        ELSE 'matched'
    END AS item_match_state,
    CASE
        WHEN o.user_id IS NULL THEN 'missing_reference'
        WHEN u.user_id IS NULL THEN 'orphan_reference'
        ELSE 'matched'
    END AS user_match_state,
    CASE
        WHEN i.order_id IS NULL AND o.amount IS NULL THEN 'both_missing'
        WHEN i.order_id IS NULL THEN 'item_total_missing'
        WHEN NOT i.item_amount_complete THEN 'item_total_incomplete'
        WHEN o.amount IS NULL THEN 'order_amount_missing'
        WHEN o.amount = i.item_total THEN 'matches'
        ELSE 'differs'
    END AS amount_reconciliation_state
FROM orders AS o
LEFT JOIN item_totals AS i
    ON o.order_id = i.order_id
LEFT JOIN users AS u
    ON o.user_id = u.user_id
ORDER BY o.order_id;
