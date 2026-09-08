"""
GridPulse Automated Webhook Alert & Incident Dispatcher (Phase 6)
Dispatches structured incident cards to external webhooks (Slack, Discord, MS Teams, HTTP endpoints)
or mock event sinks for peak-shaving notifications and critical SCADA anomalies.
"""

import os
import sys
import json
import time
from datetime import datetime
from typing import Dict, Any, List, Optional
import requests

# Add project root to sys.path and remove script_dir to prevent package shadowing
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir in sys.path:
    sys.path.remove(script_dir)
PROJECT_ROOT = os.path.abspath(os.path.join(script_dir, ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

DEFAULT_WEBHOOK_URL = os.getenv("ALERT_WEBHOOK_URL", "")
DISPATCH_HISTORY_FILE = os.path.join(PROJECT_ROOT, "tmp", "webhook_dispatch_history.json")


def _record_dispatch_history(entry: Dict[str, Any]):
    """Records dispatched alert to local history file for dashboard audit trail."""
    os.makedirs(os.path.dirname(DISPATCH_HISTORY_FILE), exist_ok=True)
    history = []
    if os.path.exists(DISPATCH_HISTORY_FILE):
        try:
            with open(DISPATCH_HISTORY_FILE, "r") as f:
                history = json.load(f)
        except Exception:
            history = []

    history.insert(0, entry)
    history = history[:50]  # Keep latest 50

    with open(DISPATCH_HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2, default=str)


def get_dispatch_history() -> List[Dict[str, Any]]:
    """Returns list of recent webhook dispatch events."""
    if os.path.exists(DISPATCH_HISTORY_FILE):
        try:
            with open(DISPATCH_HISTORY_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def format_slack_card(title: str, color: str, fields: List[Dict[str, str]], summary: str) -> Dict[str, Any]:
    """Formats an incident payload into Slack Block Kit / Attachment compatible JSON."""
    return {
        "attachments": [
            {
                "fallback": f"GridPulse Alert: {title}",
                "color": color,
                "title": f"⚡ GridPulse Incident Dispatch: {title}",
                "text": summary,
                "fields": [{"title": f["name"], "value": f["value"], "short": f.get("short", True)} for f in fields],
                "footer": "GridPulse Automated Demand Response Engine",
                "ts": int(time.time()),
            }
        ]
    }


def dispatch_peak_shaving_alert(dispatch_plan: Dict[str, Any], webhook_url: Optional[str] = None) -> Dict[str, Any]:
    """
    Constructs and dispatches automated peak-shaving alert payload.
    """
    url = webhook_url or DEFAULT_WEBHOOK_URL
    max_kw = dispatch_plan.get("peak_forecast_kw", 0.0)
    thresh_kw = dispatch_plan.get("threshold_kw", 850.0)
    overload = dispatch_plan.get("max_overload_kw", 0.0)
    savings = dispatch_plan.get("est_monthly_savings", 0.0)
    actions = dispatch_plan.get("actions", [])

    action_summary_lines = []
    for a in actions:
        if a["status"] == "ARMED":
            action_summary_lines.append(f"• *Tier {a['tier']} ({a['category']}):* {a['name']} -> {a['active_shed_kw']} kW active shed")

    action_text = "\n".join(action_summary_lines) if action_summary_lines else "No automated action required."

    fields = [
        {"name": "Forecast Peak", "value": f"{max_kw:,.1f} kW", "short": True},
        {"name": "Contract Threshold", "value": f"{thresh_kw:,.1f} kW", "short": True},
        {"name": "Projected Overload", "value": f"+{overload:.1f} kW", "short": True},
        {"name": "Potential Penalty Savings", "value": f"INR {savings:,.0f}", "short": True},
        {"name": "Active Dispatch Directives", "value": action_text, "short": False},
    ]

    payload = format_slack_card(
        title=f"IMPENDING PEAK DEMAND BREACH (+{overload:.1f} kW)",
        color="#f59e0b" if overload < 100 else "#ef4444",
        fields=fields,
        summary=f"Automated Demand Response system has triggered peak-shaving countermeasures to prevent contract demand penalties.",
    )

    result_status = "SIMULATED_SUCCESS"
    status_code = 200

    if url and url.startswith("http"):
        try:
            resp = requests.post(url, json=payload, timeout=5)
            result_status = "SENT"
            status_code = resp.status_code
        except Exception as e:
            result_status = f"FAILED: {e}"
            status_code = 500

    record = {
        "timestamp": datetime.now().isoformat(),
        "event_type": "PEAK_SHAVING_DISPATCH",
        "title": f"Peak Demand Breach (+{overload:.1f} kW)",
        "target_url": url if url else "MOCK_CONSOLE",
        "status": result_status,
        "status_code": status_code,
        "payload": payload,
    }
    _record_dispatch_history(record)
    return record


def dispatch_scada_fault_alert(
    meter_id: str,
    building_id: str,
    alert_type: str,
    severity: str,
    metric_value: float,
    threshold_value: float,
    webhook_url: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Constructs and dispatches immediate SCADA electrical fault alert (e.g. Voltage Sag).
    """
    url = webhook_url or DEFAULT_WEBHOOK_URL
    color_map = {"CRITICAL": "#ef4444", "WARNING": "#f59e0b", "INFO": "#3b82f6"}

    fields = [
        {"name": "Meter Identifier", "value": meter_id, "short": True},
        {"name": "Building Location", "value": building_id, "short": True},
        {"name": "Observed Metric", "value": f"{metric_value:.2f}", "short": True},
        {"name": "Breached Limit", "value": f"{threshold_value:.2f}", "short": True},
    ]

    payload = format_slack_card(
        title=f"SCADA Electrical Fault: {alert_type} [{severity}]",
        color=color_map.get(severity, "#ef4444"),
        fields=fields,
        summary=f"Sub-meter {meter_id} in {building_id} observed a {alert_type} breach ({metric_value:.2f} vs limit {threshold_value:.2f}).",
    )

    result_status = "SIMULATED_SUCCESS"
    status_code = 200

    if url and url.startswith("http"):
        try:
            resp = requests.post(url, json=payload, timeout=5)
            result_status = "SENT"
            status_code = resp.status_code
        except Exception as e:
            result_status = f"FAILED: {e}"
            status_code = 500

    record = {
        "timestamp": datetime.now().isoformat(),
        "event_type": f"SCADA_{alert_type}",
        "title": f"{alert_type} at {meter_id} ({building_id})",
        "target_url": url if url else "MOCK_CONSOLE",
        "status": result_status,
        "status_code": status_code,
        "payload": payload,
    }
    _record_dispatch_history(record)
    return record


if __name__ == "__main__":
    print("[WEBHOOK DISPATCHER TEST]")
    test_plan = {
        "peak_forecast_kw": 885.5,
        "threshold_kw": 800.0,
        "max_overload_kw": 85.5,
        "est_monthly_savings": 29925.0,
        "actions": [
            {"tier": 1, "category": "Soft Shedding", "name": "Non-Critical Facilities & EV Setback", "active_shed_kw": 45.0, "status": "ARMED"},
            {"tier": 2, "category": "Chiller Cycling", "name": "Lecture Theatre & Academic HVAC Cycling", "active_shed_kw": 40.5, "status": "ARMED"},
        ],
    }
    res = dispatch_peak_shaving_alert(test_plan)
    print("Peak alert dispatch result:", res["status"])

    fault_res = dispatch_scada_fault_alert(
        meter_id="M001",
        building_id="BH1",
        alert_type="VOLTAGE_SAG",
        severity="CRITICAL",
        metric_value=211.4,
        threshold_value=220.0,
    )
    print("Fault alert dispatch result:", fault_res["status"])
    print(f"Total entries in dispatch audit log: {len(get_dispatch_history())}")
