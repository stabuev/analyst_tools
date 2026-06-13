WITH
users AS (
    SELECT
        user_id,
        upper(trim(country)) AS country,
        lower(trim(plan)) AS plan
    FROM read_csv(?, header = true, all_varchar = true, nullstr = '')
),
orders AS (
    SELECT
        order_id,
        user_id,
        cast(timezone(?, ordered_at::TIMESTAMPTZ) AS DATE) AS business_date,
        lower(trim(status)) AS status,
        upper(trim(currency)) AS currency,
        amount::DECIMAL(18, 2) AS amount
    FROM read_csv(?, header = true, all_varchar = true, nullstr = '')
),
items AS (
    SELECT
        order_id,
        product_id,
        regexp_replace(lower(trim(category)), '[ -]+', '_', 'g') AS category,
        quantity::INTEGER AS quantity,
        unit_price::DECIMAL(18, 2) AS unit_price
    FROM read_csv(?, header = true, all_varchar = true, nullstr = '')
),
item_totals AS (
    SELECT
        order_id,
        count(*) AS item_rows,
        sum(quantity * unit_price) AS item_total,
        string_agg(DISTINCT category, '|' ORDER BY category) AS categories
    FROM items
    GROUP BY order_id
)
SELECT
    orders.order_id,
    orders.user_id,
    orders.business_date,
    orders.status,
    orders.currency,
    orders.amount,
    item_totals.item_rows,
    item_totals.item_total,
    item_totals.categories,
    users.country,
    users.plan,
    users.user_id IS NOT NULL AS user_found,
    orders.status = 'paid' AS is_paid,
    CASE WHEN orders.status = 'paid' THEN orders.amount ELSE 0 END AS paid_amount,
    CASE
        WHEN orders.amount IS NULL OR item_totals.item_total IS NULL THEN NULL
        ELSE abs(orders.amount - item_totals.item_total) <= 0.0001
    END AS amount_matches_items
FROM orders
LEFT JOIN item_totals USING (order_id)
LEFT JOIN users USING (user_id)
ORDER BY orders.order_id;
