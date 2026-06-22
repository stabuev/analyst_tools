with expected as (
    select count(*) as source_order_item_rows
    from {{ ref('stg_order_items') }}
),

observed as (
    select count(*) as revenue_line_rows
    from {{ ref('int_order_line_revenue') }}
)

select
    observed.revenue_line_rows,
    expected.source_order_item_rows
from observed
cross join expected
where observed.revenue_line_rows != expected.source_order_item_rows
