{{ config(materialized='view') }}

SELECT
    building_id,
    building_name,
    category,
    peak_capacity_kw,
    zone
FROM {{ ref('seed_buildings') }}
