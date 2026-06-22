with source_daily_revenue as (
    select
        purchase_rows.order_date as revenue_date,
        cast(
            sum(
                case
                    when purchase_rows.status = 'paid' then purchase_rows.amount * rates.rate_to_rub
                    else 0
                end
            )
            as decimal(18, 2)
        ) as expected_paid_revenue_rub,
        count(distinct purchase_rows.order_id) as expected_order_count,
        count(
            distinct case when purchase_rows.status = 'paid' then purchase_rows.order_id end
        ) as expected_paid_order_count
    from {{ ref('stg_orders') }} as purchase_rows
    inner join {{ ref('stg_currency_rates') }} as rates
        on
            purchase_rows.currency = rates.currency
            and purchase_rows.order_date = rates.rate_date
    group by purchase_rows.order_date
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
    mart.observed_order_count,
    source.expected_order_count,
    mart.observed_paid_order_count,
    source.expected_paid_order_count,
    mart.observed_paid_revenue_rub,
    source.expected_paid_revenue_rub,
    coalesce(mart.revenue_date, source.revenue_date) as revenue_date
from mart_daily_revenue as mart
full outer join source_daily_revenue as source
    on mart.revenue_date = source.revenue_date
where
    mart.revenue_date is null
    or source.revenue_date is null
    or mart.observed_order_count != source.expected_order_count
    or mart.observed_paid_order_count != source.expected_paid_order_count
    or abs(mart.observed_paid_revenue_rub - source.expected_paid_revenue_rub) > 0.01
