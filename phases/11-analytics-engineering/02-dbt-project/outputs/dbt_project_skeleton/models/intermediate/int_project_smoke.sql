{{ config(materialized='view') }}

select
    smoke_check,
    passed,
    cast('intermediate' as varchar) as next_layer
from {{ ref('stg_project_smoke') }}
