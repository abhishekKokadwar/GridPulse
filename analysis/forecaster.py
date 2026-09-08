"""
GridPulse 24-Hour Ahead AI Predictive Energy Forecaster (Phase 6)
Implements chronological time-series machine learning to forecast campus-wide
electricity demand with confidence intervals, in accordance with ML best practices.
"""

import os
import sys
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, Any, Tuple, Optional
import joblib

from sklearn.linear_model import Ridge
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, mean_absolute_percentage_error

# Add project root to sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

DEFAULT_MODEL_PATH = os.path.join(PROJECT_ROOT, "analysis", "forecaster_model.joblib")
DEFAULT_LAKE_PATH = os.path.join(PROJECT_ROOT, "data", "lake", "raw_telemetry")


class LoadForecaster:
    """
    Predictive Time-Series Forecaster for campus aggregate active load (kW).
    Evaluates baseline Ridge against Random Forest Regressor using chronological splits.
    """

    def __init__(self, model_path: str = DEFAULT_MODEL_PATH):
        self.model_path = model_path
        self.model = None
        self.model_name = None
        self.metrics: Dict[str, float] = {}
        self.feature_columns = [
            "hour",
            "day_of_week",
            "is_weekend",
            "sin_hour",
            "cos_hour",
            "sin_day",
            "cos_day",
            "lag_1",
            "lag_24",
        ]

    def _extract_hourly_timeseries(self, lake_path: str = DEFAULT_LAKE_PATH) -> pd.DataFrame:
        """
        Extracts hourly aggregate campus load from the Parquet lake (or raw CSV fallback).
        """
        import duckdb
        glob_pattern = os.path.join(lake_path, "**", "*.parquet").replace("\\", "/")

        if os.path.exists(lake_path) and os.listdir(lake_path):
            con = duckdb.connect()
            try:
                # Calculate instantaneous campus load per snapshot, then average across the hour
                sql = f"""
                    WITH snaps AS (
                        SELECT 
                            date_trunc('hour', timestamp) as ds,
                            timestamp as snap_ts,
                            SUM(power_kw) as snap_power_kw,
                            AVG(voltage_v) as snap_voltage_v,
                            AVG(power_factor) as snap_power_factor
                        FROM read_parquet('{glob_pattern}', hive_partitioning=1)
                        GROUP BY 1, 2
                    )
                    SELECT 
                        ds,
                        ROUND(AVG(snap_power_kw), 2) as total_power_kw,
                        ROUND(AVG(snap_voltage_v), 2) as avg_voltage_v,
                        ROUND(AVG(snap_power_factor), 3) as avg_power_factor
                    FROM snaps
                    GROUP BY 1
                    ORDER BY 1
                """
                df = con.execute(sql).df()
                if not df.empty:
                    df["ds"] = pd.to_datetime(df["ds"])
                    return df
            except Exception as e:
                print(f"[FORECASTER] DuckDB lake read failed: {e}. Falling back to CSV.")
            finally:
                con.close()

        # Fallback to CSV
        csv_path = os.path.join(PROJECT_ROOT, "data", "raw", "energy_data.csv")
        if os.path.exists(csv_path):
            raw = pd.read_csv(csv_path)
            raw["timestamp"] = pd.to_datetime(raw["timestamp"])
            snaps = raw.groupby("timestamp").agg({"power_kw": "sum", "voltage_v": "mean", "power_factor": "mean"}).reset_index()
            snaps["ds"] = snaps["timestamp"].dt.floor("h")
            df = snaps.groupby("ds").agg({"power_kw": "mean", "voltage_v": "mean", "power_factor": "mean"}).reset_index()
            df.columns = ["ds", "total_power_kw", "avg_voltage_v", "avg_power_factor"]
            return df

        raise FileNotFoundError("No telemetry data found in data/lake/ or data/raw/energy_data.csv")

    def _engineer_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Creates temporal and lag features strictly without future leakage.
        """
        df = df.copy()
        df["hour"] = df["ds"].dt.hour
        df["day_of_week"] = df["ds"].dt.dayofweek
        df["is_weekend"] = df["day_of_week"].isin([5, 6]).astype(int)

        # Cyclical Fourier features
        df["sin_hour"] = np.sin(2 * np.pi * df["hour"] / 24.0)
        df["cos_hour"] = np.cos(2 * np.pi * df["hour"] / 24.0)
        df["sin_day"] = np.sin(2 * np.pi * df["day_of_week"] / 7.0)
        df["cos_day"] = np.cos(2 * np.pi * df["day_of_week"] / 7.0)

        # Autoregressive lags
        df["lag_1"] = df["total_power_kw"].shift(1)
        df["lag_24"] = df["total_power_kw"].shift(24)

        # Backfill initial NaN lags with hour-of-day mean
        hour_means = df.groupby("hour")["total_power_kw"].transform("mean")
        df["lag_1"] = df["lag_1"].fillna(hour_means)
        df["lag_24"] = df["lag_24"].fillna(hour_means)

        return df

    def train_and_evaluate(self, train_ratio: float = 0.8) -> Dict[str, Any]:
        """
        Chronologically splits data into training and test sets,
        evaluates Ridge vs Random Forest, and persists the superior model.
        """
        df_raw = self._extract_hourly_timeseries()
        df_feat = self._engineer_features(df_raw)

        # Strict chronological split to preserve temporal sequence
        split_idx = int(len(df_feat) * train_ratio)
        train_df = df_feat.iloc[:split_idx].copy()
        test_df = df_feat.iloc[split_idx:].copy()

        X_train = train_df[self.feature_columns]
        y_train = train_df["total_power_kw"]
        X_test = test_df[self.feature_columns]
        y_test = test_df["total_power_kw"]

        # 1. Baseline Model: Ridge Regression with temporal encodings
        m_ridge = Ridge(alpha=1.0)
        m_ridge.fit(X_train, y_train)
        pred_ridge = m_ridge.predict(X_test)
        mae_ridge = mean_absolute_error(y_test, pred_ridge)
        rmse_ridge = np.sqrt(mean_squared_error(y_test, pred_ridge))
        mape_ridge = mean_absolute_percentage_error(y_test, pred_ridge)

        # 2. Ensemble Model: Random Forest Regressor
        m_rf = RandomForestRegressor(n_estimators=100, max_depth=10, random_state=42, n_jobs=-1)
        m_rf.fit(X_train, y_train)
        pred_rf = m_rf.predict(X_test)
        mae_rf = mean_absolute_error(y_test, pred_rf)
        rmse_rf = np.sqrt(mean_squared_error(y_test, pred_rf))
        mape_rf = mean_absolute_percentage_error(y_test, pred_rf)

        # Select best model based on lower RMSE
        if rmse_rf <= rmse_ridge:
            self.model = m_rf
            self.model_name = "RandomForestRegressor"
            self.metrics = {"MAE": round(float(mae_rf), 2), "RMSE": round(float(rmse_rf), 2), "MAPE": round(float(mape_rf) * 100, 2)}
        else:
            self.model = m_ridge
            self.model_name = "RidgeRegressor"
            self.metrics = {"MAE": round(float(mae_ridge), 2), "RMSE": round(float(rmse_ridge), 2), "MAPE": round(float(mape_ridge) * 100, 2)}

        # Persist trained model
        os.makedirs(os.path.dirname(self.model_path), exist_ok=True)
        joblib.dump(
            {
                "model": self.model,
                "model_name": self.model_name,
                "metrics": self.metrics,
                "feature_columns": self.feature_columns,
                "last_history": df_feat.tail(24)[["ds", "total_power_kw"]].to_dict(orient="records"),
            },
            self.model_path,
        )

        return {
            "selected_model": self.model_name,
            "metrics": self.metrics,
            "ridge_metrics": {"MAE": round(float(mae_ridge), 2), "RMSE": round(float(rmse_ridge), 2)},
            "rf_metrics": {"MAE": round(float(mae_rf), 2), "RMSE": round(float(rmse_rf), 2)},
            "test_samples": len(test_df),
        }

    def load_model(self) -> bool:
        """Loads cached model from disk."""
        if os.path.exists(self.model_path):
            try:
                pkg = joblib.load(self.model_path)
                self.model = pkg["model"]
                self.model_name = pkg["model_name"]
                self.metrics = pkg["metrics"]
                self.feature_columns = pkg["feature_columns"]
                return True
            except Exception:
                return False
        return False

    def generate_24h_forecast(self, start_time: Optional[datetime] = None) -> pd.DataFrame:
        """
        Generates recursive 24-hour ahead hourly load forecast with 95% confidence intervals.
        """
        if self.model is None and not self.load_model():
            self.train_and_evaluate()

        df_raw = self._extract_hourly_timeseries()
        df_feat = self._engineer_features(df_raw)

        if start_time is None:
            last_recorded_ts = df_feat["ds"].max()
            start_time = last_recorded_ts + timedelta(hours=1)

        forecast_records = []
        recent_loads = list(df_feat["total_power_kw"].tail(24).values)
        rmse = self.metrics.get("RMSE", 45.0)

        curr_time = start_time
        for step in range(24):
            hour = curr_time.hour
            dow = curr_time.weekday()
            is_wknd = 1 if dow in [5, 6] else 0

            sin_h = np.sin(2 * np.pi * hour / 24.0)
            cos_h = np.cos(2 * np.pi * hour / 24.0)
            sin_d = np.sin(2 * np.pi * dow / 7.0)
            cos_d = np.cos(2 * np.pi * dow / 7.0)

            lag_1 = recent_loads[-1] if recent_loads else 800.0
            lag_24 = recent_loads[-24] if len(recent_loads) >= 24 else lag_1

            feat_row = pd.DataFrame([{
                "hour": hour,
                "day_of_week": dow,
                "is_weekend": is_wknd,
                "sin_hour": sin_h,
                "cos_hour": cos_h,
                "sin_day": sin_d,
                "cos_day": cos_d,
                "lag_1": lag_1,
                "lag_24": lag_24,
            }])[self.feature_columns]

            pred_load = float(self.model.predict(feat_row)[0])
            pred_load = max(100.0, round(pred_load, 2))

            # 95% confidence intervals (+/- 1.96 * RMSE)
            margin = round(1.96 * rmse * (1.0 + step * 0.02), 2)
            lower_bound = max(0.0, round(pred_load - margin, 2))
            upper_bound = round(pred_load + margin, 2)

            forecast_records.append({
                "forecast_time": curr_time,
                "hour_of_day": hour,
                "predicted_load_kw": pred_load,
                "lower_ci_95": lower_bound,
                "upper_ci_95": upper_bound,
            })

            # Append prediction for recursive forecasting
            recent_loads.append(pred_load)
            curr_time += timedelta(hours=1)

        return pd.DataFrame(forecast_records)


if __name__ == "__main__":
    print("[AI FORECASTER] Training and evaluating models...")
    forecaster = LoadForecaster()
    res = forecaster.train_and_evaluate()
    print("Training Results:", res)

    fc_df = forecaster.generate_24h_forecast()
    print("\n24-Hour Forecast Sample (first 5 hours):")
    print(fc_df.head(5))
