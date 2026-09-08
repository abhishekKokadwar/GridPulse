"""
Unit tests for GridPulse Phase 6 Automated Dispatch & Webhook Dispatcher
"""

import os
import sys
import unittest
import pandas as pd
from datetime import datetime, timedelta

# Add project root to sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from analysis.dispatch_engine import evaluate_dispatch_plan
from consumer.webhook_dispatcher import dispatch_peak_shaving_alert, dispatch_scada_fault_alert, get_dispatch_history


class TestDispatchEngine(unittest.TestCase):
    def test_nominal_dispatch(self):
        # Forecast well below threshold
        times = [datetime.now() + timedelta(hours=i) for i in range(24)]
        df = pd.DataFrame({
            "forecast_time": times,
            "predicted_load_kw": [500.0 + i for i in range(24)],
        })
        plan = evaluate_dispatch_plan(df, peak_threshold_kw=800.0)
        self.assertFalse(plan["has_violations"])
        self.assertEqual(plan["violation_hours_count"], 0)
        self.assertEqual(plan["max_overload_kw"], 0.0)
        self.assertEqual(plan["est_monthly_savings"], 0.0)

    def test_peak_overload_dispatch_tiers(self):
        # Forecast with peak overload of 150 kW
        times = [datetime.now() + timedelta(hours=i) for i in range(24)]
        loads = [600.0] * 12 + [950.0] * 4 + [600.0] * 8
        df = pd.DataFrame({
            "forecast_time": times,
            "predicted_load_kw": loads,
        })
        plan = evaluate_dispatch_plan(df, peak_threshold_kw=800.0, tariff_rate=350.0)
        self.assertTrue(plan["has_violations"])
        self.assertEqual(plan["violation_hours_count"], 4)
        self.assertEqual(plan["max_overload_kw"], 150.0)
        self.assertGreater(plan["est_monthly_savings"], 0)

        # Check action tiers
        action_tiers = {a["tier"]: a for a in plan["actions"]}
        self.assertEqual(action_tiers[1]["status"], "ARMED")
        self.assertEqual(action_tiers[1]["active_shed_kw"], 45.0)
        self.assertEqual(action_tiers[2]["status"], "ARMED")
        self.assertEqual(action_tiers[2]["active_shed_kw"], 90.0)
        self.assertEqual(action_tiers[3]["status"], "ARMED")
        self.assertEqual(action_tiers[3]["active_shed_kw"], 15.0)

    def test_webhook_dispatch_payloads(self):
        # Peak shaving webhook test
        test_plan = {
            "peak_forecast_kw": 920.0,
            "threshold_kw": 800.0,
            "max_overload_kw": 120.0,
            "est_monthly_savings": 42000.0,
            "actions": [
                {"tier": 1, "category": "Soft Shedding", "name": "Facility Setback", "active_shed_kw": 45.0, "status": "ARMED"},
            ],
        }
        res = dispatch_peak_shaving_alert(test_plan)
        self.assertEqual(res["status"], "SIMULATED_SUCCESS")
        self.assertIn("payload", res)
        self.assertIn("attachments", res["payload"])

        # SCADA fault alert test
        fault_res = dispatch_scada_fault_alert(
            meter_id="M015",
            building_id="Library",
            alert_type="VOLTAGE_SAG",
            severity="CRITICAL",
            metric_value=214.2,
            threshold_value=220.0,
        )
        self.assertEqual(fault_res["status"], "SIMULATED_SUCCESS")
        self.assertEqual(fault_res["event_type"], "SCADA_VOLTAGE_SAG")

        # Check history audit trail
        history = get_dispatch_history()
        self.assertGreaterEqual(len(history), 2)


if __name__ == "__main__":
    unittest.main()
