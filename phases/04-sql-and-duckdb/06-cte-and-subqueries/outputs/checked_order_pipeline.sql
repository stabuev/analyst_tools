WITH
item_totals AS (
    -- population: заказы, у которых есть хотя бы одна строка товара
    -- grain: одна строка на order_id
    SELECT
        order_id,
        count(*) AS item_rows,
        count(quantity * unit_price) AS known_item_amount_rows,
        sum(quantity * unit_price) AS item_total,
        count(*) = count(quantity * unit_price) AS item_amount_complete
    FROM order_items
    GROUP BY order_id
),
safe_order_mart AS (
    -- population: все заказы
    -- grain: одна строка на order_id
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
),
paid_order_mart AS (
    -- population: только оплаченные заказы
    -- grain: одна строка на order_id
    SELECT
        order_id,
        user_id,
        currency,
        amount,
        item_rows,
        known_item_amount_rows,
        item_total,
        item_amount_complete,
        item_match_state,
        user_match_state,
        amount_reconciliation_state
    FROM safe_order_mart
    WHERE status = 'paid'
),
currency_summary AS (
    -- population: валюты, встречающиеся среди оплаченных заказов
    -- grain: одна строка на currency
    SELECT
        currency,
        count(*) AS paid_order_rows,
        count(amount) AS paid_known_amount_rows,
        count(*) - count(amount) AS paid_missing_amount_rows,
        sum(amount) AS known_paid_amount,
        count(*) FILTER (
            WHERE item_match_state = 'no_items'
        ) AS orders_without_items,
        count(*) FILTER (
            WHERE user_match_state = 'orphan_reference'
        ) AS orphan_user_orders,
        count(*) FILTER (
            WHERE amount_reconciliation_state = 'differs'
        ) AS amount_mismatch_orders,
        count(*) FILTER (
            WHERE amount_reconciliation_state = 'item_total_incomplete'
        ) AS incomplete_item_total_orders
    FROM paid_order_mart
    GROUP BY currency
)
-- FINAL RESULT
SELECT
    currency,
    paid_order_rows,
    paid_known_amount_rows,
    paid_missing_amount_rows,
    known_paid_amount,
    orders_without_items,
    orphan_user_orders,
    amount_mismatch_orders,
    incomplete_item_total_orders
FROM currency_summary
ORDER BY currency;
