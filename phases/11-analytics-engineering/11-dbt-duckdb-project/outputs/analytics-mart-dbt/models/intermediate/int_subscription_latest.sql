with ranked as (
    select
        user_id,
        plan,
        status,
        started_at,
        ended_at,
        updated_at,
        row_number() over (
            partition by user_id
            order by updated_at desc, subscription_id desc
        ) as row_number_latest
    from {{ ref('stg_subscriptions') }}
)

select
    user_id,
    plan as latest_subscription_plan,
    status as latest_subscription_status,
    started_at as latest_subscription_started_at,
    ended_at as latest_subscription_ended_at,
    updated_at as latest_subscription_updated_at,
    status = 'active' as has_active_subscription
from ranked
where row_number_latest = 1
