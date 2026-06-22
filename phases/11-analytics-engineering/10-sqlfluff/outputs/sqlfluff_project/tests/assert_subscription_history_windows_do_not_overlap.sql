with ordered_history as (
    select
        subscription_id,
        valid_from,
        valid_to,
        lead(valid_from) over (
            partition by subscription_id
            order by valid_from
        ) as next_valid_from
    from {{ ref('int_subscription_history') }}
)

select
    subscription_id,
    valid_from,
    valid_to,
    next_valid_from
from ordered_history
where
    next_valid_from is not null
    and valid_to != next_valid_from
