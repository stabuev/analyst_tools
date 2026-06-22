{{ config(materialized='table') }}

select
    users.user_id,
    users.country,
    users.platform,
    users.plan,
    count(distinct revenue.order_id) as order_count,
    coalesce(
        sum(case when revenue.status = 'paid' then revenue.line_revenue else 0 end),
        0
    ) as paid_revenue
from {{ ref('stg_users') }} as users
left join {{ ref('int_order_line_revenue') }} as revenue
    on users.user_id = revenue.user_id
where users.is_deleted = false
group by
    users.user_id,
    users.country,
    users.platform,
    users.plan
