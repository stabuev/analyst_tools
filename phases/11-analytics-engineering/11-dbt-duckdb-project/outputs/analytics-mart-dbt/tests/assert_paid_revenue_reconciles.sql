with source_paid_revenue as (
    select cast(sum(purchase_rows.amount * rates.rate_to_rub) as decimal(18, 2)) as expected_paid_revenue_rub
    from {{ ref('stg_orders') }} as purchase_rows
    inner join {{ ref('stg_currency_rates') }} as rates
        on
            purchase_rows.currency = rates.currency
            and purchase_rows.order_date = rates.rate_date
    where purchase_rows.status = 'paid'
),

mart_paid_revenue as (
    select cast(sum(paid_revenue_rub) as decimal(18, 2)) as observed_paid_revenue_rub
    from {{ ref('mart_customer_revenue_health') }}
)

select
    mart.observed_paid_revenue_rub,
    source.expected_paid_revenue_rub
from mart_paid_revenue as mart
cross join source_paid_revenue as source
where abs(mart.observed_paid_revenue_rub - source.expected_paid_revenue_rub) > 0.01
