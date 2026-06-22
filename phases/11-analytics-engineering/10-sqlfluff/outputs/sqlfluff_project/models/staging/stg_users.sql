select
    user_id,
    cast(registered_at as timestamptz) as registered_at,
    country,
    acquisition_channel,
    cast(is_deleted as boolean) as is_deleted,
    cast(updated_at as timestamptz) as updated_at,
    lower(platform) as platform,
    lower(plan) as plan
from {{ source('raw_app', 'users') }}
