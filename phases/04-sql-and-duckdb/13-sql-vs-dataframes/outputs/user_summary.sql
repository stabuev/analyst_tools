SELECT
    user_id,
    count(*) AS order_count,
    count(*) FILTER (WHERE is_paid) AS paid_order_count,
    sum(paid_amount) AS paid_revenue,
    min(business_date) AS first_order_date,
    max(business_date) AS last_order_date,
    bool_and(user_found) AS user_found
FROM order_mart
GROUP BY user_id
ORDER BY user_id;
