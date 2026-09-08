"""
Unit tests for GridPulse Phase 5 Data Lakehouse & Cold Path Analytics
"""

import os
import sys
import unittest
import pandas as pd

# Add project root to sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from analysis.lake_analytics import (
    get_lake_metadata,
    query_lake_telemetry,
    query_lake_hourly_profile,
    query_lake_building_summary,
    benchmark_query_performance,
)
from scripts.compact_lake import run_compaction


class TestLakehouse(unittest.TestCase):
    def setUp(self):
        self.lake_path = os.path.join(PROJECT_ROOT, "data", "lake", "raw_telemetry")

    def test_lake_metadata(self):
        meta = get_lake_metadata(self.lake_path)
        self.assertTrue(meta["exists"])
        self.assertGreater(meta["total_records"], 0)
        self.assertGreater(len(meta["partitions"]), 0)
        self.assertEqual(meta["meters_count"], 42)

    def test_lake_telemetry_query(self):
        df = query_lake_telemetry(limit=50, lake_path=self.lake_path)
        self.assertIsInstance(df, pd.DataFrame)
        self.assertGreater(len(df), 0)
        expected_cols = {"event_id", "timestamp", "meter_id", "building_id", "power_kw", "voltage_v"}
        self.assertTrue(expected_cols.issubset(set(df.columns)))

    def test_lake_hourly_profile(self):
        df = query_lake_hourly_profile(lake_path=self.lake_path)
        self.assertIsInstance(df, pd.DataFrame)
        self.assertGreater(len(df), 0)
        self.assertIn("hour", df.columns)
        self.assertIn("avg_power_kw", df.columns)

    def test_lake_building_summary(self):
        df = query_lake_building_summary(lake_path=self.lake_path)
        self.assertIsInstance(df, pd.DataFrame)
        self.assertGreater(len(df), 0)
        self.assertIn("building_id", df.columns)
        self.assertIn("avg_power_kw", df.columns)

    def test_compaction_execution(self):
        res = run_compaction(lake_path=self.lake_path)
        self.assertEqual(res["status"], "SUCCESS")
        self.assertGreaterEqual(res["partitions_checked"], 1)


if __name__ == "__main__":
    unittest.main()
