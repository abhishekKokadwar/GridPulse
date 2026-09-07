import os
from datetime import datetime
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
import psycopg2
from psycopg2.extras import execute_values

# Load environment variables
load_dotenv()

DEFAULT_DB_URL = "postgresql://postgres:password@localhost:5432/neondb"
DATABASE_URL = os.getenv("DATABASE_URL", DEFAULT_DB_URL)

DB_AVAILABLE = True

# SQLAlchemy engine with connection pool
engine = create_engine(
    DATABASE_URL,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
)


def init_db():
    """
    Creates normalized relational database tables:
    1. buildings (Dimension)
    2. meters (Dimension, foreign key to buildings)
    3. energy_readings (Fact / Time-series, foreign key to meters)
    4. alerts (Events / Anomalies, foreign key to meters)
    """
    schema_sql = """
    -- 1. Buildings Dimension Table
    CREATE TABLE IF NOT EXISTS buildings (
        building_id VARCHAR(64) PRIMARY KEY,
        building_name VARCHAR(128) NOT NULL,
        category VARCHAR(64) NOT NULL,
        created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
    );

    -- 2. Meters Dimension Table
    CREATE TABLE IF NOT EXISTS meters (
        meter_id VARCHAR(32) PRIMARY KEY,
        building_id VARCHAR(64) NOT NULL REFERENCES buildings(building_id) ON DELETE CASCADE,
        meter_type VARCHAR(64) DEFAULT 'Smart Sub-Meter',
        status VARCHAR(32) DEFAULT 'ACTIVE',
        created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
    );

    -- 3. Energy Readings Fact Table
    CREATE TABLE IF NOT EXISTS energy_readings (
        id BIGSERIAL PRIMARY KEY,
        event_id VARCHAR(32) NOT NULL,
        timestamp TIMESTAMP WITHOUT TIME ZONE NOT NULL,
        meter_id VARCHAR(32) NOT NULL REFERENCES meters(meter_id) ON DELETE CASCADE,
        power_kw NUMERIC(8, 2) NOT NULL,
        voltage_v NUMERIC(8, 2) NOT NULL,
        current_a NUMERIC(8, 2) NOT NULL,
        power_factor NUMERIC(5, 3) NOT NULL,
        created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
    );

    -- 4. Alerts & Anomalies Table
    CREATE TABLE IF NOT EXISTS alerts (
        id BIGSERIAL PRIMARY KEY,
        event_id VARCHAR(32) NOT NULL,
        timestamp TIMESTAMP WITHOUT TIME ZONE NOT NULL,
        meter_id VARCHAR(32) NOT NULL REFERENCES meters(meter_id) ON DELETE CASCADE,
        alert_type VARCHAR(64) NOT NULL,
        severity VARCHAR(32) NOT NULL,
        metric_value NUMERIC(8, 2) NOT NULL,
        threshold_value NUMERIC(8, 2) NOT NULL,
        description TEXT,
        created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
    );

    -- 5. Building Energy Aggregates (Real-time Analytics)
    CREATE TABLE IF NOT EXISTS building_energy_aggregates (
        id BIGSERIAL PRIMARY KEY,
        window_start TIMESTAMP WITHOUT TIME ZONE NOT NULL,
        window_end TIMESTAMP WITHOUT TIME ZONE NOT NULL,
        building_id VARCHAR(64) NOT NULL REFERENCES buildings(building_id) ON DELETE CASCADE,
        avg_power_kw NUMERIC(8, 2) NOT NULL,
        avg_voltage_v NUMERIC(8, 2) NOT NULL,
        avg_power_factor NUMERIC(5, 3) NOT NULL,
        created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
    );

    -- Optimized B-Tree Indexes
    CREATE INDEX IF NOT EXISTS idx_readings_timestamp ON energy_readings (timestamp DESC);
    CREATE INDEX IF NOT EXISTS idx_readings_meter_id ON energy_readings (meter_id);
    CREATE INDEX IF NOT EXISTS idx_readings_meter_time ON energy_readings (meter_id, timestamp DESC);
    CREATE INDEX IF NOT EXISTS idx_alerts_timestamp ON alerts (timestamp DESC);
    CREATE INDEX IF NOT EXISTS idx_alerts_meter_id ON alerts (meter_id);
    CREATE INDEX IF NOT EXISTS idx_aggregates_window ON building_energy_aggregates (window_end DESC);
    """
    with engine.begin() as conn:
        conn.execute(text(schema_sql))
    print("[DB] Initialized normalized relational schema (buildings, meters, energy_readings, alerts).")


