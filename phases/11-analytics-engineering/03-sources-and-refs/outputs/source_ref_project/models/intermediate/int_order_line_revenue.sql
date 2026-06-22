{{ config(materialized='view') }}

select
    items.order_id,
    orders.user_id,
    items.line_number,
    items.product_id,
    items.quantity,
    items.unit_price,
    items.currency,
    orders.status,
    cast(items.quantity * items.unit_price as decimal(18, 2)) as line_revenue
from {{ ref('stg_order_items') }} as items
inner join {{ ref('stg_orders') }} as orders
    on items.order_id = orders.order_id
