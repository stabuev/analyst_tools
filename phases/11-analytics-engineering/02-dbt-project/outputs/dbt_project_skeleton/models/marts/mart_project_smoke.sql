{{ config(materialized='table') }}

select
    smoke_check,
    passed,
    cast('mart' as varchar) as published_layer
from {{ ref('int_project_smoke') }}
