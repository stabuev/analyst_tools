select
    refund_id,
    order_id,
    cast(refunded_at as timestamptz) as refunded_at,
    upper(currency) as currency,
    cast(amount as decimal(18, 2)) as amount,
    reason
from {{ source('raw_app', 'refunds') }}
