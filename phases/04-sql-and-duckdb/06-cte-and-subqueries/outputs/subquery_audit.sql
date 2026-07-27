SELECT
    -- scalar subquery: одна ячейка в строке результата
    (SELECT count(*) FROM orders) AS source_order_rows,
    (SELECT count(*) FROM orders WHERE status = 'paid') AS source_paid_order_rows,
    -- EXISTS: один логический ответ, существуют ли такие строки
    EXISTS (
        SELECT 1
        FROM orders AS o
        WHERE o.user_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1
              FROM users AS u
              WHERE u.user_id = o.user_id
          )
    ) AS has_orphan_user_reference;