def seed_dimensions(campus_infrastructure):
    """
    Populates the 'buildings' and 'meters' dimension tables.
    """
    init_db()

    building_records = []
    meter_records = []
    meter_number = 1

    for category, bldgs in campus_infrastructure.items():
        for bldg_id, count in bldgs.items():
            building_records.append((bldg_id, bldg_id, category))
            for _ in range(count):
                meter_id = f"M{meter_number:03d}"
                meter_records.append((meter_id, bldg_id, "Smart Sub-Meter", "ACTIVE"))
                meter_number += 1

    raw_conn = engine.raw_connection()
    try:
        with raw_conn.cursor() as cur:
            bldg_sql = """
            INSERT INTO buildings (building_id, building_name, category)
            VALUES %s
            ON CONFLICT (building_id) DO UPDATE 
            SET category = EXCLUDED.category;
            """
            execute_values(cur, bldg_sql, building_records)

            meter_sql = """
            INSERT INTO meters (meter_id, building_id, meter_type, status)
            VALUES %s
            ON CONFLICT (meter_id) DO UPDATE 
            SET building_id = EXCLUDED.building_id;
            """
            execute_values(cur, meter_sql, meter_records)

        raw_conn.commit()
        print(f"[DB] Seeded {len(building_records)} buildings and {len(meter_records)} meters dimensions.")
    finally:
        raw_conn.close()


def insert_readings_and_alerts(readings, v_min=220.0, v_max=240.0, pf_min=0.88):
    """
    Bulk inserts telemetry into `energy_readings` and logs any anomalies to `alerts`.
    """
    if not readings:
        return 0, 0

    readings_data = []
    alerts_data = []

    for r in readings:
        readings_data.append((
            r["event_id"],
            r["timestamp"],
            r["meter_id"],
            r["power_kw"],
            r["voltage_v"],
            r["current_a"],
            r["power_factor"],
        ))

        volt = float(r["voltage_v"])
        pf = float(r["power_factor"])

        if volt < v_min:
            alerts_data.append((
                r["event_id"],
                r["timestamp"],
                r["meter_id"],
                "VOLTAGE_SAG",
                "CRITICAL",
                volt,
                v_min,
                f"Voltage dropped to {volt:.1f}V (under standard {v_min}V threshold)",
            ))
        elif volt > v_max:
            alerts_data.append((
                r["event_id"],
                r["timestamp"],
                r["meter_id"],
                "VOLTAGE_SURGE",
                "WARNING",
                volt,
                v_max,
                f"Voltage spiked to {volt:.1f}V (over standard {v_max}V threshold)",
            ))

        if pf < pf_min:
            alerts_data.append((
                r["event_id"],
                r["timestamp"],
                r["meter_id"],
                "LOW_POWER_FACTOR",
                "WARNING",
                pf,
                pf_min,
                f"Power factor degraded to {pf:.3f} (below target {pf_min})",
            ))

    raw_conn = engine.raw_connection()
    try:
        with raw_conn.cursor() as cur:
            readings_sql = """
            INSERT INTO energy_readings (
                event_id, timestamp, meter_id, power_kw, voltage_v, current_a, power_factor
            ) VALUES %s
            """
            execute_values(cur, readings_sql, readings_data, page_size=2000)

            if alerts_data:
                alerts_sql = """
                INSERT INTO alerts (
                    event_id, timestamp, meter_id, alert_type, severity, metric_value, threshold_value, description
                ) VALUES %s
                """
                execute_values(cur, alerts_sql, alerts_data, page_size=1000)

        raw_conn.commit()
        return len(readings_data), len(alerts_data)
    finally:
        raw_conn.close()


insert_readings_bulk = insert_readings_and_alerts


