with source_daily_revenue as (
    select
        orders.order_date as revenue_date,
        count(distinct orders.order_id) as expected_order_count,
        count(distinct case when orders.status = 'paid' then orders.order_id end) as expected_paid_order_count,
        cast(
            sum(
                case
                    when orders.status = 'paid' then orders.amount * rates.rate_to_rub
                    else 0
                end
            )
            as decimal(18, 2)
        ) as expected_paid_revenue_rub
    from {{ ref('stg_orders') }} as orders
    inner join {{ ref('stg_currency_rates') }} as rates
        on orders.currency = rates.currency
        and orders.order_date = rates.rate_date
    group by orders.order_date
),

mart_daily_revenue as (
    select
        revenue_date,
        order_count as observed_order_count,
        paid_order_count as observed_paid_order_count,
        paid_revenue_rub as observed_paid_revenue_rub
    from {{ ref('fct_order_revenue_daily') }}
)

select
    coalesce(mart.revenue_date, source.revenue_date) as revenue_date,
    observed_order_count,
    expected_order_count,
    observed_paid_order_count,
    expected_paid_order_count,
    observed_paid_revenue_rub,
    expected_paid_revenue_rub
from mart_daily_revenue as mart
full outer join source_daily_revenue as source
    on mart.revenue_date = source.revenue_date
where mart.revenue_date is null
    or source.revenue_date is null
    or observed_order_count != expected_order_count
    or observed_paid_order_count != expected_paid_order_count
    or abs(observed_paid_revenue_rub - expected_paid_revenue_rub) > 0.01
