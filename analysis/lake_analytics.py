"""
GridPulse Cold Path Data Lakehouse Analytics Engine (Phase 5)
Leverages DuckDB and PyArrow for high-velocity columnar SQL execution
and partition pruning directly over partitioned Snappy Parquet telemetry.
"""

import os
import sys
import time
from datetime import datetime, date
from typing import Dict, Any, List, Optional
import pandas as pd
import duckdb

# Add project root to sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

DEFAULT_LAKE_PATH = os.path.join(PROJECT_ROOT, "data", "lake", "raw_telemetry")


def get_parquet_glob(lake_path: str = DEFAULT_LAKE_PATH) -> str:
    """Returns the glob pattern for all Parquet files in the lake."""
    return os.path.join(lake_path, "**", "*.parquet").replace("\\", "/")


def get_lake_metadata(lake_path: str = DEFAULT_LAKE_PATH) -> Dict[str, Any]:
    """
    Inspects the Parquet data lake on disk and queries DuckDB for summary stats.
    Returns partition counts, file counts, file sizes, and date bounds.
    """
    if not os.path.exists(lake_path):
        return {
            "exists": False,
            "total_files": 0,
            "total_size_mb": 0.0,
            "partitions": [],
            "total_records": 0,
            "min_timestamp": None,
            "max_timestamp": None,
            "meters_count": 0,
            "buildings_count": 0,
        }

    parquet_files = []
    total_bytes = 0
    partitions_set = set()

    for root, dirs, files in os.walk(lake_path):
        for f in files:
            if f.endswith(".parquet"):
                full_p = os.path.join(root, f)
                parquet_files.append(full_p)
                total_bytes += os.path.getsize(full_p)
                # Partition directory detection (e.g. year=2026/month=8/day=23)
                rel = os.path.relpath(root, lake_path)
                if rel != ".":
                    partitions_set.add(rel.replace("\\", "/"))

    if not parquet_files:
        return {
            "exists": True,
            "total_files": 0,
            "total_size_mb": 0.0,
            "partitions": [],
            "total_records": 0,
            "min_timestamp": None,
            "max_timestamp": None,
            "meters_count": 0,
            "buildings_count": 0,
        }

    total_size_mb = round(total_bytes / (1024 * 1024), 2)
    glob_pattern = get_parquet_glob(lake_path)

    con = duckdb.connect()
    try:
        query = f"""
            SELECT 
                COUNT(*) as total_records,
                MIN(timestamp) as min_ts,
                MAX(timestamp) as max_ts,
                COUNT(DISTINCT meter_id) as meters_count,
                COUNT(DISTINCT building_id) as buildings_count
            FROM read_parquet('{glob_pattern}', hive_partitioning=1)
        """
        res = con.execute(query).fetchone()
        total_records = res[0] or 0
        min_ts = res[1]
        max_ts = res[2]
        meters_count = res[3] or 0
        buildings_count = res[4] or 0
    except Exception as e:
        print(f"[LAKE QUERY ERROR] Metadata extraction failed: {e}")
        total_records = 0
        min_ts = None
        max_ts = None
        meters_count = 0
        buildings_count = 0
    finally:
        con.close()

    return {
        "exists": True,
        "total_files": len(parquet_files),
        "total_size_mb": total_size_mb,
        "partitions": sorted(list(partitions_set)),
        "total_records": total_records,
        "min_timestamp": min_ts,
        "max_timestamp": max_ts,
        "meters_count": meters_count,
        "buildings_count": buildings_count,
    }


def query_lake_telemetry(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    building_ids: Optional[List[str]] = None,
    building_type: Optional[str] = None,
    limit: int = 2000,
    lake_path: str = DEFAULT_LAKE_PATH,
) -> pd.DataFrame:
    """
    Queries partitioned Parquet lake with column projection and partition pruning.
    """
    glob_pattern = get_parquet_glob(lake_path)
    con = duckdb.connect()

    where_clauses = ["1=1"]

    if start_date:
        where_clauses.append(f"timestamp >= '{start_date.strftime('%Y-%m-%d 00:00:00')}'")
    if end_date:
        where_clauses.append(f"timestamp <= '{end_date.strftime('%Y-%m-%d 23:59:59')}'")
    if building_ids:
        b_list = "', '".join(building_ids)
        where_clauses.append(f"building_id IN ('{b_list}')")
    if building_type and building_type != "All":
        where_clauses.append(f"building_type = '{building_type}'")

    where_sql = " AND ".join(where_clauses)
    sql = f"""
        SELECT 
            event_id,
            timestamp,
            meter_id,
            building_id,
            building_type,
            power_kw,
            voltage_v,
            current_a,
            power_factor
        FROM read_parquet('{glob_pattern}', hive_partitioning=1)
        WHERE {where_sql}
        ORDER BY timestamp DESC
        LIMIT {limit}
    """

    try:
        t0 = time.time()
        df = con.execute(sql).df()
        elapsed_ms = round((time.time() - t0) * 1000, 2)
        print(f"[LAKE QUERY] Fetched {len(df)} rows in {elapsed_ms} ms.")
        return df
    except Exception as e:
        print(f"[LAKE QUERY ERROR] {e}")
        return pd.DataFrame()
    finally:
        con.close()


