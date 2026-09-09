{{ config(materialized='table') }}

WITH campus_hourly AS (
    SELECT
        strftime(date_trunc('hour', timestamp), '%Y-%m-%d') AS dispatch_date,
        date_trunc('hour', timestamp) AS hour_window,
        SUM(power_kw) AS campus_demand_kw
    FROM {{ ref('silver_telemetry_clean') }}
    GROUP BY 1, 2
),

daily_agg AS (
    SELECT
        dispatch_date,
        COUNT(DISTINCT hour_window) AS active_hours,
        ROUND(AVG(campus_demand_kw), 2) AS avg_campus_demand_kw,
        ROUND(MAX(campus_demand_kw), 2) AS peak_campus_demand_kw,
        ROUND(MIN(campus_demand_kw), 2) AS min_campus_demand_kw,
        ROUND(SUM(campus_demand_kw), 2) AS total_daily_kwh
    FROM campus_hourly
    GROUP BY 1
),

dispatch_calc AS (
    SELECT
        dispatch_date,
        active_hours,
        avg_campus_demand_kw,
        peak_campus_demand_kw,
        min_campus_demand_kw,
        total_daily_kwh,
        {{ var('contract_demand_kw') }} AS contract_demand_limit_kw,
        GREATEST(0.0, ROUND(peak_campus_demand_kw - {{ var('contract_demand_kw') }}, 2)) AS overload_kw,
        CASE 
            WHEN peak_campus_demand_kw > {{ var('contract_demand_kw') }} THEN TRUE 
            ELSE FALSE 
        END AS is_contract_breached,
        ROUND(GREATEST(0.0, peak_campus_demand_kw - {{ var('contract_demand_kw') }}) * {{ var('demand_charge_penalty_rate_inr') }}, 2) AS demand_penalty_exposure_inr,
        CASE
            WHEN peak_campus_demand_kw > {{ var('contract_demand_kw') }} + 50.0 THEN 'Tier 3 (BESS + Chiller Cycling + Lighting)'
            WHEN peak_campus_demand_kw > {{ var('contract_demand_kw') }} THEN 'Tier 2 (Chiller Duty Cycling + Lighting)'
            WHEN peak_campus_demand_kw > ({{ var('contract_demand_kw') }} * 0.90) THEN 'Tier 1 (Architectural Lighting & EV Setback)'
            ELSE 'Nominal Grid Operation'
        END AS recommended_dispatch_tier
    FROM daily_agg
)

SELECT * FROM dispatch_calc
