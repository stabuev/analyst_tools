select
    {{ normalize_currency('currency') }} as currency,
    cast(rate_date as date) as rate_date,
    {{ to_decimal('rate_to_rub', 18, 4) }} as rate_to_rub,
    cast(loaded_at as timestamptz) as loaded_at
from {{ source('raw_app', 'currency_rates') }}
