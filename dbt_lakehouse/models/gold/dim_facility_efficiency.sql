{{ config(materialized='table') }}

WITH facility_totals AS (
    SELECT
        building_id,
        building_name,
        category,
        zone,
        COUNT(DISTINCT meter_id) AS total_meters,
        ROUND(AVG(power_kw), 2) AS avg_demand_kw,
        ROUND(MAX(power_kw), 2) AS peak_demand_kw,
        ROUND(MIN(power_kw), 2) AS baseload_demand_kw,
        ROUND(AVG(power_kw) / NULLIF(MAX(power_kw), 0), 3) AS load_factor,
        ROUND(AVG(power_factor), 3) AS avg_power_factor,
        COUNT(*) AS total_telemetry_samples
    FROM {{ ref('silver_telemetry_clean') }}
    GROUP BY 1, 2, 3, 4
),

ranked AS (
    SELECT
        building_id,
        building_name,
        category,
        zone,
        total_meters,
        avg_demand_kw,
        peak_demand_kw,
        baseload_demand_kw,
        load_factor,
        avg_power_factor,
        total_telemetry_samples,
        DENSE_RANK() OVER (
            PARTITION BY category 
            ORDER BY load_factor DESC
        ) AS category_efficiency_rank,
        ROUND(
            peak_demand_kw / NULLIF(SUM(peak_demand_kw) OVER (), 0) * 100.0,
            2
        ) AS peak_campus_contribution_pct
    FROM facility_totals
)

SELECT * FROM ranked
