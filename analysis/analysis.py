import os
import sys
import pandas as pd
import numpy as np

# Add project root to path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    from database.db import (
        load_telemetry_with_joins,
        load_alerts_from_db,
        get_db_stats,
        engine,
    )
    from sqlalchemy import text
    DB_AVAILABLE = True
except Exception:
    DB_AVAILABLE = False


def load_energy_data_from_db(limit=25000, category=None, building=None, meter=None, date_from=None, date_to=None):
    """
    Step 5: Load data from PostgreSQL using SQL JOINs into a Pandas DataFrame.
    Relationship: buildings (1) -> meters (N) -> energy_readings (N)
    """
    if not DB_AVAILABLE:
        raise RuntimeError("Database module not available. Fallback to CSV.")
    
    return load_telemetry_with_joins(
        limit=limit,
        category=category,
        building=building,
        meter=meter,
        date_from=date_from,
        date_to=date_to,
    )


def load_energy_data(filepath="data/raw/energy_data.csv"):
    """
    Loads raw energy CSV into a clean Pandas DataFrame (Phase-1 fallback).
    """
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"File not found: {filepath}. Please run simulator first.")

    df = pd.read_csv(filepath)

    df["timestamp"] = pd.to_datetime(df["timestamp"])
    numeric_cols = ["power_kw", "voltage_v", "current_a", "power_factor"]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["hour"] = df["timestamp"].dt.hour
    df["day_name"] = df["timestamp"].dt.day_name()
    df["day_of_week"] = df["timestamp"].dt.dayofweek
    df["is_weekend"] = df["day_of_week"].isin([5, 6])
    df["day_type"] = np.where(df["is_weekend"], "Weekend", "Weekday")

    df = df.dropna().reset_index(drop=True)
    return df


def calculate_kpis(df):
    """
    Calculates high-level system KPIs on the DataFrame.
    """
    if df.empty:
        return {}

    total_records = len(df)
    total_buildings = df["building_id"].nunique()
    total_categories = df["building_type"].nunique() if "building_type" in df.columns else 0
    total_meters = df["meter_id"].nunique()

    latest_timestamp = df["timestamp"].max()
    earliest_timestamp = df["timestamp"].min()

    # Instantaneous snapshot (latest reading per meter)
    latest_readings = df.sort_values("timestamp").groupby("meter_id").last()
    current_total_load_kw = latest_readings["power_kw"].sum()
    avg_voltage = latest_readings["voltage_v"].mean()
    avg_pf = latest_readings["power_factor"].mean()

    # Aggregates across entire dataset
    avg_power_kw = df["power_kw"].mean()
    peak_power_kw = df["power_kw"].max()
    min_power_kw = df["power_kw"].min()

    return {
        "total_records": total_records,
        "total_categories": total_categories,
        "total_buildings": total_buildings,
        "total_meters": total_meters,
        "earliest_time": str(earliest_timestamp),
        "latest_time": str(latest_timestamp),
        "current_total_load_kw": round(current_total_load_kw, 2),
        "avg_voltage": round(avg_voltage, 2),
        "avg_power_factor": round(avg_pf, 3),
        "avg_power_kw": round(avg_power_kw, 2),
        "peak_power_kw": round(peak_power_kw, 2),
        "min_power_kw": round(min_power_kw, 2),
    }


def get_building_summary(df):
    """
    Aggregates metrics grouped by building and its category.
    """
    group_cols = ["building_id", "building_type"] if "building_type" in df.columns else ["building_id"]
    summary = df.groupby(group_cols).agg(
        total_energy_kw_sum=("power_kw", "sum"),
        avg_power_kw=("power_kw", "mean"),
        peak_power_kw=("power_kw", "max"),
        avg_voltage_v=("voltage_v", "mean"),
        avg_current_a=("current_a", "mean"),
        avg_power_factor=("power_factor", "mean"),
        meter_count=("meter_id", "nunique"),
        reading_count=("event_id", "count"),
    ).reset_index()

    for col in ["total_energy_kw_sum", "avg_power_kw", "peak_power_kw", "avg_voltage_v", "avg_current_a"]:
        summary[col] = summary[col].round(2)
    summary["avg_power_factor"] = summary["avg_power_factor"].round(3)

    return summary.sort_values(by="avg_power_kw", ascending=False).reset_index(drop=True)


def get_meter_summary(df):
    """
    Aggregates metrics grouped by meter.
    """
    group_cols = ["meter_id", "building_id", "building_type"] if "building_type" in df.columns else ["meter_id", "building_id"]
    summary = df.groupby(group_cols).agg(
        avg_power_kw=("power_kw", "mean"),
        peak_power_kw=("power_kw", "max"),
        avg_voltage_v=("voltage_v", "mean"),
        avg_current_a=("current_a", "mean"),
        avg_power_factor=("power_factor", "mean"),
        reading_count=("event_id", "count"),
    ).reset_index()

    for col in ["avg_power_kw", "peak_power_kw", "avg_voltage_v", "avg_current_a"]:
        summary[col] = summary[col].round(2)
    summary["avg_power_factor"] = summary["avg_power_factor"].round(3)

    return summary.sort_values(by="avg_power_kw", ascending=False).reset_index(drop=True)


