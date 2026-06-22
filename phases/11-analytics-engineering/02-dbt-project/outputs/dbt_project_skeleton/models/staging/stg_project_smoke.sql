{{ config(materialized='view') }}

select
    'project_smoke' as smoke_check,
    cast(1 as integer) as passed,
    cast('staging' as varchar) as layer_name
