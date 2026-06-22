select
    order_id,
    cast(line_number as integer) as line_number,
    product_id,
    cast(quantity as integer) as quantity,
    cast(unit_price as decimal(18, 2)) as unit_price,
    upper(currency) as currency,
    cast(loaded_at as timestamptz) as loaded_at
from {{ source('raw_app', 'order_items') }}
