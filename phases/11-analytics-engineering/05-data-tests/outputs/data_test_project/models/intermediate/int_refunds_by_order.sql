select
    order_id,
    currency,
    cast(sum(amount) as decimal(18, 2)) as refund_amount_native,
    max(refunded_at) as last_refunded_at
from {{ ref('stg_refunds') }}
group by
    order_id,
    currency
