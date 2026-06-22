{%- macro normalize_status(column_name) -%}
lower({{ column_name }})
{%- endmacro -%}

{%- macro normalize_currency(column_name) -%}
upper({{ column_name }})
{%- endmacro -%}

{%- macro to_decimal(column_name, precision=18, scale=2) -%}
cast({{ column_name }} as decimal({{ precision }}, {{ scale }}))
{%- endmacro -%}

{%- macro money_product(quantity_column, unit_price_column, precision=18, scale=2) -%}
cast({{ quantity_column }} * {{ unit_price_column }} as decimal({{ precision }}, {{ scale }}))
{%- endmacro -%}

{%- macro rub_amount(amount_column, rate_column, precision=18, scale=2) -%}
cast({{ amount_column }} * {{ rate_column }} as decimal({{ precision }}, {{ scale }}))
{%- endmacro -%}
