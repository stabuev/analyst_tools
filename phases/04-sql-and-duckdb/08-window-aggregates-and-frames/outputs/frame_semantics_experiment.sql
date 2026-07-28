-- A deliberately small oracle for frame semantics.
-- sort_key has peers (A and B) and a gap before D.
--
-- default_running_sum demonstrates the implicit RANGE-like frame.
-- rows_running_sum counts deterministic row positions.
-- range_running_sum includes all peers at the current sort_key.
-- rows_distance_1_sum selects one preceding row position.
-- range_distance_1_sum selects values whose sort_key is within one unit.
-- default_last_value stops at the current frame; partition_last_value sees the full
-- partition because its frame ends at UNBOUNDED FOLLOWING.

WITH frame_events(row_id, sort_key, amount) AS (
    VALUES
        ('A', 1, 10),
        ('B', 1, 20),
        ('C', 2, 5),
        ('D', 4, 40)
)
SELECT
    row_id,
    sort_key,
    amount,
    sum(amount) OVER (
        ORDER BY sort_key
    ) AS default_running_sum,
    sum(amount) OVER (
        ORDER BY sort_key, row_id
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) AS rows_running_sum,
    sum(amount) OVER (
        ORDER BY sort_key
        RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) AS range_running_sum,
    sum(amount) OVER (
        ORDER BY sort_key, row_id
        ROWS BETWEEN 1 PRECEDING AND CURRENT ROW
    ) AS rows_distance_1_sum,
    sum(amount) OVER (
        ORDER BY sort_key
        RANGE BETWEEN 1 PRECEDING AND CURRENT ROW
    ) AS range_distance_1_sum,
    last_value(row_id) OVER (
        ORDER BY sort_key, row_id
    ) AS default_last_value,
    last_value(row_id) OVER (
        ORDER BY sort_key, row_id
        ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
    ) AS partition_last_value
FROM frame_events
ORDER BY sort_key, row_id;
