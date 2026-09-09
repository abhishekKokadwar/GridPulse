"""
Automated Test Suite for GridPulse ACID Delta Lakehouse
Validates ACID Transactions, Schema Evolution, Time-Travel, In-Place Compaction, and DuckDB SQL.
"""

import os
import sys
import unittest
import pandas as pd
import duckdb

# Add project root to sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from analysis.delta_lakehouse import DeltaLakehouseManager, DEFAULT_DELTA_PATH


class TestDeltaLakehouse(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """Initialize the Delta Lakehouse manager and ensure initial table exists."""
        cls.mgr = DeltaLakehouseManager(table_path=DEFAULT_DELTA_PATH)
        if not cls.mgr.is_initialized():
            cls.mgr.initialize_from_parquet()

    def test_01_table_initialized_and_log_exists(self):
        """Verify Delta table and _delta_log are present on disk."""
        self.assertTrue(self.mgr.is_initialized(), "Delta Lake table is not initialized")
        delta_log_dir = os.path.join(self.mgr.table_path, "_delta_log")
        self.assertTrue(os.path.exists(delta_log_dir), "_delta_log directory does not exist")
        log_files = [f for f in os.listdir(delta_log_dir) if f.endswith(".json")]
        self.assertGreater(len(log_files), 0, "No commit log JSON files found in _delta_log")

    def test_02_acid_version_and_history(self):
        """Verify ACID transactions generate an immutable commit history."""
        history = self.mgr.get_commit_history()
        self.assertIsInstance(history, list)
        self.assertGreater(len(history), 0, "Commit history is empty")
        first_commit = history[-1] if history else {}
        self.assertEqual(first_commit.get("version"), 0, "First commit version is not 0")

    def test_03_schema_evolution_with_temperature_sensor(self):
        """Verify Schema Evolution: add ambient_temp_c dynamically without rewriting old files."""
        v_before = self.mgr.get_table().version()
        res = self.mgr.simulate_schema_evolution(batch_size=20)
        self.assertEqual(res["status"], "COMMITTED")
        v_after = res["new_version"]
        self.assertGreater(v_after, v_before, "Version was not incremented after schema evolution")

        # Verify new schema contains ambient_temp_c and humidity_pct
        dt = self.mgr.get_table()
        schema_names = [f.name for f in dt.schema().fields]
        self.assertIn("ambient_temp_c", schema_names)
        self.assertIn("humidity_pct", schema_names)

    def test_04_time_travel_version_0_vs_latest(self):
        """Verify Time Travel: query snapshot at Version 0 vs latest snapshot."""
        # Query Version 0 (historical state before temperature sensor)
        df_v0, meta_v0 = self.mgr.query_time_travel(version=0)
        self.assertFalse(meta_v0["has_temperature_sensor"], "Version 0 should not contain ambient_temp_c")
        self.assertNotIn("ambient_temp_c", df_v0.columns)

        # Query Latest Version
        df_latest, meta_latest = self.mgr.query_time_travel()
        self.assertTrue(meta_latest["has_temperature_sensor"], "Latest version must contain ambient_temp_c")
        self.assertIn("ambient_temp_c", df_latest.columns)
        self.assertGreater(meta_latest["total_rows"], meta_v0["total_rows"], "Latest version should have more total rows than Version 0")

    def test_05_in_place_compaction_optimize(self):
        """Verify in-place compaction executes and logs an OPTIMIZE transaction."""
        # Append two small micro-batches to guarantee multi-file fragmentation in a partition
        sample_df = self.mgr.get_table().to_pandas().head(5)
        self.mgr.append_batch(sample_df)
        self.mgr.append_batch(sample_df)

        res = self.mgr.optimize_and_compact()
        self.assertEqual(res["status"], "OPTIMIZED")
        self.assertIn("metrics", res)

        # Verify OPTIMIZE operation exists in commit history
        history = self.mgr.get_commit_history()
        ops = [h["operation"] for h in history]
        self.assertIn("OPTIMIZE", ops, "OPTIMIZE commit not found in history")

    def test_06_duckdb_vectorized_analytical_query(self):
        """Verify DuckDB queries Delta table with vectorized SQL filters and groupings."""
        sql = """
            SELECT 
                building_type, 
                COUNT(*) as count, 
                ROUND(AVG(power_kw), 2) as mean_power,
                ROUND(MAX(power_kw), 2) as max_power
            FROM campus_telemetry
            WHERE power_kw >= 0.0
            GROUP BY building_type
            ORDER BY count DESC
        """
        df, meta = self.mgr.query_time_travel(sql=sql)
        self.assertGreater(len(df), 0, "Vectorized DuckDB query returned 0 rows")
        self.assertIn("building_type", df.columns)
        self.assertIn("mean_power", df.columns)
        categories = set(df["building_type"].unique())
        self.assertTrue(categories.issubset({"Hostels", "Departments", "Lecture Theatres", "Facilities"}))

    def test_07_snapshot_comparison(self):
        """Verify snapshot diffing between Version 0 and latest version."""
        latest_v = self.mgr.get_table().version()
        diff = self.mgr.compare_snapshots(version_a=0, version_b=latest_v)
        self.assertEqual(diff["version_a"], 0)
        self.assertEqual(diff["version_b"], latest_v)
        self.assertTrue(diff["schema_evolved"])
        self.assertIn("ambient_temp_c", diff["added_columns"])
        self.assertGreater(diff["row_delta"], 0)


if __name__ == "__main__":
    unittest.main()
