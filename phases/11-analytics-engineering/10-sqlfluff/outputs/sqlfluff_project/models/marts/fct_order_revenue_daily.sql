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

revenue_by_order as (
    select
        line_rows.order_id,
        line_rows.order_date,
        line_rows.status,
        line_rows.currency,
        {{ to_decimal('sum(line_rows.line_revenue_native)') }} as gross_amount_native,
        {{ to_decimal('coalesce(max(refunds.refund_amount_native), 0)') }} as refund_amount_native
    from line_revenue as line_rows
    left join refunds_by_order as refunds
        on line_rows.order_id = refunds.order_id
    group by
        line_rows.order_id,
        line_rows.order_date,
        line_rows.status,
        line_rows.currency
),

revenue_by_order_rub as (
    select
        order_rows.order_id,
        order_rows.order_date,
        order_rows.status,
        {{ rub_amount('order_rows.gross_amount_native', 'rates.rate_to_rub') }} as gross_revenue_rub,
        cast(
            case
                when order_rows.status = 'paid'
                    then {{
                        rub_amount(
                            '(order_rows.gross_amount_native - order_rows.refund_amount_native)',
                            'rates.rate_to_rub'
                        )
                    }}
                else 0
            end
            as decimal(18, 2)
        ) as paid_revenue_rub,
        {{ rub_amount('order_rows.refund_amount_native', 'rates.rate_to_rub') }} as refunded_amount_rub
    from revenue_by_order as order_rows
    left join {{ ref('stg_currency_rates') }} as rates
        on
            order_rows.currency = rates.currency
            and order_rows.order_date = rates.rate_date
),

daily_revenue as (
    select
        order_rows.order_date as revenue_date,
        count(distinct order_rows.order_id) as order_count,
        count(distinct case when order_rows.status = 'paid' then order_rows.order_id end) as paid_order_count,
        {{ to_decimal('sum(order_rows.gross_revenue_rub)') }} as gross_revenue_rub,
        {{ to_decimal('sum(order_rows.paid_revenue_rub)') }} as paid_revenue_rub,
        {{ to_decimal('sum(order_rows.refunded_amount_rub)') }} as refunded_amount_rub,
        max(order_rows.order_date) as max_source_order_date
    from revenue_by_order_rub as order_rows
    {% if is_incremental() %}
    where order_rows.order_date >= (
        select coalesce(max(revenue_date) - interval '2 days', date '1900-01-01') from {{ this }}
    )
    {% endif %}
    group by order_rows.order_date
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
