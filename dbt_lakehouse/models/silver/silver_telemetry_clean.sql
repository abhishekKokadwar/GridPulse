{{ config(materialized='table') }}

WITH raw AS (
    SELECT * FROM {{ ref('bronze_raw_telemetry') }}
),

deduped AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY meter_id, timestamp 
            ORDER BY event_id DESC
        ) AS dedup_rank
    FROM raw
),

filtered AS (
    SELECT
        d.event_id,
        d.timestamp,
        d.meter_id,
        d.building_id,
        COALESCE(b.building_name, d.building_id) AS building_name,
        COALESCE(b.category, d.building_type, 'Facilities') AS category,
        COALESCE(b.zone, 'General Zone') AS zone,
        COALESCE(b.peak_capacity_kw, 100.0) AS building_capacity_kw,
        COALESCE(m.meter_type, 'Smart Sub-Meter') AS meter_type,
        -- Physical electrical plausibility boundaries
        GREATEST(0.0, d.power_kw) AS power_kw,
        CASE 
            WHEN d.voltage_v BETWEEN 180.0 AND 270.0 THEN d.voltage_v
            ELSE 230.0
        END AS voltage_v,
        GREATEST(0.0, d.current_a) AS current_a,
        CASE
            WHEN d.power_factor BETWEEN 0.70 AND 1.00 THEN d.power_factor
            WHEN d.power_factor > 1.00 THEN 1.00
            ELSE 0.85
        END AS power_factor,
        -- Operational quality flags
        CASE 
            WHEN d.voltage_v NOT BETWEEN 200.0 AND 250.0 THEN TRUE 
            ELSE FALSE 
        END AS is_voltage_sag_swell,
        CASE 
            WHEN d.power_factor < 0.85 THEN TRUE 
            ELSE FALSE 
        END AS is_low_power_factor,
        d._ingested_at
    FROM deduped d
    LEFT JOIN {{ ref('stg_buildings') }} b ON d.building_id = b.building_id
    LEFT JOIN {{ ref('stg_meters') }} m ON d.meter_id = m.meter_id
    WHERE d.dedup_rank = 1
      AND d.timestamp IS NOT NULL
      AND d.power_kw IS NOT NULL
)

SELECT * FROM filtered