def query_lake_hourly_profile(
    building_id: Optional[str] = None,
    building_type: Optional[str] = None,
    lake_path: str = DEFAULT_LAKE_PATH,
) -> pd.DataFrame:
    """
    Computes 24-hour Diurnal Profile (0-23 hours) across the lake using DuckDB.
    """
    glob_pattern = get_parquet_glob(lake_path)
    con = duckdb.connect()

    where_clauses = ["1=1"]
    if building_id and building_id != "All":
        where_clauses.append(f"building_id = '{building_id}'")
    if building_type and building_type != "All":
        where_clauses.append(f"building_type = '{building_type}'")

    where_sql = " AND ".join(where_clauses)

    sql = f"""
        SELECT 
            EXTRACT(hour FROM timestamp) as hour,
            ROUND(AVG(power_kw), 2) as avg_power_kw,
            ROUND(MIN(power_kw), 2) as min_power_kw,
            ROUND(MAX(power_kw), 2) as max_power_kw,
            ROUND(AVG(voltage_v), 2) as avg_voltage_v,
            ROUND(AVG(power_factor), 3) as avg_power_factor,
            COUNT(*) as reading_count
        FROM read_parquet('{glob_pattern}', hive_partitioning=1)
        WHERE {where_sql}
        GROUP BY 1
        ORDER BY 1
    """

    try:
        df = con.execute(sql).df()
        return df
    except Exception as e:
        print(f"[LAKE QUERY ERROR] Hourly profile failed: {e}")
        return pd.DataFrame()
    finally:
        con.close()


def query_lake_building_summary(lake_path: str = DEFAULT_LAKE_PATH) -> pd.DataFrame:
    """
    Returns aggregated power consumption and meter counts grouped by building.
    """
    glob_pattern = get_parquet_glob(lake_path)
    con = duckdb.connect()

    sql = f"""
        SELECT 
            building_id,
            building_type,
            COUNT(DISTINCT meter_id) as meter_count,
            ROUND(AVG(power_kw), 2) as avg_power_kw,
            ROUND(MAX(power_kw), 2) as max_power_kw,
            ROUND(SUM(power_kw * (15.0 / 60.0)), 2) as est_total_kwh,
            COUNT(*) as total_readings
        FROM read_parquet('{glob_pattern}', hive_partitioning=1)
        GROUP BY building_id, building_type
        ORDER BY avg_power_kw DESC
    """

    try:
        df = con.execute(sql).df()
        return df
    except Exception as e:
        print(f"[LAKE QUERY ERROR] Building summary failed: {e}")
        return pd.DataFrame()
    finally:
        con.close()


def benchmark_query_performance(lake_path: str = DEFAULT_LAKE_PATH) -> Dict[str, Any]:
    """
    Benchmarks cold-path DuckDB Parquet scan vs PostgreSQL query (if DB is accessible).
    """
    glob_pattern = get_parquet_glob(lake_path)
    con = duckdb.connect()

    lake_time_ms = 0.0
    db_time_ms = None
    row_count = 0

    # 1. Benchmark DuckDB
    try:
        t0 = time.time()
        sql = f"""
            SELECT building_type, COUNT(*), AVG(power_kw), MAX(power_kw)
            FROM read_parquet('{glob_pattern}', hive_partitioning=1)
            GROUP BY building_type
        """
        res = con.execute(sql).fetchall()
        lake_time_ms = round((time.time() - t0) * 1000, 2)
        row_count = sum(r[1] for r in res)
    except Exception as e:
        print(f"[BENCHMARK] DuckDB error: {e}")
    finally:
        con.close()

    # 2. Benchmark PostgreSQL if available
    try:
        from database.db import engine, DB_AVAILABLE
        if DB_AVAILABLE:
            from sqlalchemy import text
            t0 = time.time()
            with engine.connect() as conn:
                pg_sql = text("""
                    SELECT b.category, COUNT(*), AVG(er.power_kw), MAX(er.power_kw)
                    FROM energy_readings er
                    JOIN meters m ON er.meter_id = m.meter_id
                    JOIN buildings b ON m.building_id = b.building_id
                    GROUP BY b.category
                """)
                conn.execute(pg_sql).fetchall()
            db_time_ms = round((time.time() - t0) * 1000, 2)
    except Exception:
        db_time_ms = None

    return {
        "lake_time_ms": lake_time_ms,
        "db_time_ms": db_time_ms,
        "scanned_rows": row_count,
        "speedup_ratio": round(db_time_ms / lake_time_ms, 1) if (db_time_ms and lake_time_ms > 0) else None,
    }


def query_lake(sql_query: str, lake_path: str = DEFAULT_LAKE_PATH) -> pd.DataFrame:
    """
    Executes an arbitrary SQL query against the Parquet data lake using DuckDB.
    Creates a temporary virtual table `telemetry_lake` mapped to the parquet files.
    """
    glob_pattern = get_parquet_glob(lake_path)
    con = duckdb.connect()
    try:
        con.execute(f"""
            CREATE OR REPLACE VIEW telemetry_lake AS 
            SELECT * FROM read_parquet('{glob_pattern}', hive_partitioning=1);
        """)
        return con.execute(sql_query).df()
    finally:
        con.close()



if __name__ == "__main__":
    print("[LAKE ANALYTICS ENGINE TEST]")
    meta = get_lake_metadata()
    print("Lake Metadata:", meta)
    if meta["exists"] and meta["total_records"] > 0:
        sample_df = query_lake_telemetry(limit=5)
        print("\nSample Telemetry:\n", sample_df)
        bench = benchmark_query_performance()
        print("\nBenchmark:", bench)
