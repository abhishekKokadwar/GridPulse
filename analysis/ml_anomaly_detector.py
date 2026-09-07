import os
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from datetime import datetime

class MLAnomalyDetector:
    """
    Real Statistical & Machine Learning Anomaly Detection Engine:
    
    1. Isolation Forest (Unsupervised Machine Learning):
       Learns multidimensional normal operational manifolds across
       [hour, day_of_week, power_kw, voltage_v, current_a, power_factor].
       Detects contextual anomalies (e.g. 40kW draw at 3 AM on Sunday).

    2. Statistical Dynamic Baseline (Z-Score & Rolling Statistics):
       Identifies statistical power surges deviating > 3 standard deviations
       from historical contextual baselines.

    3. Deterministic SCADA Electrical Guardrails:
       Flags explicit IEEE/IEC physical violations (Voltage Sags/Surges).
    """

    def __init__(self, contamination=0.02):
        self.contamination = contamination
        self.model = IsolationForest(
            n_estimators=100,
            contamination=contamination,
            random_state=42,
            n_jobs=-1,
        )
        self.is_trained = False
        self.feature_cols = ["hour", "day_of_week", "power_kw", "voltage_v", "current_a", "power_factor"]
        self.meter_baselines = {}

    def extract_features(self, df_or_record):
        """Extracts numerical & temporal features for ML inference."""
        if isinstance(df_or_record, dict):
            dt = pd.to_datetime(df_or_record["timestamp"])
            return np.array([[
                dt.hour,
                dt.dayofweek,
                float(df_or_record["power_kw"]),
                float(df_or_record["voltage_v"]),
                float(df_or_record["current_a"]),
                float(df_or_record["power_factor"]),
            ]])
        else:
            df = df_or_record.copy()
            if "hour" not in df.columns:
                df["timestamp"] = pd.to_datetime(df["timestamp"])
                df["hour"] = df["timestamp"].dt.hour
                df["day_of_week"] = df["timestamp"].dt.dayofweek
            return df[self.feature_cols].values

    def train_on_historical(self, df_historical):
        """Trains the Isolation Forest model on historical campus baseline telemetry."""
        X = self.extract_features(df_historical)
        self.model.fit(X)
        self.is_trained = True

        # Calculate per-building/meter statistical baselines (mean & std)
        for meter_id, group in df_historical.groupby("meter_id"):
            self.meter_baselines[meter_id] = {
                "mean_pwr": float(group["power_kw"].mean()),
                "std_pwr": float(group["power_kw"].std()) or 1.0,
            }

        print(f"[ML DETECTOR] Isolation Forest trained on {len(X)} historical samples across {len(self.meter_baselines)} meters.")

    def score_single_reading(self, reading):
        """
        Evaluates a real-time streaming reading.
        Returns a dict with ML anomaly score, statistical Z-Score, and anomaly classifications.
        """
        meter_id = reading.get("meter_id", "M001")
        power_kw = float(reading.get("power_kw", 0))
        voltage_v = float(reading.get("voltage_v", 230))
        pf = float(reading.get("power_factor", 0.95))

        # 1. Statistical Z-Score
        baseline = self.meter_baselines.get(meter_id, {"mean_pwr": 20.0, "std_pwr": 5.0})
        z_score = (power_kw - baseline["mean_pwr"]) / baseline["std_pwr"]
        is_stat_anomaly = abs(z_score) > 3.0

        # 2. Machine Learning Isolation Forest Score
        ml_anomaly = False
        anomaly_score = 0.0
        if self.is_trained:
            X = self.extract_features(reading)
            prediction = self.model.predict(X)[0]  # -1 = anomaly, 1 = normal
            anomaly_score = float(self.model.decision_function(X)[0])  # Negative = more anomalous
            ml_anomaly = (prediction == -1)

        # 3. Deterministic SCADA Grid Violations
        is_voltage_sag = voltage_v < 220.0
        is_voltage_surge = voltage_v > 240.0
        is_low_pf = pf < 0.88

        # Combine results into structured evaluation
        is_any_anomaly = ml_anomaly or is_stat_anomaly or is_voltage_sag or is_voltage_surge or is_low_pf

        reasons = []
        if ml_anomaly:
            reasons.append(f"ML Isolation Anomaly (Score: {anomaly_score:.3f})")
        if is_stat_anomaly:
            reasons.append(f"Statistical Load Spike (Z={z_score:+.2f})")
        if is_voltage_sag:
            reasons.append(f"SCADA Voltage Sag ({voltage_v:.1f}V < 220V)")
        if is_voltage_surge:
            reasons.append(f"SCADA Voltage Surge ({voltage_v:.1f}V > 240V)")
        if is_low_pf:
            reasons.append(f"SCADA Low Power Factor ({pf:.3f} < 0.88)")

        return {
            "is_anomaly": is_any_anomaly,
            "ml_anomaly": ml_anomaly,
            "anomaly_score": round(anomaly_score, 4),
            "z_score": round(z_score, 2),
            "reasons": reasons,
            "primary_reason": reasons[0] if reasons else "NOMINAL",
        }
