with line_revenue as (
    select * from {{ ref('int_order_line_revenue') }}
),

refunds_by_order as (
    select * from {{ ref('int_refunds_by_order') }}
),

order_revenue as (
    select
        lines.order_id,
        lines.user_id,
        lines.order_date,
        lines.status,
        lines.currency,
        cast(sum(lines.line_revenue_native) as decimal(18, 2)) as gross_amount_native,
        cast(coalesce(max(refunds.refund_amount_native), 0) as decimal(18, 2)) as refund_amount_native
    from line_revenue as lines
    left join refunds_by_order as refunds
        on lines.order_id = refunds.order_id
    group by
        lines.order_id,
        lines.user_id,
        lines.order_date,
        lines.status,
        lines.currency
),

order_revenue_rub as (
    select
        orders.order_id,
        orders.user_id,
        orders.status,
        cast(orders.gross_amount_native * rates.rate_to_rub as decimal(18, 2)) as gross_revenue_rub,
        cast(
            case
                when orders.status = 'paid'
                    then (orders.gross_amount_native - orders.refund_amount_native) * rates.rate_to_rub
                else 0
            end
            as decimal(18, 2)
        ) as paid_revenue_rub,
        cast(orders.refund_amount_native * rates.rate_to_rub as decimal(18, 2)) as refunded_amount_rub
    from order_revenue as orders
    left join {{ ref('stg_currency_rates') }} as rates
        on orders.currency = rates.currency
        and orders.order_date = rates.rate_date
)

select
    users.user_id,
    users.country,
    users.platform,
    users.plan,
    coalesce(subscriptions.latest_subscription_status, 'none') as latest_subscription_status,
    coalesce(subscriptions.has_active_subscription, false) as has_active_subscription,
    count(distinct orders.order_id) as order_count,
    count(distinct case when orders.status = 'paid' then orders.order_id end) as paid_order_count,
    cast(coalesce(sum(orders.gross_revenue_rub), 0) as decimal(18, 2)) as gross_revenue_rub,
    cast(coalesce(sum(orders.paid_revenue_rub), 0) as decimal(18, 2)) as paid_revenue_rub,
    cast(coalesce(sum(orders.refunded_amount_rub), 0) as decimal(18, 2)) as refunded_amount_rub,
    coalesce(max(support.support_ticket_count), 0) as support_ticket_count,
    coalesce(max(support.high_priority_ticket_count), 0) as high_priority_ticket_count,
    case
        when coalesce(sum(orders.refunded_amount_rub), 0) > 0
            or coalesce(max(support.support_ticket_count), 0) > 0
            then 'needs_attention'
        when coalesce(sum(orders.paid_revenue_rub), 0) >= 2000
            then 'high_value'
        when coalesce(sum(orders.paid_revenue_rub), 0) > 0
            then 'monetized'
        else 'no_revenue'
    end as revenue_health_segment
from {{ ref('stg_users') }} as users
left join order_revenue_rub as orders
    on users.user_id = orders.user_id
left join {{ ref('int_subscription_latest') }} as subscriptions
    on users.user_id = subscriptions.user_id
left join {{ ref('int_support_by_user') }} as support
    on users.user_id = support.user_id
where users.is_deleted = false
group by
    users.user_id,
    users.country,
    users.platform,
    users.plan,
    subscriptions.latest_subscription_status,
    subscriptions.has_active_subscription
