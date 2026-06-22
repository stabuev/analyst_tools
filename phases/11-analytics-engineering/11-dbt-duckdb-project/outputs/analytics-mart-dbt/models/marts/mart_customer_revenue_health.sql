with line_revenue as (
    select * from {{ ref('int_order_line_revenue') }}
),

refunds_by_order as (
    select * from {{ ref('int_refunds_by_order') }}
),

revenue_by_order as (
    select
        line_rows.order_id,
        line_rows.user_id,
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
        line_rows.user_id,
        line_rows.order_date,
        line_rows.status,
        line_rows.currency
),

revenue_by_order_rub as (
    select
        order_rows.order_id,
        order_rows.user_id,
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
)

select
    user_rows.user_id,
    user_rows.country,
    user_rows.platform,
    user_rows.plan,
    coalesce(subscriptions.latest_subscription_status, 'none') as latest_subscription_status,
    coalesce(subscriptions.has_active_subscription, false) as has_active_subscription,
    count(distinct order_rows.order_id) as order_count,
    count(distinct case when order_rows.status = 'paid' then order_rows.order_id end) as paid_order_count,
    {{ to_decimal('coalesce(sum(order_rows.gross_revenue_rub), 0)') }} as gross_revenue_rub,
    {{ to_decimal('coalesce(sum(order_rows.paid_revenue_rub), 0)') }} as paid_revenue_rub,
    {{ to_decimal('coalesce(sum(order_rows.refunded_amount_rub), 0)') }} as refunded_amount_rub,
    coalesce(max(support_rows.support_ticket_count), 0) as support_ticket_count,
    coalesce(max(support_rows.high_priority_ticket_count), 0) as high_priority_ticket_count,
    case
        when
            coalesce(sum(order_rows.refunded_amount_rub), 0) > 0
            or coalesce(max(support_rows.support_ticket_count), 0) > 0
            then 'needs_attention'
        when coalesce(sum(order_rows.paid_revenue_rub), 0) >= 2000
            then 'high_value'
        when coalesce(sum(order_rows.paid_revenue_rub), 0) > 0
            then 'monetized'
        else 'no_revenue'
    end as revenue_health_segment
from {{ ref('stg_users') }} as user_rows
left join revenue_by_order_rub as order_rows
    on user_rows.user_id = order_rows.user_id
left join {{ ref('int_subscription_latest') }} as subscriptions
    on user_rows.user_id = subscriptions.user_id
left join {{ ref('int_support_by_user') }} as support_rows
    on user_rows.user_id = support_rows.user_id
where user_rows.is_deleted = false
group by
    user_rows.user_id,
    user_rows.country,
    user_rows.platform,
    user_rows.plan,
    subscriptions.latest_subscription_status,
    subscriptions.has_active_subscription
