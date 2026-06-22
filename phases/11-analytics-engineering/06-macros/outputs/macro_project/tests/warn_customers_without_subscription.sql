{{ config(severity = 'warn') }}

select
    user_id,
    latest_subscription_status,
    support_ticket_count,
    revenue_health_segment
from {{ ref('mart_customer_revenue_health') }}
where latest_subscription_status = 'none'
    or support_ticket_count > 0
