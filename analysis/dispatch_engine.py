"""
GridPulse Automated Peak-Shaving & Demand Response Dispatch Engine (Phase 6)
Analyzes 24-hour ahead AI load forecasts against contractual peak limits,
generating prescriptive tiered load-shedding and battery dispatch recommendations.
"""

import os
import sys
from datetime import datetime
from typing import Dict, Any, List, Optional
import pandas as pd
import numpy as np

# Add project root to sys.path and remove script_dir to prevent package shadowing
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir in sys.path:
    sys.path.remove(script_dir)
PROJECT_ROOT = os.path.abspath(os.path.join(script_dir, ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

DEFAULT_PEAK_THRESHOLD_KW = 850.0  # Contractual campus maximum demand target
DEFAULT_DEMAND_TARIFF_PER_KW = 350.0  # Commercial monthly demand tariff in INR/kW (or USD equivalent)


def evaluate_dispatch_plan(
    forecast_df: pd.DataFrame,
    peak_threshold_kw: float = DEFAULT_PEAK_THRESHOLD_KW,
    tariff_rate: float = DEFAULT_DEMAND_TARIFF_PER_KW,
) -> Dict[str, Any]:
    """
    Evaluates 24-hour predictive forecast against contract peak threshold.
    Generates prescriptive 3-Tier Automated Demand Response actions.
    """
    if forecast_df.empty or "predicted_load_kw" not in forecast_df.columns:
        return {
            "has_violations": False,
            "violation_hours_count": 0,
            "peak_forecast_kw": 0.0,
            "threshold_kw": peak_threshold_kw,
            "max_overload_kw": 0.0,
            "total_shed_kw": 0.0,
            "est_monthly_savings": 0.0,
            "actions": [],
            "adjusted_forecast_df": pd.DataFrame(),
        }

    df = forecast_df.copy()
    max_forecast_load = float(df["predicted_load_kw"].max())
    overload_mask = df["predicted_load_kw"] > peak_threshold_kw
    violation_rows = df[overload_mask]
    violation_hours_count = len(violation_rows)

    actions: List[Dict[str, Any]] = []
    total_shed_capacity = 0.0

    if violation_hours_count > 0:
        max_overload_kw = round(float(violation_rows["predicted_load_kw"].max() - peak_threshold_kw), 2)
        peak_times = [t.strftime("%H:%M") for t in violation_rows["forecast_time"]]

        # Tier 1: Soft Setback (Facilities & EV Chargers)
        t1_capacity = min(45.0, max_overload_kw)
        actions.append({
            "tier": 1,
            "name": "Non-Critical Facilities & EV Setback",
            "category": "Soft Shedding",
            "target_zones": ["Convention Center", "Open Air Theatre (OAT)", "Main Gate EV Pods"],
            "target_meters": ["M030", "M031", "M037"],
            "shed_capacity_kw": 45.0,
            "active_shed_kw": t1_capacity,
            "action_desc": "Dim decorative/outdoor architectural lighting and throttle Level-2 EV charging to standby.",
            "urgency": "MEDIUM",
            "status": "ARMED",
        })
        total_shed_capacity += 45.0

        # Tier 2: HVAC Duty-Cycling (Lecture Theatres & Academic Block)
        t2_capacity = min(90.0, max(0.0, max_overload_kw - 45.0))
        actions.append({
            "tier": 2,
            "name": "Lecture Theatre & Academic HVAC Duty-Cycling",
            "category": "Chiller Cycling",
            "target_zones": ["LT1 (Lecture Theatre 1)", "LT2 (Lecture Theatre 2)", "Academic Block"],
            "target_meters": ["M026", "M027", "M028", "M029", "M032", "M033"],
            "shed_capacity_kw": 90.0,
            "active_shed_kw": t2_capacity,
            "action_desc": "Cycle central chilled-water air handling units in 15-minute intervals between lecture periods.",
            "urgency": "HIGH" if max_overload_kw > 45.0 else "STANDBY",
            "status": "ARMED" if max_overload_kw > 45.0 else "STANDBY",
        })
        total_shed_capacity += 90.0

        # Tier 3: Battery Energy Storage System (BESS Discharge)
        t3_capacity = min(160.0, max(0.0, max_overload_kw - 135.0))
        actions.append({
            "tier": 3,
            "name": "Powerhouse BESS 500kWh Peak-Shaving Discharge",
            "category": "Battery Storage",
            "target_zones": ["Main Powerhouse Substation"],
            "target_meters": ["M036"],
            "shed_capacity_kw": 160.0,
            "active_shed_kw": t3_capacity,
            "action_desc": "Discharge 500 kWh stationary lithium iron phosphate battery storage inverter into 415V bus.",
            "urgency": "CRITICAL" if max_overload_kw > 135.0 else "STANDBY",
            "status": "ARMED" if max_overload_kw > 135.0 else "STANDBY",
        })
        total_shed_capacity += 160.0

        # Compute adjusted curve after automated dispatch
        total_active_shed = min(max_overload_kw, 45.0 + 90.0 + 160.0)
        df["dispatched_load_kw"] = np.where(
            df["predicted_load_kw"] > peak_threshold_kw,
            np.maximum(peak_threshold_kw, df["predicted_load_kw"] - total_active_shed),
            df["predicted_load_kw"],
        )
        df["dispatched_load_kw"] = df["dispatched_load_kw"].round(2)

        est_monthly_savings = round(max_overload_kw * tariff_rate, 2)
    else:
        max_overload_kw = 0.0
        peak_times = []
        df["dispatched_load_kw"] = df["predicted_load_kw"]
        est_monthly_savings = 0.0

    return {
        "has_violations": violation_hours_count > 0,
        "violation_hours_count": violation_hours_count,
        "peak_forecast_kw": max_forecast_load,
        "threshold_kw": peak_threshold_kw,
        "peak_times": peak_times,
        "max_overload_kw": max_overload_kw,
        "total_shed_kw": total_shed_capacity,
        "est_monthly_savings": est_monthly_savings,
        "actions": actions,
        "adjusted_forecast_df": df,
    }


def evaluate_peak_shaving_dispatch(
    peak_kw: float,
    peak_threshold_kw: float = DEFAULT_PEAK_THRESHOLD_KW,
    tariff_rate: float = DEFAULT_DEMAND_TARIFF_PER_KW,
) -> Dict[str, Any]:
    """
    Convenience evaluator for a single peak load value against contract threshold.
    Returns prescriptive dispatch actions and penalty avoidance economics.
    """
    dummy_df = pd.DataFrame({
        "forecast_time": [datetime.now()],
        "predicted_load_kw": [float(peak_kw)],
    })
    return evaluate_dispatch_plan(dummy_df, peak_threshold_kw=peak_threshold_kw, tariff_rate=tariff_rate)



if __name__ == "__main__":
    from analysis.forecaster import LoadForecaster
    fc = LoadForecaster()
    pred_df = fc.generate_24h_forecast()
    plan = evaluate_dispatch_plan(pred_df, peak_threshold_kw=750.0)
    print("\n[DISPATCH ENGINE TEST (Threshold: 750 kW)]")
    print(f"Violations detected: {plan['has_violations']} ({plan['violation_hours_count']} hours)")
    print(f"Max Overload: {plan['max_overload_kw']} kW above {plan['threshold_kw']} kW")
    print(f"Potential Tariff Savings: INR {plan['est_monthly_savings']:,}")
    print("\nRecommended Dispatch Actions:")
    for a in plan["actions"]:
        print(f"  * Tier {a['tier']}: {a['name']} -> {a['status']} ({a['active_shed_kw']} kW active / {a['shed_capacity_kw']} kW cap)")
