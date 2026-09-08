import os
import sys

# Prevent OpenBLAS Memory Allocation errors on Windows with multiple processes
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"

import time
from datetime import datetime, date
import streamlit as st
import pandas as pd
import numpy as np
import altair as alt

# Add project root to path for imports
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from database.db import (
    load_telemetry_with_joins,
    load_alerts_from_db,
    load_streaming_aggregates,
    get_db_stats,
    insert_readings_and_alerts,
    seed_dimensions,
    init_db,
)
from analysis.analysis import (
    load_energy_data,
    calculate_kpis,
    get_building_summary,
    get_category_summary,
    get_meter_summary,
    get_time_series_trend,
    get_hourly_load_profile,
    get_day_of_week_profile,
    get_weekday_vs_weekend_summary,
    detect_anomalies,
)
from simulator.simulator import (
    generate_reading,
    create_meters,
    save_readings_to_csv,
    generate_historical_batch,
    CAMPUS_INFRASTRUCTURE,
)
from analysis.lake_analytics import (
    get_lake_metadata,
    query_lake_telemetry,
    query_lake_hourly_profile,
    query_lake_building_summary,
    benchmark_query_performance,
)
from scripts.compact_lake import run_compaction
from analysis.forecaster import LoadForecaster
from analysis.dispatch_engine import evaluate_dispatch_plan
from consumer.webhook_dispatcher import (
    dispatch_peak_shaving_alert,
    dispatch_scada_fault_alert,
    get_dispatch_history,
)

