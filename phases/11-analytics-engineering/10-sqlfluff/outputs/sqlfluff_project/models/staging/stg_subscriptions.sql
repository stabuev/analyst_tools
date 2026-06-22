select
    subscription_id,
    user_id,
    {{ normalize_status('plan') }} as plan,
    {{ normalize_status('status') }} as status,
    cast(started_at as timestamptz) as started_at,
    cast(nullif(cast(ended_at as varchar), '') as timestamptz) as ended_at,
    cast(updated_at as timestamp) as updated_at
from {{ source('raw_app', 'subscriptions') }}
