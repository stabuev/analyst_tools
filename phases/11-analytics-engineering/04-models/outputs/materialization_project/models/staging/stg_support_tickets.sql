select
    ticket_id,
    user_id,
    cast(created_at as timestamptz) as created_at,
    lower(topic) as topic,
    lower(priority) as priority,
    lower(status) as status
from {{ source('raw_app', 'support_tickets') }}
