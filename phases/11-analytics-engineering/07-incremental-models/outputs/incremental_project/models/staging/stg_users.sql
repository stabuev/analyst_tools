select
    user_id,
    cast(registered_at as timestamptz) as registered_at,
    country,
    lower(platform) as platform,
    acquisition_channel,
    lower(plan) as plan,
    cast(is_deleted as boolean) as is_deleted,
    cast(updated_at as timestamptz) as updated_at
from {{ source('raw_app', 'users') }}
