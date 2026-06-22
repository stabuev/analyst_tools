select
    items.order_id,
    orders.user_id,
    orders.order_date,
    items.line_number,
    items.product_id,
    items.quantity,
    items.unit_price,
    items.currency,
    orders.status,
    {{ money_product('items.quantity', 'items.unit_price') }} as line_revenue_native
from {{ ref('stg_order_items') }} as items
inner join {{ ref('stg_orders') }} as orders
    on items.order_id = orders.order_id
