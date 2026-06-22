select
    refund_id,
    order_id,
    cast(refunded_at as timestamptz) as refunded_at,
    {{ normalize_currency('currency') }} as currency,
    {{ to_decimal('amount') }} as amount,
    reason
from {{ source('raw_app', 'refunds') }}
