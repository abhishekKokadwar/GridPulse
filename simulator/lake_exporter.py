"""
Historical & Batch Data Lake Exporter (Phase 5)
Exports raw CSV telemetry or generates multi-day synthetic time series
directly into the partitioned Snappy Parquet Data Lake (year=YYYY/month=MM/day=DD).
"""

import argparse
import os
import sys
from datetime import datetime, timedelta
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

# Ensure project root is in sys.path and remove script dir to avoid package shadowing
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir in sys.path:
    sys.path.remove(script_dir)
PROJECT_ROOT = os.path.abspath(os.path.join(script_dir, ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from simulator.simulator import generate_historical_batch

DEFAULT_LAKE_PATH = os.path.join(PROJECT_ROOT, "data", "lake", "raw_telemetry")


def export_dataframe_to_lake(df: pd.DataFrame, lake_path: str = DEFAULT_LAKE_PATH) -> int:
    """
    Partitions a DataFrame of telemetry records by year, month, day,
    and writes Snappy-compressed Parquet files matching Spark's lake schema.
    Returns the total number of records written.
    """
    if df.empty:
        print("[LAKE EXPORTER] DataFrame is empty. No files written.")
        return 0

    df = df.copy()

    # Ensure timestamp is datetime
    if not pd.api.types.is_datetime64_any_dtype(df["timestamp"]):
        df["timestamp"] = pd.to_datetime(df["timestamp"])

    # Extract partitioning columns
    df["year"] = df["timestamp"].dt.year
    df["month"] = df["timestamp"].dt.month
    df["day"] = df["timestamp"].dt.day

    os.makedirs(lake_path, exist_ok=True)

    # PyArrow Table
    table = pa.Table.from_pandas(df, preserve_index=False)

    # Write partitioned dataset
    pq.write_to_dataset(
        table,
        root_path=lake_path,
        partition_cols=["year", "month", "day"],
        compression="snappy",
        use_dictionary=True,
        existing_data_behavior="overwrite_or_ignore",
    )

    total_records = len(df)
    unique_partitions = df[["year", "month", "day"]].drop_duplicates().to_dict(orient="records")
    print(f"[LAKE EXPORTER] Successfully wrote {total_records:,} records across {len(unique_partitions)} partitions to '{lake_path}'.")
    return total_records


def export_from_csv(csv_path: str = None, lake_path: str = DEFAULT_LAKE_PATH) -> int:
    """
    Exports raw CSV telemetry into partitioned Parquet data lake.
    Falls back to generating a 7-day realistic synthetic batch if CSV is missing.
    """
    if csv_path is None:
        csv_path = os.path.join(PROJECT_ROOT, "data", "raw", "energy_data.csv")

    if not os.path.exists(csv_path):
        print(f"[LAKE EXPORTER] Raw CSV not found at '{csv_path}'. Auto-generating 7-day telemetry into lake...")
        return generate_and_export_batch(days=7, step_minutes=30, lake_path=lake_path)

    print(f"[LAKE EXPORTER] Loading raw CSV from: {csv_path} ...")
    df = pd.read_csv(csv_path)
    return export_dataframe_to_lake(df, lake_path)


def generate_and_export_batch(days: int = 7, step_minutes: int = 15, lake_path: str = DEFAULT_LAKE_PATH) -> int:
    """Generates a synthetic historical batch and writes to data lake."""
    end_time = datetime.now()
    start_time = end_time - timedelta(days=days)
    print(f"[LAKE EXPORTER] Generating {days}-day telemetry batch ({start_time.strftime('%Y-%m-%d')} to {end_time.strftime('%Y-%m-%d')})...")
    readings = generate_historical_batch(days=days, step_minutes=step_minutes)
    df = pd.DataFrame(readings)
    return export_dataframe_to_lake(df, lake_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="GridPulse Phase 5: Parquet Data Lake Exporter")
    parser.add_argument("--from-csv", action="store_true", help="Hydrate lake using data/raw/energy_data.csv")
    parser.add_argument("--generate-days", type=int, default=None, help="Generate N days of synthetic telemetry into the lake")
    parser.add_argument("--lake-path", type=str, default=DEFAULT_LAKE_PATH, help="Target data lake root directory")

    args = parser.parse_args()

    if args.generate_days:
        generate_and_export_batch(days=args.generate_days, lake_path=args.lake_path)
    else:
        # Default behavior is to hydrate from raw CSV if available
        try:
            export_from_csv(lake_path=args.lake_path)
        except FileNotFoundError:
            print("[LAKE EXPORTER] Raw CSV not found. Generating default 7-day batch...")
            generate_and_export_batch(days=7, lake_path=args.lake_path)
