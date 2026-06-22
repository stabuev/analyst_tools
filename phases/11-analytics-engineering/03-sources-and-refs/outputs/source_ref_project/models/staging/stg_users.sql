{{ config(materialized='view') }}

select
    cast(user_id as varchar) as user_id,
    cast(registered_at as timestamptz) as registered_at,
    upper(cast(country as varchar)) as country,
    lower(cast(platform as varchar)) as platform,
    lower(cast(acquisition_channel as varchar)) as acquisition_channel,
    lower(cast(plan as varchar)) as plan,
    cast(is_deleted as boolean) as is_deleted,
    cast(updated_at as timestamptz) as updated_at
from {{ source('raw_app', 'users') }}
