select
    order_id,
    user_id,
    cast(ordered_at as timestamptz) as ordered_at,
    cast(cast(ordered_at as timestamptz) as date) as order_date,
    {{ normalize_status('status') }} as status,
    {{ normalize_currency('currency') }} as currency,
    {{ to_decimal('amount') }} as amount,
    cast(updated_at as timestamptz) as updated_at
from {{ source('raw_app', 'orders') }}
