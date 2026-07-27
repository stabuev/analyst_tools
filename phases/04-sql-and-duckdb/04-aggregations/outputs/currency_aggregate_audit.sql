SELECT
    currency,
    count(*) AS order_rows,
    count(amount) AS known_amount_rows,
    count(*) FILTER (WHERE status = 'paid') AS paid_order_rows,
    count(amount) FILTER (WHERE status = 'paid') AS paid_known_amount_rows,
    (
        count(*) FILTER (WHERE status = 'paid')
        - count(amount) FILTER (WHERE status = 'paid')
    ) AS paid_missing_amount_rows,
    (
        count(*) FILTER (WHERE status = 'paid')
        = count(amount) FILTER (WHERE status = 'paid')
    ) AS paid_amount_complete,
    sum(amount) FILTER (WHERE status = 'paid') AS known_paid_revenue,
    avg(amount) FILTER (WHERE status = 'paid') AS average_known_paid_amount
FROM orders
GROUP BY currency
ORDER BY currency ASC NULLS LAST;
