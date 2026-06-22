select
    subscription_id,
    user_id,
    plan,
    status,
    started_at,
    ended_at,
    cast(dbt_valid_from as timestamp) as valid_from,
    cast(dbt_valid_to as timestamp) as valid_to,
    dbt_updated_at,
    dbt_scd_id,
    cast(dbt_valid_to as timestamp) = timestamp '9999-12-31 00:00:00' as is_current
from {{ ref('subscription_status_snapshot') }}
