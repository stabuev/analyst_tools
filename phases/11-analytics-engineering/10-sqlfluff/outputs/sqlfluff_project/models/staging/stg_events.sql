select
    event_id,
    user_id,
    event_name,
    cast(event_version as integer) as event_version,
    cast(occurred_at as timestamptz) as occurred_at,
    cast(received_at as timestamptz) as received_at,
    properties_json,
    lower(platform) as platform
from {{ source('raw_app', 'events') }}
