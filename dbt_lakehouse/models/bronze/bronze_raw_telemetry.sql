{{ config(materialized='view') }}

SELECT
    event_id::VARCHAR AS event_id,
    timestamp::TIMESTAMP AS timestamp,
    meter_id::VARCHAR AS meter_id,
    building_id::VARCHAR AS building_id,
    COALESCE(building_type, 'Unknown')::VARCHAR AS building_type,
    power_kw::DOUBLE AS power_kw,
    voltage_v::DOUBLE AS voltage_v,
    current_a::DOUBLE AS current_a,
    power_factor::DOUBLE AS power_factor,
    current_timestamp AS _ingested_at
FROM read_parquet('{{ var("raw_telemetry_glob") }}', hive_partitioning=1, union_by_name=true)
