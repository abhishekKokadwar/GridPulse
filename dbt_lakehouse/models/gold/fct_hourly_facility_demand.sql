{{ config(materialized='table') }}

WITH hourly_metrics AS (
    SELECT
        strftime(date_trunc('hour', timestamp), '%Y-%m-%d %H:00:00') AS hour_timestamp,
        date_trunc('hour', timestamp) AS hour_window,
        building_id,
        building_name,
        category,
        zone,
        COUNT(DISTINCT meter_id) AS active_meter_count,
        COUNT(*) AS sample_count,
        ROUND(AVG(power_kw), 2) AS avg_power_kw,
        ROUND(MAX(power_kw), 2) AS peak_power_kw,
        ROUND(MIN(power_kw), 2) AS min_power_kw,
        ROUND(SUM(power_kw) / NULLIF(COUNT(*), 0) * 1.0, 2) AS total_kwh,
        ROUND(AVG(voltage_v), 1) AS avg_voltage_v,
        ROUND(AVG(power_factor), 3) AS avg_power_factor,
        SUM(CASE WHEN is_voltage_sag_swell THEN 1 ELSE 0 END) AS voltage_anomalies_count,
        SUM(CASE WHEN is_low_power_factor THEN 1 ELSE 0 END) AS low_pf_anomalies_count
    FROM {{ ref('silver_telemetry_clean') }}
    GROUP BY 1, 2, 3, 4, 5, 6
)

SELECT 
    md5(concat(hour_timestamp, '_', building_id)) AS hourly_facility_id,
    hour_timestamp,
    hour_window,
    building_id,
    building_name,
    category,
    zone,
    active_meter_count,
    sample_count,
    avg_power_kw,
    peak_power_kw,
    min_power_kw,
    total_kwh,
    avg_voltage_v,
    avg_power_factor,
    voltage_anomalies_count,
    low_pf_anomalies_count
FROM hourly_metrics