# ---------------------------------------------------------
# Page Configuration
# ---------------------------------------------------------
st.set_page_config(
    page_title="GridPulse | Smart Campus Energy Monitoring, Lakehouse & AI Dispatch",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------
# Custom Styling
# ---------------------------------------------------------
st.markdown(
    """
    <style>
    /* Metric Cards */
    [data-testid="stMetric"] {
        background: linear-gradient(135deg, rgba(255,255,255,0.06), rgba(255,255,255,0.02));
        border: 1px solid rgba(255, 255, 255, 0.12);
        border-radius: 12px;
        padding: 14px 18px;
        box-shadow: 0 4px 14px 0 rgba(0, 0, 0, 0.2);
    }
    [data-testid="stMetricValue"] {
        font-size: 1.8rem;
        font-weight: 700;
        color: #00d2ff;
    }
    [data-testid="stMetricLabel"] {
        font-size: 0.88rem;
        font-weight: 500;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    /* Tab Styling */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
    }
    .stTabs [data-baseweb="tab"] {
        border-radius: 8px 8px 0px 0px;
        padding: 10px 20px;
        font-weight: 600;
    }
    /* Badges */
    .badge {
        display: inline-block;
        padding: 4px 10px;
        border-radius: 20px;
        font-size: 0.8rem;
        font-weight: 600;
    }
    .badge-success { background-color: rgba(34, 197, 94, 0.2); color: #4ade80; border: 1px solid #22c55e; }
    .badge-warning { background-color: rgba(234, 179, 8, 0.2); color: #facc15; border: 1px solid #eab308; }
    .badge-danger { background-color: rgba(239, 68, 68, 0.2); color: #f87171; border: 1px solid #ef4444; }
    .badge-db { background-color: rgba(59, 130, 246, 0.2); color: #60a5fa; border: 1px solid #3b82f6; }
    </style>
    """,
    unsafe_allow_html=True,
)

RAW_DATA_PATH = os.path.join(PROJECT_ROOT, "data", "raw", "energy_data.csv")

# ---------------------------------------------------------
# Sidebar Controls & PostgreSQL Integration
# ---------------------------------------------------------
with st.sidebar:
    st.image("https://img.icons8.com/isometric/100/flash-on.png", width=64)
    st.title("GridPulse Controls")
    st.caption("Phase 2: Relational PostgreSQL (Neon) • SQL • Streamlit")
    st.markdown("---")

    # Storage Backend Selector
    st.subheader("Database Backend")
    data_source_mode = st.radio(
        "Data Source",
        ["🐘 PostgreSQL (Neon Cloud)", "📁 Local CSV File"],
        index=0,
    )

    db_connected = False
    db_stats = {}
    if data_source_mode.startswith("🐘"):
        try:
            db_stats = get_db_stats()
            db_connected = True
            st.markdown(
                f'<span class="badge badge-db">🐘 NEON POSTGRES CONNECTED</span><br>'
                f'<small style="color:#94a3b8;">Tables: <b>buildings ({db_stats.get("building_count", 0)})</b> • '
                f'<b>meters ({db_stats.get("meter_count", 0)})</b><br>'
                f'<b>readings ({db_stats.get("readings_count", 0):,})</b> • '
                f'<b>alerts ({db_stats.get("alerts_count", 0):,})</b></small>',
                unsafe_allow_html=True,
            )
        except Exception as e:
            st.error(f"PostgreSQL connection error: {e}")
            st.info("Falling back to local CSV mode.")
            data_source_mode = "📁 Local CSV File"

    st.markdown("---")
    st.subheader("SQL Pushdown Filters")

    # Category Filter
    categories = ["All Categories", "Hostels", "Departments", "Lecture Theatres", "Facilities"]
    selected_cat = st.selectbox("Category ▼", categories, index=0)

    # Building Filter (Dynamically computed from CAMPUS_INFRASTRUCTURE)
    if selected_cat == "All Categories":
        bldgs_list = []
        for cat_bldgs in CAMPUS_INFRASTRUCTURE.values():
            bldgs_list.extend(cat_bldgs.keys())
    else:
        bldgs_list = list(CAMPUS_INFRASTRUCTURE.get(selected_cat, {}).keys())

    selected_bldg = st.selectbox("Building ▼", ["All Buildings"] + sorted(bldgs_list), index=0)

    # Meter Filter
    all_meters = create_meters()
    if selected_bldg != "All Buildings":
        filtered_meter_ids = [m["meter_id"] for m in all_meters if m["building_id"] == selected_bldg]
    elif selected_cat != "All Categories":
        filtered_meter_ids = [m["meter_id"] for m in all_meters if m["building_type"] == selected_cat]
    else:
        filtered_meter_ids = [m["meter_id"] for m in all_meters]

    selected_meter = st.selectbox("Meter ▼", ["All Meters"] + sorted(filtered_meter_ids), index=0)

    # Timeline aggregation
    time_resample = st.selectbox("Timeline Resolution", ["15min", "30min", "1h", "3h", "1D"], index=2)

    st.markdown("---")
    st.subheader("Database Simulator & Actions")

    col_sim1, col_sim2 = st.columns(2)
    with col_sim1:
        if st.button("⚡ +1 Reading", help="Simulate a live reading for all 42 meters and insert into PostgreSQL"):
            meters = create_meters()
            now_dt = datetime.now()
            new_batch = [generate_reading(m, event_id=int(time.time()), dt=now_dt) for m in meters]
            save_readings_to_csv(new_batch, RAW_DATA_PATH, overwrite=False)
            if db_connected:
                insert_readings_and_alerts(new_batch)
            st.toast(f"Ingested {len(new_batch)} readings to PostgreSQL!", icon="⚡")
            time.sleep(0.5)
            st.rerun()
    with col_sim2:
        if st.button("🔄 7-Day Reset", help="Regenerate clean 7-day realistic historical dataset in PostgreSQL"):
            with st.spinner("Populating 7-day historical telemetry in PostgreSQL..."):
                generate_historical_batch(days=7, interval_minutes=30, output_path=RAW_DATA_PATH, save_to_db=True, overwrite_csv=True)
            st.toast("Regenerated 7-day profile in PostgreSQL!", icon="🔄")
            time.sleep(0.5)
            st.rerun()

    auto_refresh = st.checkbox("Auto Refresh (every 5s)", value=False)
    if auto_refresh:
        time.sleep(5)
        st.rerun()

# ---------------------------------------------------------
# Fetch Data using SQL Query Pushdown
# ---------------------------------------------------------
if data_source_mode.startswith("🐘") and db_connected:
    df_filtered = load_telemetry_with_joins(
        limit=25000,
        category=selected_cat if selected_cat != "All Categories" else None,
        building=selected_bldg if selected_bldg != "All Buildings" else None,
        meter=selected_meter if selected_meter != "All Meters" else None,
    )
    df_alerts_db = load_alerts_from_db(limit=500)
else:
    df_all = load_energy_data(RAW_DATA_PATH)
    df_filtered = df_all.copy()
    if selected_cat != "All Categories":
        df_filtered = df_filtered[df_filtered["building_type"] == selected_cat]
    if selected_bldg != "All Buildings":
        df_filtered = df_filtered[df_filtered["building_id"] == selected_bldg]
    if selected_meter != "All Meters":
        df_filtered = df_filtered[df_filtered["meter_id"] == selected_meter]
    df_alerts_db = pd.DataFrame()

kpis = calculate_kpis(df_filtered)
anomalies_info = detect_anomalies(df_filtered)

# ---------------------------------------------------------
# Dashboard Header
# ---------------------------------------------------------
col_head1, col_head2 = st.columns([3, 1])
with col_head1:
    st.title("⚡ GridPulse — Smart Campus Energy Telemetry")
    st.caption("Phase 2 Architecture: Python Simulator → PostgreSQL (Neon) → SQL → Pandas → Streamlit")

with col_head2:
    st.markdown("<br>", unsafe_allow_html=True)
    backend_badge = "badge-db" if data_source_mode.startswith("🐘") else "badge-success"
    backend_text = "🐘 POSTGRES LIVE" if data_source_mode.startswith("🐘") else "📁 CSV LOCAL"
    st.markdown(
        f'<div style="text-align: right;"><span class="badge {backend_badge}">● {backend_text}</span><br>'
        f'<small style="color: #94a3b8;">Active Sync: {kpis.get("latest_time", "N/A")}</small></div>',
        unsafe_allow_html=True,
    )

st.markdown("---")

# ---------------------------------------------------------
# Top KPIs Metric Row
# ---------------------------------------------------------
m1, m2, m3, m4, m5 = st.columns(5)
with m1:
    st.metric(
        label="Instantaneous Load",
        value=f"{kpis.get('current_total_load_kw', 0):,.1f} kW",
        delta=f"Avg: {kpis.get('avg_power_kw', 0)} kW",
    )
with m2:
    st.metric(
        label="Active Sub-Meters",
        value=f"{kpis.get('total_meters', 0)}",
        delta=f"{kpis.get('total_buildings', 0)} Buildings",
    )
with m3:
    st.metric(
        label="Nominal Voltage",
        value=f"{kpis.get('avg_voltage', 0)} V",
        delta="Standard: 230.0 V",
    )
with m4:
    st.metric(
        label="Power Factor (Avg)",
        value=f"{kpis.get('avg_power_factor', 0)}",
        delta="Target ≥ 0.90",
    )
with m5:
    anom_count = anomalies_info["total_anomalies"]
    st.metric(
        label="Grid Anomalies",
        value=f"{anom_count}",
        delta=f"{anomalies_info['voltage_sags']} sags, {anomalies_info['voltage_surges']} surges",
        delta_color="inverse",
    )

st.markdown("<br>", unsafe_allow_html=True)

# ---------------------------------------------------------
# Main Tabs Layout
# ---------------------------------------------------------
tab_realtime, tab_lakehouse, tab_forecast, tab_trends, tab_schedules, tab_hierarchy, tab_anomalies, tab_db_schema, tab_explorer = st.tabs([
    "⚡ Phase 4: Real-Time Stream",
    "🧊 Phase 5: Data Lakehouse",
    "🔮 Phase 6: AI Forecasting & Dispatch",
    "📈 Multi-Day Timeline",
    "🕒 24-Hour & Schedule Curves",
    "🏢 Infrastructure & Buildings",
    "⚠️ Grid Health & PostgreSQL Alerts",
    "🏛️ Relational DB Schema",
    "🗂️ Telemetry Query Explorer",
])

# ---------------------------------------------------------
# Tab 0: Phase 4 Real-Time Streaming View
# ---------------------------------------------------------
with tab_realtime:
    st.subheader("⚡ Live Kafka-Spark Streaming Analytics (PostgreSQL Aggregates)")
    st.caption("Powered by Spark Structured Streaming with 5-minute sliding windows.")
    
    @st.fragment(run_every="3s")
    def realtime_streaming_view():
        if not (data_source_mode.startswith("🐘") and db_connected):
            st.warning("Connect to PostgreSQL to view live streaming analytics.")
            return

        df_agg = load_streaming_aggregates(limit=1000)
        
        if df_agg.empty:
            st.info("Waiting for streaming data... Ensure Kafka producer and Spark processor are running.")
            return

        # Latest window stats
        latest_window = df_agg["window_end"].max()
        df_latest = df_agg[df_agg["window_end"] == latest_window]
        
        current_load = df_latest["avg_power_kw"].sum()
        current_voltage = df_latest["avg_voltage_v"].mean()
        
        # Historical stats for comparison (from the global filtered dataframe)
        hist_avg_load = kpis.get('avg_power_kw', 0)
        hist_avg_voltage = kpis.get('avg_voltage', 0)
        
        m1, m2, m3 = st.columns(3)
        with m1:
            st.metric("Live Aggregated Load (kW)", f"{current_load:,.1f}", delta=f"vs Hist: {(current_load - hist_avg_load):.1f} kW", delta_color="inverse")
        with m2:
            st.metric("Live Avg Voltage (V)", f"{current_voltage:.1f}", delta=f"vs Hist: {(current_voltage - hist_avg_voltage):.1f} V")
        with m3:
            st.metric("Last Sliding Window End", latest_window.strftime("%H:%M:%S"))

        st.markdown("#### Live 5-Minute Sliding Window Timeline")
        
        # Timeline chart
        agg_timeline = df_agg.groupby("window_end")["avg_power_kw"].sum().reset_index()
        # Filter for the last 60 minutes for real-time zooming effect
        recent_cutoff = agg_timeline["window_end"].max() - pd.Timedelta(minutes=60)
        agg_timeline = agg_timeline[agg_timeline["window_end"] >= recent_cutoff]
        
        chart_live = (
            alt.Chart(agg_timeline)
            .mark_area(
                line={"color": "#facc15", "strokeWidth": 3},
                color=alt.Gradient(
                    gradient="linear",
                    stops=[
                        alt.GradientStop(color="rgba(250, 204, 21, 0.45)", offset=0),
                        alt.GradientStop(color="rgba(250, 204, 21, 0.0)", offset=1),
                    ],
                    x1=1, x2=1, y1=1, y2=0,
                )
            )
            .encode(
                x=alt.X("window_end:T", title="Sliding Window End"),
                y=alt.Y("avg_power_kw:Q", title="Total Aggregated Power (kW)"),
                tooltip=["window_end:T", "avg_power_kw:Q"]
            )
            .properties(height=280)
            .interactive()
        )
        st.altair_chart(chart_live, use_container_width=True)
        
        st.markdown("#### Raw Aggregates Stream")
        st.dataframe(df_agg.head(50), use_container_width=True, hide_index=True)

    # Render fragment
    realtime_streaming_view()

# ---------------------------------------------------------
# Tab 1: Phase 5 Data Lakehouse Explorer (DuckDB & Parquet)
# ---------------------------------------------------------
with tab_lakehouse:
    st.subheader("🧊 Phase 5: Columnar Data Lakehouse & Cold Path Analytics")
    st.caption("Zero-copy, in-process analytical query processing over Snappy-compressed Parquet files via DuckDB.")

    lake_meta = get_lake_metadata()

    if not lake_meta["exists"] or lake_meta["total_records"] == 0:
        st.warning("⚠️ No Data Lake partitions detected on disk at `data/lake/raw_telemetry`.")
        col_gen1, col_gen2 = st.columns([2, 1])
        with col_gen1:
            st.info("Hydrate the lakehouse from historical CSV data or let Spark Structured Streaming write micro-batches.")
        with col_gen2:
            if st.button("🚀 Hydrate Lake from Raw CSV", use_container_width=True):
                from simulator.lake_exporter import export_from_csv
                with st.spinner("Hydrating partitioned Parquet lake..."):
                    cnt = export_from_csv()
                    st.success(f"Successfully generated {cnt:,} records across partitions!")
                    time.sleep(1)
                    st.rerun()
    else:
        # 1. Health & Storage Metric Cards
        col_l1, col_l2, col_l3, col_l4 = st.columns(4)
        with col_l1:
            st.metric("Total Archived Records", f"{lake_meta['total_records']:,}")
        with col_l2:
            st.metric("Active Partitions", f"{len(lake_meta['partitions'])} Days")
        with col_l3:
            st.metric("Lake Storage Footprint", f"{lake_meta['total_size_mb']} MB", delta=f"{lake_meta['total_files']} files")
        with col_l4:
            ts_span = ""
            if lake_meta['min_timestamp'] and lake_meta['max_timestamp']:
                ts_span = f"{pd.to_datetime(lake_meta['min_timestamp']).strftime('%b %d')} - {pd.to_datetime(lake_meta['max_timestamp']).strftime('%b %d')}"
            st.metric("Time Horizon", ts_span if ts_span else "N/A", delta=f"{lake_meta['meters_count']} Meters")

        # 2. Performance Benchmark & Small-File Compaction Bar
        with st.expander("⚡ Columnar Speedup Benchmark & Compaction Engine", expanded=True):
            col_b1, col_b2 = st.columns([2, 1])
            with col_b1:
                st.markdown("##### 🚀 Hot vs Cold Analytical Query Latency")
                bench = benchmark_query_performance()
                ratio_str = f"{bench['speedup_ratio']}x faster" if bench.get('speedup_ratio') else "Vectorized In-Process"
                st.markdown(
                    f"""
                    - **Cold Path (DuckDB over Parquet):** `{bench['lake_time_ms']} ms` for `{bench['scanned_rows']:,}` rows.
                    - **Hot Path (PostgreSQL Relational):** `{bench['db_time_ms'] if bench['db_time_ms'] else 'N/A'} ms`.
                    - **Performance Acceleration:** **{ratio_str}**
                    """
                )
            with col_b2:
                st.markdown("##### 🧹 Micro-Batch Compaction")
                st.caption("Coalesce 30s Spark micro-batch files into consolidated daily Parquet blocks.")
                if st.button("Run Lake Compaction", use_container_width=True):
                    with st.spinner("Compacting small parquet part files..."):
                        comp_res = run_compaction()
                        if comp_res["status"] == "SUCCESS":
                            st.success(
                                f"Compaction finished in {comp_res['elapsed_ms']}ms. "
                                f"Reduced {comp_res['total_files_before']} -> {comp_res['total_files_after']} files "
                                f"across {comp_res['partitions_compacted']} partitions."
                            )
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error(comp_res.get("message", "Compaction failed"))

        st.markdown("<br>", unsafe_allow_html=True)

        # 3. Analytical Lake Queries
        col_q1, col_q2 = st.columns([1, 2])
        with col_q1:
            st.markdown("#### 🔍 Partition Filter")
            cat_list = ["All", "Hostels", "Departments", "Facilities", "Lecture Theatres"]
            selected_cat = st.selectbox("Building Category", cat_list, key="lake_cat")
            limit_val = st.slider("Query Row Limit", 100, 5000, 1000, step=100, key="lake_limit")
            
            st.markdown("#### 📂 Partitions on Disk")
            st.code("\n".join(lake_meta["partitions"][:10]) + ("\n..." if len(lake_meta["partitions"]) > 10 else ""), language="text")

        with col_q2:
            st.markdown("#### 🕒 Cold-Path 24-Hour Diurnal Load Profile (DuckDB)")
            hourly_lake_df = query_lake_hourly_profile(building_type=selected_cat)
            if not hourly_lake_df.empty:
                chart_lake_hourly = (
                    alt.Chart(hourly_lake_df)
                    .mark_line(point=True, strokeWidth=3, color="#38bdf8")
                    .encode(
                        x=alt.X("hour:O", title="Hour of Day (0-23)"),
                        y=alt.Y("avg_power_kw:Q", title="Mean Power (kW)"),
                        tooltip=["hour:O", "avg_power_kw:Q", "min_power_kw:Q", "max_power_kw:Q", "avg_voltage_v:Q"]
                    )
                    .properties(height=260)
                )
                st.altair_chart(chart_lake_hourly, use_container_width=True)

        st.markdown("#### 🏢 Building Energy Aggregates (Scanned Directly from Parquet)")
        bld_summary_df = query_lake_building_summary()
        if not bld_summary_df.empty:
            chart_bld_bar = (
                alt.Chart(bld_summary_df)
                .mark_bar(color="#0ea5e9", cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
                .encode(
                    x=alt.X("building_id:N", sort="-y", title="Campus Building"),
                    y=alt.Y("avg_power_kw:Q", title="Average Load (kW)"),
                    color=alt.Color("building_type:N", title="Category"),
                    tooltip=["building_id", "building_type", "avg_power_kw", "est_total_kwh", "meter_count"]
                )
                .properties(height=260)
            )
            st.altair_chart(chart_bld_bar, use_container_width=True)

        st.markdown("#### 🗄️ Ad-Hoc Parquet Query View")
        lake_query_df = query_lake_telemetry(building_type=selected_cat, limit=limit_val)
        st.dataframe(lake_query_df, use_container_width=True, hide_index=True)

# ---------------------------------------------------------
# Tab 2: Phase 6 AI Forecasting & Automated Dispatch
# ---------------------------------------------------------
with tab_forecast:
    st.subheader("🔮 Phase 6: Predictive AI Load Forecasting & Automated Dispatch")
    st.caption("24-Hour ahead recursive energy forecasting with 95% confidence bounds and automated demand-response peak-shaving dispatch.")

    forecaster = LoadForecaster()
    is_loaded = forecaster.load_model()
    if not is_loaded:
        with st.spinner("Training predictive time-series models on historical telemetry..."):
            forecaster.train_and_evaluate()

    # 1. Model Performance & Configuration Bar
    col_fc1, col_fc2 = st.columns([2, 1])
    with col_fc1:
        st.markdown("##### 🧠 Active AI Forecasting Model")
        m_name = forecaster.model_name or "RandomForestRegressor"
        metrics = forecaster.metrics or {}
        st.markdown(
            f"""
            - **Architecture:** `{m_name}` (Chronological Train/Validation Split)
            - **Evaluation Error Metrics:** MAE: `{metrics.get('MAE', 'N/A')} kW` | RMSE: `{metrics.get('RMSE', 'N/A')} kW` | MAPE: `{metrics.get('MAPE', 'N/A')}%`
            - **Input Features:** Cyclical Fourier Harmonics ($\sin/\cos$), Academic Day, Autoregressive Lags ($t-1, t-24$).
            """
        )
    with col_fc2:
        st.markdown("##### ⚙️ Contract Threshold Controls")
        peak_threshold_input = st.slider("Contract Demand Limit (kW)", min_value=600.0, max_value=1200.0, value=780.0, step=20.0, key="peak_thresh_slider")
        tariff_input = st.number_input("Demand Charge (INR/kW/mo)", min_value=100.0, max_value=1000.0, value=350.0, step=25.0, key="tariff_slider")

    # 2. Generate 24-Hour Predictions & Evaluate Dispatch
    pred_df = forecaster.generate_24h_forecast()
    dispatch_plan = evaluate_dispatch_plan(pred_df, peak_threshold_kw=peak_threshold_input, tariff_rate=tariff_input)

    st.markdown("<br>", unsafe_allow_html=True)

    # 3. Peak Demand Status & Financial KPIs
    col_k1, col_k2, col_k3, col_k4 = st.columns(4)
    with col_k1:
        st.metric("24h Peak Forecast", f"{dispatch_plan['peak_forecast_kw']:,.1f} kW")
    with col_k2:
        st.metric("Contract Demand Limit", f"{dispatch_plan['threshold_kw']:,.1f} kW")
    with col_k3:
        delta_color = "inverse" if dispatch_plan["has_violations"] else "normal"
        overload_str = f"+{dispatch_plan['max_overload_kw']:.1f} kW" if dispatch_plan["has_violations"] else "0.0 kW (Nominal)"
        st.metric("Projected Peak Overload", overload_str, delta=f"{dispatch_plan['violation_hours_count']} Hours Impacted", delta_color=delta_color)
    with col_k4:
        st.metric("Demand Tariff Savings", f"INR {dispatch_plan['est_monthly_savings']:,.0f}", delta=f"Cap: {dispatch_plan['total_shed_kw']:.0f} kW")

    # 4. Forecast Horizon & Dispatch Visualizations
    st.markdown("#### 📈 24-Hour Forecast Horizon vs Peak Demand Limit")
    chart_data = dispatch_plan["adjusted_forecast_df"].copy()
    chart_data["contract_threshold"] = peak_threshold_input

    # Base line: Predicted load
    base_chart = alt.Chart(chart_data).encode(x=alt.X("forecast_time:T", title="Forecast Horizon (Next 24 Hours)"))

    # Confidence interval band
    band = base_chart.mark_area(opacity=0.2, color="#38bdf8").encode(
        y=alt.Y("lower_ci_95:Q", title="Grid Power Demand (kW)"),
        y2=alt.Y2("upper_ci_95:Q"),
    )

    # Predicted load line
    pred_line = base_chart.mark_line(color="#38bdf8", strokeWidth=3).encode(
        y=alt.Y("predicted_load_kw:Q"),
        tooltip=[
            alt.Tooltip("forecast_time:T", title="Time"),
            alt.Tooltip("predicted_load_kw:Q", title="Forecast (kW)"),
            alt.Tooltip("dispatched_load_kw:Q", title="Dispatched (kW)"),
            alt.Tooltip("lower_ci_95:Q", title="Lower 95%"),
            alt.Tooltip("upper_ci_95:Q", title="Upper 95%"),
        ],
    )

    # Post-dispatch line
    disp_line = base_chart.mark_line(color="#10b981", strokeWidth=3, strokeDash=[5, 5]).encode(
        y=alt.Y("dispatched_load_kw:Q")
    )

    # Threshold rule
    rule = alt.Chart(chart_data).mark_rule(color="#ef4444", strokeWidth=2).encode(
        y=alt.Y("contract_threshold:Q")
    )

    combined_fc_chart = (band + pred_line + disp_line + rule).properties(height=320).interactive()
    st.altair_chart(combined_fc_chart, use_container_width=True)
    st.caption("🔵 Solid Blue: Uncontrolled AI Forecast | 🟢 Dashed Green: Post-Dispatch Profile | 🔴 Red: Contract Demand Limit | Shaded Blue: 95% Confidence Band")

    st.markdown("<br>", unsafe_allow_html=True)

    # 5. Automated Demand-Response Directives
    st.markdown("#### ⚡ Automated Demand-Response Directives (Peak-Shaving Actions)")
    if not dispatch_plan["has_violations"]:
        st.success("✅ **Campus Grid Nominal:** Peak load remains within contract demand threshold. No automated load-shedding required.")
    else:
        st.warning(f"⚠️ **Peak Demand Mitigation Active:** {dispatch_plan['violation_hours_count']} hours exceed contract capacity. Prescriptive dispatch countermeasures engaged:")
        for action in dispatch_plan["actions"]:
            col_a1, col_a2 = st.columns([3, 1])
            with col_a1:
                tier_badge = "🟢 Tier 1 (Soft)" if action['tier'] == 1 else ("🟡 Tier 2 (Chillers)" if action['tier'] == 2 else "🔴 Tier 3 (BESS)")
                st.markdown(f"**{tier_badge}: {action['name']}**")
                st.write(f"_{action['action_desc']}_")
                st.caption(f"**Target Zones:** {', '.join(action['target_zones'])} | **Meters:** {', '.join(action['target_meters'])}")
            with col_a2:
                status_color = "green" if action['status'] == "ARMED" else "gray"
                st.markdown(f"<span style='color:{status_color}; font-weight:bold;'>STATUS: {action['status']}</span>", unsafe_allow_html=True)
                st.metric("Active Shed Target", f"{action['active_shed_kw']:.1f} kW", delta=f"Cap: {action['shed_capacity_kw']:.0f} kW")
            st.divider()

    # 6. Automated Webhook Alert Dispatcher Console
    with st.expander("🔔 Automated Incident Webhook Dispatcher Console", expanded=True):
        default_wh = os.getenv("ALERT_WEBHOOK_URL", "")
        col_cfg1, col_cfg2 = st.columns([3, 1])
        with col_cfg1:
            active_wh = st.text_input(
                "Target Webhook Endpoint URL (Slack, Discord, or Webhook.site)",
                value=st.session_state.get("webhook_url_input", default_wh),
                placeholder="https://hooks.slack.com/services/... or https://webhook.site/...",
                help="Paste your Slack webhook, Discord webhook (append /slack), or free https://webhook.site URL.",
                key="wh_url_field",
            )
            st.session_state["webhook_url_input"] = active_wh
        with col_cfg2:
            st.markdown("<br>", unsafe_allow_html=True)
            if active_wh and active_wh.startswith("http"):
                st.markdown("<span class='badge badge-success'>🟢 LIVE WEBHOOK ACTIVE</span>", unsafe_allow_html=True)
            else:
                st.markdown("<span class='badge badge-warning'>🟡 MOCK CONSOLE MODE</span>", unsafe_allow_html=True)

        st.markdown("---")
        col_wh1, col_wh2 = st.columns([2, 1])
        with col_wh1:
            st.markdown("##### 🚀 External Webhook Notification Engine")
            st.caption("Delivers rich incident cards to Slack, Discord, MS Teams, or HTTP endpoints with zero code changes.")
            recent_logs = get_dispatch_history()
            if recent_logs:
                st.dataframe(pd.DataFrame(recent_logs)[["timestamp", "event_type", "title", "status", "status_code"]], use_container_width=True, hide_index=True)
            else:
                st.info("No webhooks dispatched yet. Trigger a simulated dispatch below.")
        with col_wh2:
            st.markdown("##### ⚡ Trigger Alert Payloads")
            if st.button("📢 Dispatch Peak Shaving Alert", use_container_width=True):
                rec = dispatch_peak_shaving_alert(dispatch_plan, webhook_url=active_wh if active_wh else None)
                if rec["status"] == "SENT":
                    st.success(f"Dispatched Peak Alert to Webhook! (HTTP {rec['status_code']})")
                else:
                    st.info(f"Dispatched to Mock Console: {rec['status']}")
                time.sleep(1)
                st.rerun()

            if st.button("🚨 Dispatch SCADA Fault Alert", use_container_width=True):
                rec = dispatch_scada_fault_alert(
                    meter_id="M001",
                    building_id="BH1",
                    alert_type="VOLTAGE_SAG",
                    severity="CRITICAL",
                    metric_value=212.4,
                    threshold_value=220.0,
                    webhook_url=active_wh if active_wh else None,
                )
                if rec["status"] == "SENT":
                    st.success(f"Dispatched SCADA Alert to Webhook! (HTTP {rec['status_code']})")
                else:
                    st.info(f"Dispatched to Mock Console: {rec['status']}")
                time.sleep(1)
                st.rerun()

# ---------------------------------------------------------
# Tab 3: Multi-Day Timeline
# ---------------------------------------------------------
with tab_trends:
    st.subheader("Campus Aggregate Power Load Over Time")

    trend_df = get_time_series_trend(df_filtered, freq=time_resample)
    if not trend_df.empty:
        chart_power = (
            alt.Chart(trend_df)
            .mark_area(
                line={"color": "#00d2ff", "strokeWidth": 2},
                color=alt.Gradient(
                    gradient="linear",
                    stops=[
                        alt.GradientStop(color="rgba(0, 210, 255, 0.45)", offset=0),
                        alt.GradientStop(color="rgba(0, 210, 255, 0.0)", offset=1),
                    ],
                    x1=1,
                    x2=1,
                    y1=1,
                    y2=0,
                ),
            )
            .encode(
                x=alt.X("timestamp:T", title="Date & Time"),
                y=alt.Y("total_power_kw:Q", title="Aggregate Power (kW)"),
                tooltip=[
                    alt.Tooltip("timestamp:T", title="Timestamp"),
                    alt.Tooltip("total_power_kw:Q", title="Total kW", format=".1f"),
                    alt.Tooltip("avg_voltage_v:Q", title="Avg Voltage (V)", format=".1f"),
                    alt.Tooltip("avg_power_factor:Q", title="Power Factor", format=".3f"),
                ],
            )
            .properties(height=340)
            .interactive()
        )
        st.altair_chart(chart_power, use_container_width=True)

        col_sub1, col_sub2 = st.columns(2)
        with col_sub1:
            st.markdown("#### Grid Voltage Fluctuation (V)")
            chart_voltage = (
                alt.Chart(trend_df)
                .mark_line(color="#a855f7")
                .encode(
                    x=alt.X("timestamp:T", title="Time"),
                    y=alt.Y("avg_voltage_v:Q", scale=alt.Scale(domain=[215, 245]), title="Voltage (V)"),
                    tooltip=["timestamp:T", "avg_voltage_v:Q"],
                )
                .properties(height=230)
            )
            st.altair_chart(chart_voltage, use_container_width=True)

        with col_sub2:
            st.markdown("#### Power Factor Degradation Curve")
            chart_pf = (
                alt.Chart(trend_df)
                .mark_line(color="#10b981")
                .encode(
                    x=alt.X("timestamp:T", title="Time"),
                    y=alt.Y("avg_power_factor:Q", scale=alt.Scale(domain=[0.82, 1.0]), title="Power Factor"),
                    tooltip=["timestamp:T", "avg_power_factor:Q"],
                )
                .properties(height=230)
            )
            st.altair_chart(chart_pf, use_container_width=True)
    else:
        st.info("No time series data available for the selected filters.")

# ---------------------------------------------------------
# Tab 2: 24-Hour & Schedule Curves
# ---------------------------------------------------------
with tab_schedules:
    st.subheader("🕒 Diurnal & Schedule Pattern Analysis")
    st.caption("Visual proof of class hours (9 AM - 6 PM), weekend shifts, and Sunday facility closures")

    col_sch1, col_sch2 = st.columns(2)

    with col_sch1:
        st.markdown("#### 24-Hour Diurnal Load Curve (00:00 to 23:00)")
        hourly_profile = get_hourly_load_profile(df_filtered, group_by_category=True)
        if not hourly_profile.empty:
            chart_hourly = (
                alt.Chart(hourly_profile)
                .mark_line(point=True, strokeWidth=2.5)
                .encode(
                    x=alt.X("hour:O", title="Hour of Day (0-23)"),
                    y=alt.Y("avg_power_kw:Q", title="Average Power (kW)"),
                    color=alt.Color("building_type:N", title="Category"),
                    tooltip=["hour:O", "building_type:N", "avg_power_kw:Q"],
                )
                .properties(height=320)
                .interactive()
            )
            st.altair_chart(chart_hourly, use_container_width=True)

    with col_sch2:
        st.markdown("#### Weekday vs Weekend Demand Comparison")
        ww_summary = get_weekday_vs_weekend_summary(df_filtered)
        if not ww_summary.empty:
            chart_ww = (
                alt.Chart(ww_summary)
                .mark_bar(cornerRadius=6)
                .encode(
                    x=alt.X("day_type:N", title="Day Type"),
                    y=alt.Y("avg_power_kw:Q", title="Average Load (kW)"),
                    color=alt.Color("day_type:N", legend=None, scale=alt.Scale(range=["#00d2ff", "#f59e0b"])),
                    column=alt.Column("building_type:N", title="Infrastructure Category"),
                    tooltip=["building_type:N", "day_type:N", "avg_power_kw:Q", "peak_power_kw:Q"],
                )
                .properties(height=280)
            )
            st.altair_chart(chart_ww, use_container_width=True)

    st.markdown("---")
    st.subheader("📅 Day-of-the-Week Load Distribution & Sunday Library Analysis")
    
    col_dow1, col_dow2 = st.columns([1, 1])
    with col_dow1:
        st.markdown("#### Daily Average Load by Category")
        dow_profile = get_day_of_week_profile(df_filtered)
        if not dow_profile.empty:
            chart_dow = (
                alt.Chart(dow_profile)
                .mark_bar(cornerRadius=4)
                .encode(
                    x=alt.X("day_name:N", sort=["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"], title="Day of Week"),
                    y=alt.Y("avg_power_kw:Q", title="Average Power (kW)"),
                    color=alt.Color("building_type:N", title="Category"),
                    tooltip=["day_name:N", "building_type:N", "avg_power_kw:Q"],
                )
                .properties(height=280)
            )
            st.altair_chart(chart_dow, use_container_width=True)

    with col_dow2:
        st.markdown("#### 📚 Central Library: Sunday Closure vs Weekday Operation")
        df_lib = df_filtered[df_filtered["building_id"] == "Library"]
        if not df_lib.empty:
            lib_daily = df_lib.groupby(["day_name", "day_of_week"]).agg(
                avg_power_kw=("power_kw", "mean"),
                peak_power_kw=("power_kw", "max"),
            ).reset_index().sort_values("day_of_week")

            chart_lib = (
                alt.Chart(lib_daily)
                .mark_bar(cornerRadius=5)
                .encode(
                    x=alt.X("day_name:N", sort=["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"], title="Day"),
                    y=alt.Y("avg_power_kw:Q", title="Library Avg Power (kW)"),
                    color=alt.condition(
                        alt.datum.day_name == "Sunday",
                        alt.value("#ef4444"),
                        alt.value("#3b82f6"),
                    ),
                    tooltip=["day_name:N", "avg_power_kw:Q", "peak_power_kw:Q"],
                )
                .properties(height=280)
            )
            st.altair_chart(chart_lib, use_container_width=True)
            st.caption("🔴 Red bar highlights Sunday closure (~2.5 kW standby vs ~28 kW weekday operations).")

# ---------------------------------------------------------
# Tab 3: Infrastructure & Buildings
# ---------------------------------------------------------
with tab_hierarchy:
    col_c1, col_c2 = st.columns([1, 1])

    with col_c1:
        st.subheader("Category Energy Share")
        cat_summary = get_category_summary(df_filtered)
        if not cat_summary.empty:
            bar_cat = (
                alt.Chart(cat_summary)
                .mark_bar(cornerRadius=6)
                .encode(
                    x=alt.X("total_energy_kw_sum:Q", title="Total Cumulative Load (kW Sum)"),
                    y=alt.Y("building_type:N", sort="-x", title="Category"),
                    color=alt.Color("building_type:N", legend=None, scale=alt.Scale(scheme="tealblues")),
                    tooltip=[
                        alt.Tooltip("building_type:N", title="Category"),
                        alt.Tooltip("total_energy_kw_sum:Q", title="Cumulative kW", format=".1f"),
                        alt.Tooltip("avg_power_kw:Q", title="Avg Meter Load (kW)", format=".1f"),
                        alt.Tooltip("building_count:Q", title="Buildings"),
                        alt.Tooltip("meter_count:Q", title="Meters"),
                    ],
                )
                .properties(height=280)
            )
            st.altair_chart(bar_cat, use_container_width=True)
            st.dataframe(cat_summary, use_container_width=True, hide_index=True)

    with col_c2:
        st.subheader("Top Consuming Buildings")
        bldg_summary = get_building_summary(df_filtered)
        if not bldg_summary.empty:
            bar_bldg = (
                alt.Chart(bldg_summary.head(10))
                .mark_bar(cornerRadius=6)
                .encode(
                    x=alt.X("avg_power_kw:Q", title="Average Power (kW)"),
                    y=alt.Y("building_id:N", sort="-x", title="Building"),
                    color=alt.Color("building_type:N", title="Category"),
                    tooltip=["building_id:N", "building_type:N", "avg_power_kw:Q", "peak_power_kw:Q", "meter_count:Q"],
                )
                .properties(height=280)
            )
            st.altair_chart(bar_bldg, use_container_width=True)
            st.dataframe(bldg_summary.head(10), use_container_width=True, hide_index=True)

    st.markdown("---")
    st.subheader("Sub-Meter Individual Telemetry Breakdown")
    meter_summary = get_meter_summary(df_filtered)
    st.dataframe(meter_summary, use_container_width=True, hide_index=True)

# ---------------------------------------------------------
# Tab 4: Grid Health & PostgreSQL Alerts
# ---------------------------------------------------------
with tab_anomalies:
    st.subheader("⚠️ Power Quality & PostgreSQL Alerts Table")
    st.caption("Directly queried from the `alerts` relational table in PostgreSQL")

    a1, a2, a3 = st.columns(3)
    with a1:
        st.markdown(
            f"""
            <div style="padding:15px; border-radius:10px; background:rgba(239, 68, 68, 0.1); border:1px solid #ef4444;">
                <h4 style="margin:0; color:#f87171;">🔻 Voltage Sags (<220V)</h4>
                <h2 style="margin:5px 0 0 0; color:#f87171;">{anomalies_info['voltage_sags']}</h2>
                <small>Motor stalls and equipment brownout</small>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with a2:
        st.markdown(
            f"""
            <div style="padding:15px; border-radius:10px; background:rgba(234, 179, 8, 0.1); border:1px solid #eab308;">
                <h4 style="margin:0; color:#facc15;">🔺 Voltage Surges (>240V)</h4>
                <h2 style="margin:5px 0 0 0; color:#facc15;">{anomalies_info['voltage_surges']}</h2>
                <small>Transformer thermal stress and capacitor failures</small>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with a3:
        st.markdown(
            f"""
            <div style="padding:15px; border-radius:10px; background:rgba(168, 85, 247, 0.1); border:1px solid #a855f7;">
                <h4 style="margin:0; color:#c084fc;">⚡ Low Power Factor (<0.88)</h4>
                <h2 style="margin:5px 0 0 0; color:#c084fc;">{anomalies_info['low_power_factor']}</h2>
                <small>Reactive power penalty & grid line losses</small>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown("<br>", unsafe_allow_html=True)
    if not df_alerts_db.empty:
        st.markdown("#### Live Relational Alerts Log (`alerts` JOIN `meters` JOIN `buildings`)")
        st.dataframe(df_alerts_db.head(100), use_container_width=True, hide_index=True)
    else:
        st.info("No alert records detected.")

# ---------------------------------------------------------
# Tab 5: Relational DB Schema
# ---------------------------------------------------------
with tab_db_schema:
    st.subheader("🏛️ Phase 2 Relational Database Schema (PostgreSQL)")
    st.markdown(
        """
        ```text
        ┌─────────────────────────┐
        │       BUILDINGS         │
        ├─────────────────────────┤
        │ PK  building_id         │◄────────┐
        │     building_name       │         │ 1-to-Many
        │     category            │         │
        └─────────────────────────┘         │
                                            │
        ┌─────────────────────────┐         │
        │         METERS          │         │
        ├─────────────────────────┤         │
        │ PK  meter_id            │         │
        │ FK  building_id         ├─────────┘
        │     meter_type          │◄────────┐
        │     status              │         │
        └─────────────────────────┘         │
                                            │
        ┌─────────────────────────┐         │ 1-to-Many
        │     ENERGY_READINGS     │         │
        ├─────────────────────────┤         │
        │ PK  id                  │         │
        │     event_id            │         │
        │     timestamp           │         │
        │ FK  meter_id            ├─────────┤
        │     power_kw            │         │
        │     voltage_v           │         │
        │     current_a           │         │
        │     power_factor        │         │
        └─────────────────────────┘         │
                                            │
        ┌─────────────────────────┐         │ 1-to-Many
        │         ALERTS          │         │
        ├─────────────────────────┤         │
        │ PK  id                  │         │
        │     event_id            │         │
        │     timestamp           │         │
        │ FK  meter_id            ├─────────┘
        │     alert_type          │
        │     severity            │
        │     metric_value        │
        │     threshold_value     │
        │     description         │
        └─────────────────────────┘
        ```
        """
    )

# ---------------------------------------------------------
# Tab 6: Telemetry Query Explorer
# ---------------------------------------------------------
with tab_explorer:
    st.subheader(f"Data Explorer — Source: {data_source_mode}")
    col_d1, col_d2 = st.columns([3, 1])
    with col_d1:
        data_view = st.radio("Select View", ["Latest Readings", "Calculated Apparent/Reactive Power (kVA/kVAR)"], horizontal=True)
    with col_d2:
        csv_data = df_filtered.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="📥 Export SQL Query to CSV",
            data=csv_data,
            file_name=f"gridpulse_postgres_telemetry_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
        )

    if data_view == "Latest Readings":
        st.dataframe(df_filtered, use_container_width=True, hide_index=True)
    else:
        df_proc = df_filtered.copy()
        df_proc["apparent_power_kva"] = round(df_proc["power_kw"] / df_proc["power_factor"], 2)
        df_proc["reactive_power_kvar"] = round(
            np.sqrt(np.maximum(0, df_proc["apparent_power_kva"] ** 2 - df_proc["power_kw"] ** 2)), 2
        )
        st.dataframe(df_proc, use_container_width=True, hide_index=True)
