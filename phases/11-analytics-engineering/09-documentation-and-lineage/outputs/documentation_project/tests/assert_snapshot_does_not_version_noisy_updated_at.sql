select
    subscription_id,
    count(*) as version_count
from {{ ref('int_subscription_history') }}
where subscription_id = 's001'
group by subscription_id
having count(*) != 1
