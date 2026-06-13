SELECT
    order_id,
    user_id,
    upper(trim(currency)) AS currency,
    amount::DOUBLE AS amount
FROM read_csv(?, header = true, all_varchar = true, nullstr = '')
WHERE lower(trim(status)) = 'paid'
  AND amount::DOUBLE >= ?
ORDER BY amount::DOUBLE DESC, order_id;
