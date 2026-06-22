{{ config(materialized='view') }}

select
    cast(order_id as varchar) as order_id,
    cast(user_id as varchar) as user_id,
    cast(ordered_at as timestamptz) as ordered_at,
    lower(cast(status as varchar)) as status,
    upper(cast(currency as varchar)) as currency,
    cast(amount as decimal(18, 2)) as amount,
    cast(updated_at as timestamptz) as updated_at
from {{ source('raw_app', 'orders') }}
