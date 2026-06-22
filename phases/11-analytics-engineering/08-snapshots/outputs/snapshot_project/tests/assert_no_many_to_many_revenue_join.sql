with expected as (
    select count(*) as source_order_item_rows
    from {{ ref('stg_order_items') }}
),

observed as (
    select count(*) as revenue_line_rows
    from {{ ref('int_order_line_revenue') }}
)

select
    revenue_line_rows,
    source_order_item_rows
from observed
cross join expected
where revenue_line_rows != source_order_item_rows
