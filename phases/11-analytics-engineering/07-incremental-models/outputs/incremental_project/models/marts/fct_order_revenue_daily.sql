{{
    config(
        materialized='incremental',
        unique_key='revenue_date',
        incremental_strategy='delete+insert',
        on_schema_change='fail'
    )
}}

with line_revenue as (
    select * from {{ ref('int_order_line_revenue') }}
),

refunds_by_order as (
    select * from {{ ref('int_refunds_by_order') }}
),

order_revenue as (
    select
        lines.order_id,
        lines.order_date,
        lines.status,
        lines.currency,
        {{ to_decimal('sum(lines.line_revenue_native)') }} as gross_amount_native,
        {{ to_decimal('coalesce(max(refunds.refund_amount_native), 0)') }} as refund_amount_native
    from line_revenue as lines
    left join refunds_by_order as refunds
        on lines.order_id = refunds.order_id
    group by
        lines.order_id,
        lines.order_date,
        lines.status,
        lines.currency
),

order_revenue_rub as (
    select
        orders.order_id,
        orders.order_date,
        orders.status,
        {{ rub_amount('orders.gross_amount_native', 'rates.rate_to_rub') }} as gross_revenue_rub,
        cast(
            case
                when orders.status = 'paid'
                    then {{ rub_amount('(orders.gross_amount_native - orders.refund_amount_native)', 'rates.rate_to_rub') }}
                else 0
            end
            as decimal(18, 2)
        ) as paid_revenue_rub,
        {{ rub_amount('orders.refund_amount_native', 'rates.rate_to_rub') }} as refunded_amount_rub
    from order_revenue as orders
    left join {{ ref('stg_currency_rates') }} as rates
        on orders.currency = rates.currency
        and orders.order_date = rates.rate_date
),

daily_revenue as (
    select
        orders.order_date as revenue_date,
        count(distinct orders.order_id) as order_count,
        count(distinct case when orders.status = 'paid' then orders.order_id end) as paid_order_count,
        {{ to_decimal('sum(orders.gross_revenue_rub)') }} as gross_revenue_rub,
        {{ to_decimal('sum(orders.paid_revenue_rub)') }} as paid_revenue_rub,
        {{ to_decimal('sum(orders.refunded_amount_rub)') }} as refunded_amount_rub,
        max(orders.order_date) as max_source_order_date
    from order_revenue_rub as orders
    {% if is_incremental() %}
    where orders.order_date >= (
        select coalesce(max(revenue_date) - interval '2 days', date '1900-01-01') from {{ this }}
    )
    {% endif %}
    group by orders.order_date
)

select
    revenue_date,
    order_count,
    paid_order_count,
    gross_revenue_rub,
    paid_revenue_rub,
    refunded_amount_rub,
    max_source_order_date
from daily_revenue
