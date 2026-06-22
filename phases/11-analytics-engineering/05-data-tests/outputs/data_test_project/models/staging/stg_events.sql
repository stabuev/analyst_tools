select
    event_id,
    user_id,
    event_name,
    cast(event_version as integer) as event_version,
    cast(occurred_at as timestamptz) as occurred_at,
    cast(received_at as timestamptz) as received_at,
    lower(platform) as platform,
    properties_json
from {{ source('raw_app', 'events') }}
