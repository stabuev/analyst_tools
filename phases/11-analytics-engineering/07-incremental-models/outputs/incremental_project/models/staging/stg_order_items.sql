select
    order_id,
    cast(line_number as integer) as line_number,
    product_id,
    cast(quantity as integer) as quantity,
    {{ to_decimal('unit_price') }} as unit_price,
    {{ normalize_currency('currency') }} as currency,
    cast(loaded_at as timestamptz) as loaded_at
from {{ source('raw_app', 'order_items') }}