def get_category_summary(df):
    """
    Aggregates metrics grouped by category (Hostels, Departments, Lecture Theatres, Facilities).
    """
    if "building_type" not in df.columns:
        return pd.DataFrame()

    summary = df.groupby("building_type").agg(
        total_energy_kw_sum=("power_kw", "sum"),
        avg_power_kw=("power_kw", "mean"),
        peak_power_kw=("power_kw", "max"),
        avg_voltage_v=("voltage_v", "mean"),
        avg_current_a=("current_a", "mean"),
        avg_power_factor=("power_factor", "mean"),
        building_count=("building_id", "nunique"),
        meter_count=("meter_id", "nunique"),
        reading_count=("event_id", "count"),
    ).reset_index()

    for col in ["total_energy_kw_sum", "avg_power_kw", "peak_power_kw", "avg_voltage_v", "avg_current_a"]:
        summary[col] = summary[col].round(2)
    summary["avg_power_factor"] = summary["avg_power_factor"].round(3)

    return summary.sort_values(by="total_energy_kw_sum", ascending=False).reset_index(drop=True)


def get_time_series_trend(df, freq="1h", category=None):
    """
    Resamples data to show campus-wide or category-specific demand trends over time.
    """
    subset = df if category is None or "building_type" not in df.columns else df[df["building_type"] == category]
    df_ts = subset.set_index("timestamp")
    trend = df_ts.resample(freq).agg(
        total_power_kw=("power_kw", "sum"),
        avg_power_kw=("power_kw", "mean"),
        avg_voltage_v=("voltage_v", "mean"),
        avg_power_factor=("power_factor", "mean"),
    ).dropna().reset_index()

    return trend


def get_hourly_load_profile(df, group_by_category=True):
    """
    Calculates average 24-hour daily load curves (0-23h).
    """
    group_cols = ["hour", "building_type"] if group_by_category and "building_type" in df.columns else ["hour"]
    profile = df.groupby(group_cols).agg(
        avg_power_kw=("power_kw", "mean"),
        total_power_kw=("power_kw", "sum"),
        avg_voltage_v=("voltage_v", "mean"),
    ).reset_index()

    profile["avg_power_kw"] = profile["avg_power_kw"].round(2)
    return profile


def get_day_of_week_profile(df):
    """
    Calculates power consumption profile by day of week (Monday to Sunday).
    """
    day_profile = df.groupby(["day_name", "day_of_week", "building_type"]).agg(
        avg_power_kw=("power_kw", "mean"),
        total_power_kw=("power_kw", "sum"),
    ).reset_index()

    day_profile = day_profile.sort_values("day_of_week").reset_index(drop=True)
    return day_profile


def get_weekday_vs_weekend_summary(df):
    """
    Compares average power load between weekdays and weekends.
    """
    summary = df.groupby(["day_type", "building_type"]).agg(
        avg_power_kw=("power_kw", "mean"),
        peak_power_kw=("power_kw", "max"),
        reading_count=("event_id", "count"),
    ).reset_index()

    summary["avg_power_kw"] = summary["avg_power_kw"].round(2)
    summary["peak_power_kw"] = summary["peak_power_kw"].round(2)
    return summary


def detect_anomalies(df, v_min=220.0, v_max=240.0, pf_min=0.88):
    """
    Flags potential grid anomalies from the DataFrame.
    """
    voltage_sag = df[df["voltage_v"] < v_min]
    voltage_surge = df[df["voltage_v"] > v_max]
    low_pf = df[df["power_factor"] < pf_min]

    anomalies = df[
        (df["voltage_v"] < v_min)
        | (df["voltage_v"] > v_max)
        | (df["power_factor"] < pf_min)
    ].copy()

    return {
        "total_anomalies": len(anomalies),
        "voltage_sags": len(voltage_sag),
        "voltage_surges": len(voltage_surge),
        "low_power_factor": len(low_pf),
        "anomaly_records": anomalies,
    }


def save_processed_data(df, output_path="data/processed/processed_energy_data.csv"):
    """
    Saves cleaned and enriched dataset into data/processed.
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    df_proc = df.copy()
    df_proc["apparent_power_kva"] = round(df_proc["power_kw"] / df_proc["power_factor"], 2)
    df_proc["reactive_power_kvar"] = round(
        np.sqrt(np.maximum(0, df_proc["apparent_power_kva"] ** 2 - df_proc["power_kw"] ** 2)), 2
    )

    df_proc.to_csv(output_path, index=False)
    print(f"[OK] Saved processed dataset ({len(df_proc)} rows) -> {output_path}")
    return df_proc


if __name__ == "__main__":
    print("--- Phase 2 Step 5: PostgreSQL -> SQL Query -> Pandas DataFrame -> Analytics ---")
    if DB_AVAILABLE:
        stats = get_db_stats()
        print(f"[DB STATS] Buildings: {stats.get('building_count')}, Meters: {stats.get('meter_count')}, Readings: {stats.get('readings_count')}, Alerts: {stats.get('alerts_count')}")

        print("\n[SQL + PANDAS] Querying relational JOIN (buildings JOIN meters JOIN energy_readings)...")
        df_pg = load_energy_data_from_db(limit=25000)
        print(f"Loaded {len(df_pg)} rows into Pandas DataFrame from PostgreSQL.")

        kpis = calculate_kpis(df_pg)
        print("\n--- System KPIs from PostgreSQL ---")
        for k, v in kpis.items():
            print(f"  {k}: {v}")

        print("\n--- Top 5 Consuming Buildings (SQL + Pandas) ---")
        bldg_summary = get_building_summary(df_pg)
        print(bldg_summary.head())

        print("\n--- Alert Frequency from DB ---")
        df_alerts = load_alerts_from_db(limit=10)
        print(df_alerts[["event_id", "building_id", "alert_type", "severity", "metric_value"]].head())
    else:
        print("Database not available.")
