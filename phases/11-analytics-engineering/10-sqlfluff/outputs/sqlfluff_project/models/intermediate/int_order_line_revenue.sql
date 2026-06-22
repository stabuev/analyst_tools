select
    items.order_id,
    purchase_rows.user_id,
    purchase_rows.order_date,
    items.line_number,
    items.product_id,
    items.quantity,
    items.unit_price,
    items.currency,
    purchase_rows.status,
    {{ money_product('items.quantity', 'items.unit_price') }} as line_revenue_native
from {{ ref('stg_order_items') }} as items
inner join {{ ref('stg_orders') }} as purchase_rows
    on items.order_id = purchase_rows.order_id
