select
    upper(currency) as currency,
    cast(rate_date as date) as rate_date,
    cast(rate_to_rub as decimal(18, 4)) as rate_to_rub,
    cast(loaded_at as timestamptz) as loaded_at
from {{ source('raw_app', 'currency_rates') }}