def load_telemetry_with_joins(limit=25000, category=None, building=None, meter=None, date_from=None, date_to=None):
    """
    Executes relational SQL JOINs across buildings, meters, and energy_readings,
    returning a clean Pandas DataFrame.
    """
    conditions = []
    params = {}

    if category and category != "All Categories":
        conditions.append("b.category = :category")
        params["category"] = category
    if building and building != "All Buildings":
        conditions.append("b.building_id = :building")
        params["building"] = building
    if meter and meter != "All Meters":
        conditions.append("m.meter_id = :meter")
        params["meter"] = meter
    if date_from:
        conditions.append("r.timestamp >= :date_from")
        params["date_from"] = date_from
    if date_to:
        conditions.append("r.timestamp <= :date_to")
        params["date_to"] = date_to

    where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

    query = f"""
    SELECT 
        r.id,
        r.event_id,
        r.timestamp,
        r.meter_id,
        m.building_id,
        b.category AS building_type,
        b.building_name,
        CAST(r.power_kw AS FLOAT) AS power_kw,
        CAST(r.voltage_v AS FLOAT) AS voltage_v,
        CAST(r.current_a AS FLOAT) AS current_a,
        CAST(r.power_factor AS FLOAT) AS power_factor
    FROM energy_readings r
    JOIN meters m ON r.meter_id = m.meter_id
    JOIN buildings b ON m.building_id = b.building_id
    {where_clause}
    ORDER BY r.timestamp DESC
    LIMIT {limit};
    """

    with engine.connect() as conn:
        df = pd.read_sql(text(query), conn, params=params)

    if not df.empty:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df["hour"] = df["timestamp"].dt.hour
        df["day_name"] = df["timestamp"].dt.day_name()
        df["day_of_week"] = df["timestamp"].dt.dayofweek
        df["is_weekend"] = df["day_of_week"].isin([5, 6])
        df["day_type"] = df["is_weekend"].apply(lambda x: "Weekend" if x else "Weekday")

    return df


load_readings_from_db = load_telemetry_with_joins


def load_alerts_from_db(limit=500):
    """
    Fetches alert logs joined with building and meter information.
    """
    query = f"""
    SELECT 
        a.id,
        a.event_id,
        a.timestamp,
        a.meter_id,
        m.building_id,
        b.category AS building_type,
        a.alert_type,
        a.severity,
        CAST(a.metric_value AS FLOAT) AS metric_value,
        CAST(a.threshold_value AS FLOAT) AS threshold_value,
        a.description
    FROM alerts a
    JOIN meters m ON a.meter_id = m.meter_id
    JOIN buildings b ON m.building_id = b.building_id
    ORDER BY a.timestamp DESC
    LIMIT {limit};
    """
    with engine.connect() as conn:
        df_alerts = pd.read_sql(text(query), conn)

    if not df_alerts.empty:
        df_alerts["timestamp"] = pd.to_datetime(df_alerts["timestamp"])
    return df_alerts


def load_streaming_aggregates(limit=1000):
    """
    Fetches the real-time sliding window aggregates populated by Spark Structured Streaming.
    """
    query = f"""
    SELECT 
        a.id,
        a.window_start,
        a.window_end,
        a.building_id,
        b.building_name,
        b.category AS building_type,
        CAST(a.avg_power_kw AS FLOAT) AS avg_power_kw,
        CAST(a.avg_voltage_v AS FLOAT) AS avg_voltage_v,
        CAST(a.avg_power_factor AS FLOAT) AS avg_power_factor
    FROM building_energy_aggregates a
    JOIN buildings b ON a.building_id = b.building_id
    ORDER BY a.window_end DESC
    LIMIT {limit};
    """
    with engine.connect() as conn:
        df_agg = pd.read_sql(text(query), conn)

    if not df_agg.empty:
        df_agg["window_start"] = pd.to_datetime(df_agg["window_start"])
        df_agg["window_end"] = pd.to_datetime(df_agg["window_end"])
    return df_agg


def get_db_stats():
    """Returns metadata summary of the database schema."""
    query = """
    SELECT 
        (SELECT COUNT(*) FROM buildings) AS building_count,
        (SELECT COUNT(*) FROM meters) AS meter_count,
        (SELECT COUNT(*) FROM energy_readings) AS readings_count,
        (SELECT COUNT(*) FROM alerts) AS alerts_count,
        (SELECT COUNT(*) FROM building_energy_aggregates) AS aggregates_count,
        (SELECT MIN(timestamp) FROM energy_readings) AS earliest_reading,
        (SELECT MAX(timestamp) FROM energy_readings) AS latest_reading;
    """
    with engine.connect() as conn:
        res = conn.execute(text(query)).fetchone()
        if res:
            return {
                "building_count": res[0] or 0,
                "meter_count": res[1] or 0,
                "readings_count": res[2] or 0,
                "alerts_count": res[3] or 0,
                "aggregates_count": res[4] or 0,
                "earliest_reading": str(res[5]) if res[5] else "N/A",
                "latest_reading": str(res[6]) if res[6] else "N/A",
            }
    return {}


if __name__ == "__main__":
    init_db()
    stats = get_db_stats()
    print(f"[DB STATS] {stats}")
