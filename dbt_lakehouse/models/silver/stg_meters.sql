{{ config(materialized='view') }}

SELECT
    meter_id,
    building_id,
    meter_type,
    status
FROM {{ ref('seed_meters') }}
