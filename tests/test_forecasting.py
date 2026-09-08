"""
Unit tests for GridPulse Phase 6 24-Hour AI Forecaster
"""

import os
import sys
import unittest
import pandas as pd

# Add project root to sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from analysis.forecaster import LoadForecaster


class TestForecaster(unittest.TestCase):
    def setUp(self):
        self.forecaster = LoadForecaster()

    def test_model_training_and_metrics(self):
        res = self.forecaster.train_and_evaluate()
        self.assertIn("selected_model", res)
        self.assertIn(res["selected_model"], ["RandomForestRegressor", "RidgeRegressor"])
        self.assertIn("MAE", res["metrics"])
        self.assertIn("RMSE", res["metrics"])
        self.assertIn("MAPE", res["metrics"])
        # Ensure error metrics are within realistic bounds
        self.assertLess(res["metrics"]["MAPE"], 30.0)

    def test_24h_forecast_generation(self):
        fc_df = self.forecaster.generate_24h_forecast()
        self.assertIsInstance(fc_df, pd.DataFrame)
        self.assertEqual(len(fc_df), 24)
        expected_cols = {"forecast_time", "hour_of_day", "predicted_load_kw", "lower_ci_95", "upper_ci_95"}
        self.assertTrue(expected_cols.issubset(set(fc_df.columns)))
        # Verify confidence intervals enclose or match predictions
        for _, row in fc_df.iterrows():
            self.assertLessEqual(row["lower_ci_95"], row["predicted_load_kw"])
            self.assertGreaterEqual(row["upper_ci_95"], row["predicted_load_kw"])


if __name__ == "__main__":
    unittest.main()
