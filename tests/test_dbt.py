"""
Automated Integration & Unit Tests for GridPulse Medallion Lakehouse (dbt-duckdb)
Validates compilation, execution, data contracts, and analytical marts sanity.
"""

import os
import sys
import unittest
import duckdb

# Add project root to sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from scripts.run_dbt import run_pipeline, DEFAULT_DB_PATH, DBT_PROJECT_DIR


class TestMedallionLakehouse(unittest.TestCase):
    con = None

    @classmethod
    def setUpClass(cls):
        """Execute the dbt pipeline once for the test suite."""
        res = run_pipeline(do_seed=True, do_run=True, do_test=True, project_dir=DBT_PROJECT_DIR)
        assert res["success"] is True, "Initial dbt pipeline execution failed in setUpClass"
        cls.con = duckdb.connect(DEFAULT_DB_PATH)

    @classmethod
    def tearDownClass(cls):
        if cls.con:
            cls.con.close()

    def test_database_file_created(self):
        """Verify the DuckDB lakehouse database file is created on disk."""
        self.assertTrue(os.path.exists(DEFAULT_DB_PATH), f"Database not found at {DEFAULT_DB_PATH}")
        self.assertGreater(os.path.getsize(DEFAULT_DB_PATH), 1024, "Database file is empty or corrupted")

    def test_medallion_tables_and_views_exist(self):
        """Verify all Bronze, Silver, and Gold objects exist in DuckDB."""
        tables_df = self.con.execute("""
            SELECT table_schema, table_name, table_type 
            FROM information_schema.tables 
            WHERE table_schema IN ('bronze', 'silver', 'gold')
        """).df()
        
        schema_table_map = set(zip(tables_df['table_schema'], tables_df['table_name']))
        
        expected_objects = [
            ('bronze', 'bronze_raw_telemetry'),
            ('silver', 'seed_buildings'),
            ('silver', 'seed_meters'),
            ('silver', 'stg_buildings'),
            ('silver', 'stg_meters'),
            ('silver', 'silver_telemetry_clean'),
            ('gold', 'fct_hourly_facility_demand'),
            ('gold', 'fct_daily_campus_dispatch'),
            ('gold', 'dim_facility_efficiency'),
        ]
        
        for schema, tbl in expected_objects:
            self.assertIn((schema, tbl), schema_table_map, f"Missing object {schema}.{tbl}")

    def test_silver_telemetry_clean_integrity(self):
        """Verify Silver table has deduplicated, bounded electrical readings."""
        row_count = self.con.execute("SELECT COUNT(*) FROM silver.silver_telemetry_clean").fetchone()[0]
        self.assertGreater(row_count, 0, "Silver telemetry table has 0 rows")

        # Check no negative power or invalid voltage
        anomalies = self.con.execute("""
            SELECT COUNT(*) 
            FROM silver.silver_telemetry_clean 
            WHERE power_kw < 0.0 OR voltage_v < 180.0 OR voltage_v > 270.0
        """).fetchone()[0]
        self.assertEqual(anomalies, 0, "Found invalid electrical boundaries in Silver")

        # Check distinct facilities mapped
        building_count = self.con.execute("SELECT COUNT(DISTINCT building_id) FROM silver.silver_telemetry_clean").fetchone()[0]
        self.assertGreaterEqual(building_count, 15, "Fewer facilities mapped than expected")

    def test_gold_facility_efficiency_kpis(self):
        """Verify Gold efficiency dimension computes valid load factors for all 22 facilities."""
        df = self.con.execute("SELECT * FROM gold.dim_facility_efficiency").df()
        self.assertEqual(len(df), 22, f"Expected 22 campus facilities, found {len(df)}")
        
        # Load factor must be bounded (0.0 to 1.0)
        self.assertTrue((df['load_factor'] > 0.0).all(), "Found load_factor <= 0")
        self.assertTrue((df['load_factor'] <= 1.0).all(), "Found load_factor > 1.0")
        
        # Categories should match standard campus infrastructure
        categories = set(df['category'].unique())
        self.assertIn("Hostels", categories)
        self.assertIn("Departments", categories)
        self.assertIn("Facilities", categories)
        self.assertIn("Lecture Theatres", categories)

    def test_gold_daily_campus_dispatch_kpis(self):
        """Verify Gold daily campus dispatch calculates overload and dispatch tiers."""
        df = self.con.execute("SELECT * FROM gold.fct_daily_campus_dispatch").df()
        self.assertGreater(len(df), 0, "Daily campus dispatch table is empty")
        
        # Check required columns
        for col in ['dispatch_date', 'peak_campus_demand_kw', 'overload_kw', 'recommended_dispatch_tier']:
            self.assertIn(col, df.columns, f"Missing column {col} in fct_daily_campus_dispatch")
            
        self.assertTrue((df['peak_campus_demand_kw'] > 0.0).all(), "Found non-positive peak demand")

    def test_gold_hourly_facility_demand_kpis(self):
        """Verify Gold hourly demand mart has aggregated power and kWh."""
        df = self.con.execute("SELECT * FROM gold.fct_hourly_facility_demand LIMIT 100").df()
        self.assertGreater(len(df), 0, "Hourly facility demand mart is empty")
        self.assertTrue((df['avg_power_kw'] >= 0.0).all(), "Negative avg_power_kw in hourly mart")
        self.assertTrue((df['sample_count'] > 0).all(), "Zero sample_count in hourly mart")


if __name__ == "__main__":
    unittest.main()
