select
    user_id,
    count(*) as support_ticket_count,
    sum(case when priority = 'high' then 1 else 0 end) as high_priority_ticket_count,
    max(created_at) as last_ticket_at
from {{ ref('stg_support_tickets') }}
group by user_id
