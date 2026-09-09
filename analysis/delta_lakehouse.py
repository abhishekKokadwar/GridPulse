"""
GridPulse Enterprise ACID Data Lakehouse Engine (Delta Lake + DuckDB)
Implements:
1. ACID Transactions with atomic commit log (_delta_log/*.json)
2. In-Place Compaction (OPTIMIZE) eliminating small-file fragmentation
3. Time-Travel Auditing (querying by version number or timestamp)
4. Schema Evolution (e.g. ambient_temp_c, humidity_pct with schema_mode="merge")
5. Vectorized DuckDB In-Process Analytical SQL Execution
"""

import os
import sys
import time
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple
import pandas as pd
import duckdb
import pyarrow as pa
import pyarrow.dataset as ds
from deltalake import DeltaTable, write_deltalake

# Add project root to sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

DEFAULT_DELTA_PATH = os.path.join(PROJECT_ROOT, "data", "lakehouse", "delta", "campus_telemetry")
DEFAULT_PARQUET_LAKE = os.path.join(PROJECT_ROOT, "data", "lake", "raw_telemetry")


class DeltaLakehouseManager:
    """
    High-level manager for the GridPulse ACID Delta Lakehouse.
    Integrates Python deltalake with DuckDB for vectorized analytical queries.
    """

    def __init__(
        self,
        table_path: str = DEFAULT_DELTA_PATH,
        parquet_source: str = DEFAULT_PARQUET_LAKE,
    ):
        self.table_path = table_path.replace("\\", "/")
        self.parquet_source = parquet_source.replace("\\", "/")
        os.makedirs(os.path.dirname(self.table_path), exist_ok=True)

    def is_initialized(self) -> bool:
        """Checks if a valid Delta Lake table exists at table_path."""
        try:
            DeltaTable(self.table_path)
            return True
        except Exception:
            return False

    def get_table(self, version: Optional[int] = None) -> DeltaTable:
        """Returns the DeltaTable instance, optionally at a specific historical version."""
        if version is not None:
            return DeltaTable(self.table_path, version=version)
        return DeltaTable(self.table_path)

    def initialize_from_parquet(
        self,
        partition_by: Optional[List[str]] = None,
        max_records: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Reads cold-path partitioned Parquet lake and converts it into an ACID Delta Lake table.
        Creates Commit Version 0 in _delta_log.
        """
        if not os.path.exists(self.parquet_source):
            raise FileNotFoundError(f"Source Parquet lake not found at: {self.parquet_source}")

        if partition_by is None:
            partition_by = ["year", "month", "day"]

        t0 = time.time()
        # Read partitioned dataset via PyArrow
        dataset = ds.dataset(self.parquet_source, format="parquet", partitioning="hive")
        table = dataset.to_table()
        if max_records and len(table) > max_records:
            table = table.slice(0, max_records)

        # Atomic write to Delta Lake
        write_deltalake(
            self.table_path,
            table,
            partition_by=partition_by,
            mode="overwrite",
        )
        elapsed_sec = round(time.time() - t0, 3)

        dt = self.get_table()
        return {
            "status": "INITIALIZED",
            "total_records": len(table),
            "version": dt.version(),
            "partitions": partition_by,
            "elapsed_sec": elapsed_sec,
            "table_path": self.table_path,
        }

    def append_batch(
        self,
        records: pd.DataFrame,
        schema_mode: str = "merge",
    ) -> Dict[str, Any]:
        """
        Appends a streaming micro-batch of telemetry to the Delta Lake table atomically.
        """
        t0 = time.time()
        write_deltalake(
            self.table_path,
            records,
            mode="append",
            schema_mode=schema_mode,
        )
        dt = self.get_table()
        elapsed_ms = round((time.time() - t0) * 1000, 2)

        return {
            "status": "COMMITTED",
            "operation": "APPEND",
            "records_appended": len(records),
            "new_version": dt.version(),
            "elapsed_ms": elapsed_ms,
        }

    def simulate_schema_evolution(
        self,
        batch_size: int = 42,
    ) -> Dict[str, Any]:
        """
        Demonstrates Schema Evolution:
        Ingests a micro-batch containing NEW sensor fields (ambient_temp_c, humidity_pct)
        using schema_mode='merge'. The Delta log updates schema metadata without rewriting
        historical Parquet files. Downstream queries on earlier data return NULL seamlessly.
        """
        if not self.is_initialized():
            self.initialize_from_parquet()

        now = datetime.now()
        new_records = []
        for i in range(1, batch_size + 1):
            meter_id = f"M{i:03d}"
            bldg_id = f"BH{(i % 4) + 1}"
            new_records.append({
                "event_id": f"EVT_EVOLVED_{int(now.timestamp())}_{i:03d}",
                "timestamp": now,
                "meter_id": meter_id,
                "building_id": bldg_id,
                "building_type": "Hostels",
                "power_kw": round(25.0 + (i * 0.8), 2),
                "voltage_v": round(230.0 + (i % 5) - 2.5, 1),
                "current_a": round(10.0 + (i * 0.3), 2),
                "power_factor": 0.95,
                "year": now.year,
                "month": now.month,
                "day": now.day,
                # New sensor dimensions for IoT Edge weather station integration:
                "ambient_temp_c": round(28.5 + (i * 0.1), 1),
                "humidity_pct": round(58.0 + (i % 10), 1),
            })

        df_evolved = pd.DataFrame(new_records)
        res = self.append_batch(df_evolved, schema_mode="merge")
        res["new_columns_introduced"] = ["ambient_temp_c", "humidity_pct"]
        return res

    def optimize_and_compact(self) -> Dict[str, Any]:
        """
        Executes In-Place Compaction using native Delta Lake OPTIMIZE.
        Consolidates fragmented micro-batch part files into optimal file sizes
        and logs an OPTIMIZE transaction in _delta_log.
        """
        if not self.is_initialized():
            raise RuntimeError("Delta Lake table not initialized.")

        t0 = time.time()
        dt = DeltaTable(self.table_path)
        metrics = dt.optimize.compact()
        elapsed_sec = round(time.time() - t0, 3)

        dt_after = DeltaTable(self.table_path)
        return {
            "status": "OPTIMIZED",
            "operation": "COMPACTION",
            "new_version": dt_after.version(),
            "elapsed_sec": elapsed_sec,
            "metrics": metrics,
        }

    def get_commit_history(self) -> List[Dict[str, Any]]:
        """
        Returns full ACID commit history from the Delta transaction log (_delta_log).
        """
        if not self.is_initialized():
            return []

        dt = DeltaTable(self.table_path)
        history = dt.history()
        cleaned_history = []
        for h in history:
            ts_ms = h.get("timestamp")
            dt_str = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC") if ts_ms else "N/A"
            cleaned_history.append({
                "version": h.get("version"),
                "operation": h.get("operation"),
                "timestamp": dt_str,
                "raw_timestamp": ts_ms,
                "engineInfo": h.get("engineInfo", "deltalake-python"),
                "operationParameters": h.get("operationParameters", {}),
            })
        return cleaned_history

    def query_time_travel(
        self,
        version: Optional[int] = None,
        sql: Optional[str] = None,
        limit: Optional[int] = 1000,
    ) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        """
        Executes zero-copy vectorized DuckDB SQL over a specific historical snapshot.
        If version is None, queries the latest snapshot.
        """
        if not self.is_initialized():
            return pd.DataFrame(), {"error": "Delta Lake table not initialized"}

        t0 = time.time()
        dt = self.get_table(version=version)
        curr_version = dt.version()
        arrow_ds = dt.to_pyarrow_dataset()

        con = duckdb.connect()
        try:
            total_rows = con.execute("SELECT COUNT(*) FROM arrow_ds").fetchone()[0]
            if sql is None:
                if limit:
                    query_str = f"SELECT * FROM arrow_ds LIMIT {limit}"
                else:
                    query_str = "SELECT * FROM arrow_ds"
            else:
                query_str = sql.replace("campus_telemetry", "arrow_ds")

            df = con.execute(query_str).df()
            elapsed_ms = round((time.time() - t0) * 1000, 2)

            meta = {
                "version_queried": curr_version,
                "row_count": len(df),
                "total_rows": total_rows,
                "columns": list(df.columns),
                "elapsed_ms": elapsed_ms,
                "has_temperature_sensor": "ambient_temp_c" in df.columns,
            }
            return df, meta
        finally:
            con.close()

    def compare_snapshots(
        self,
        version_a: int,
        version_b: int,
    ) -> Dict[str, Any]:
        """
        Compares two historical snapshots across record count, columns, and sensor schema.
        """
        dt_a = self.get_table(version=version_a)
        dt_b = self.get_table(version=version_b)

        cols_a = [f.name for f in dt_a.schema().fields]
        cols_b = [f.name for f in dt_b.schema().fields]

        con = duckdb.connect()
        try:
            ds_a = dt_a.to_pyarrow_dataset()
            ds_b = dt_b.to_pyarrow_dataset()
            count_a = con.execute("SELECT COUNT(*) FROM ds_a").fetchone()[0]
            count_b = con.execute("SELECT COUNT(*) FROM ds_b").fetchone()[0]
        finally:
            con.close()

        added_cols = list(set(cols_b) - set(cols_a))
        removed_cols = list(set(cols_a) - set(cols_b))

        return {
            "version_a": version_a,
            "version_b": version_b,
            "rows_a": count_a,
            "rows_b": count_b,
            "row_delta": count_b - count_a,
            "columns_a": cols_a,
            "columns_b": cols_b,
            "added_columns": added_cols,
            "removed_columns": removed_cols,
            "schema_evolved": len(added_cols) > 0,
        }


# Singleton accessor
_lakehouse_instance: Optional[DeltaLakehouseManager] = None


def get_delta_lakehouse(table_path: str = DEFAULT_DELTA_PATH) -> DeltaLakehouseManager:
    """Returns singleton manager instance for Delta Lake."""
    global _lakehouse_instance
    if _lakehouse_instance is None or _lakehouse_instance.table_path != table_path.replace("\\", "/"):
        _lakehouse_instance = DeltaLakehouseManager(table_path=table_path)
    return _lakehouse_instance


if __name__ == "__main__":
    print("[DELTA LAKEHOUSE MODULE TEST]")
    mgr = get_delta_lakehouse()
    if not mgr.is_initialized():
        print("Initializing Delta Lake table from Parquet...")
        res = mgr.initialize_from_parquet()
        print("Initialization:", res)
    else:
        print("Delta Lake table already initialized at version:", mgr.get_table().version())

    history = mgr.get_commit_history()
    print("History length:", len(history))
    sample_df, meta = mgr.query_time_travel()
    print("Latest query sample rows:", len(sample_df), "Meta:", meta)
