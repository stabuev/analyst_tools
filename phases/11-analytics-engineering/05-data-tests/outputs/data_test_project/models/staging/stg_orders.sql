select
    order_id,
    user_id,
    cast(ordered_at as timestamptz) as ordered_at,
    cast(cast(ordered_at as timestamptz) as date) as order_date,
    lower(status) as status,
    upper(currency) as currency,
    cast(amount as decimal(18, 2)) as amount,
    cast(updated_at as timestamptz) as updated_at
from {{ source('raw_app', 'orders') }}
