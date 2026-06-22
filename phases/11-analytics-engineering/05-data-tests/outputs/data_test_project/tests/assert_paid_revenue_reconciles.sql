with source_paid_revenue as (
    select
        cast(sum(orders.amount * rates.rate_to_rub) as decimal(18, 2)) as expected_paid_revenue_rub
    from {{ ref('stg_orders') }} as orders
    inner join {{ ref('stg_currency_rates') }} as rates
        on orders.currency = rates.currency
        and orders.order_date = rates.rate_date
    where orders.status = 'paid'
),

mart_paid_revenue as (
    select
        cast(sum(paid_revenue_rub) as decimal(18, 2)) as observed_paid_revenue_rub
    from {{ ref('mart_customer_revenue_health') }}
)

select
    observed_paid_revenue_rub,
    expected_paid_revenue_rub
from mart_paid_revenue
cross join source_paid_revenue
where abs(observed_paid_revenue_rub - expected_paid_revenue_rub) > 0.01
