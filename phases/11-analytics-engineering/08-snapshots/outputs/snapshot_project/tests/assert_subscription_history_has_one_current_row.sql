select
    subscription_id,
    count(*) as current_row_count
from {{ ref('int_subscription_history') }}
where is_current
group by subscription_id
having count(*) != 1
