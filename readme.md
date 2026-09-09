# ⚡ GridPulse: Smart Campus Energy Monitoring & Lakehouse Analytics

GridPulse is an enterprise-grade, end-to-end IoT data engineering pipeline and real-time analytical platform built for monitoring, analyzing, forecasting, and mitigating power grid telemetry across a university campus.

The platform evolves through **6 architectural phases**, transitioning from synthetic batch telemetry to a distributed streaming Lambda/Kappa architecture, cold-path Parquet Data Lakehouse, and prescriptive AI peak-shaving automation.

---

## 📚 Project Documentation
- 📑 **[System Architecture & Technical Design (docs/design.md)](docs/design.md)**: Comprehensive guide covering the 3-tier architecture, normalized 3NF schema, electrical formulas, hybrid ML anomaly engine, DuckDB lakehouse scans, and demand-response dispatch tiers.
- 🗺️ **[Architectural Phases & Roadmap (docs/phases.md)](docs/phases.md)**: Detailed phase milestones, transition history, operational deliverables, and verification matrices.

---

## 🗺️ Architectural Phases Matrix

| Phase | Phase Name | Status | Primary Stack | Key Deliverables |
| :--- | :--- | :---: | :--- | :--- |
| **Phase 1** | **Batch CSV & Synthetic Telemetry** | ✅ Complete | Python, Pandas, NumPy, CSV | 42-meter campus simulator, diurnal curves, apparent & reactive power ($kVA, kVAR$) |
| **Phase 2** | **Relational Warehouse & SQL Pushdown** | ✅ Complete | PostgreSQL (Neon), SQLAlchemy | 3NF schema, B-Tree indexes, pushdown filtering, voltage/PF threshold alerts |
| **Phase 3** | **Message Broker & ML Anomaly Ingestion** | ✅ Complete | Apache Kafka (KRaft), Isolation Forest | Decoupled event streaming (`gridpulse.telemetry.raw`), 3-tier ML anomaly detection |
| **Phase 4** | **Distributed Stream Processing** | ✅ Complete | Apache Spark 3.5, PySpark, Docker | 5-min sliding windows (1-min slide, 2-min watermark), 15s triggers, zero-flicker UI |
| **Phase 5** | **Data Lakehouse Storage & Cold Path** | ✅ Complete | Apache Parquet, Snappy, DuckDB | Partitioned time-series lake (`year/month/day`), DuckDB vector SQL (448x faster), compactor |
| **Phase 6** | **Predictive AI & Automated Dispatch** | ✅ Complete | Scikit-Learn, Random Forest, Webhooks | 24h recursive load forecasting, 3-tier peak-shaving dispatch, automated incident webhooks |
| **Phase 7** | **Enterprise Medallion Lakehouse & dbt** | ✅ Complete | dbt-duckdb, DuckDB, Jinja, Data Contracts | Bronze/Silver/Gold ELT models, 34 data contract assertions, dimensional enrichment, curated analytical marts |
| **Phase 8** | **ACID Lakehouse Table Format & Time-Travel** | ✅ Complete | Delta Lake (`deltalake`), DuckDB, PyArrow | Atomic commits (`_delta_log`), time-travel snapshots, dynamic schema evolution (`ambient_temp_c`), native OPTIMIZE compaction |

---

## 🏗️ End-to-End System Architecture

```text
[42 Smart Sub-Meters (19 Buildings)] 
           │
           ▼
[Kafka Producer (confluent-kafka)] ──JSON Events──► [Apache Kafka (KRaft Mode)]
                                                          │
                   ┌──────────────────────────────────────┴──────────────────────────────────────┐
                   ▼                                                                            ▼
       [Apache Spark 3.5.0]                                                           [Python ML Consumer]
   (5-min sliding window / 15s trigger)                                            (Isolation Forest + Z-Score)
                   │                                                                            │
         ┌─────────┴─────────┐                                                                  ▼
         ▼                   ▼                                                       [PostgreSQL Database]
  [PostgreSQL (Neon)]  [Parquet Lakehouse]                                           • Fact: energy_readings
• building_energy_     • data/lake/raw_telemetry/                                    • Events: alerts
  aggregates           • Snappy Columnar Store                                                  │
         │                   │                                                                  │
         ▼                   ▼                                                                  ▼
  [Live Real-Time View] [DuckDB In-Process Query] ◄─────────────────────────────────────────────┘
  (@st.fragment 3s)     (Sub-10ms Columnar Analytics)
                             │
                             ▼
                 [Phase 6: Predictive AI Forecaster]
                 • Random Forest Regressor (MAPE: 11.5%)
                 • 24-Hour Ahead Load Horizon (95% CI)
                             │
                             ▼
                 [3-Tier Demand Response Engine]
                 • Tier 1: Non-Critical Facility & EV Setback (-45 kW)
                 • Tier 2: Lecture Theatre HVAC Duty Cycling (-90 kW)
                 • Tier 3: Main Powerhouse BESS Injection (-160 kW)
                             │
                             ▼
                 [Automated Incident Webhook Dispatcher]
                 • Slack / Discord / MS Teams / HTTP Payloads
```

---

## 🚀 Quickstart & Execution Runbook

### 1. Launch Kafka Broker & Kafka UI
Start the containerized KRaft message broker:
```powershell
docker-compose up -d
```
*Kafka UI is available at `http://localhost:8080` to inspect topics and partitions.*

### 2. Start IoT Telemetry Kafka Producer
Stream live readings from all 42 smart sub-meters across campus:
```powershell
python simulator/kafka_producer.py
```

### 3. Launch Dockerized Spark Structured Streaming Processor
Run the distributed streaming engine inside Docker:
```powershell
.\run_spark.ps1
```
*Spark computes sliding-window aggregates to PostgreSQL every 15 seconds and dual-writes partitioned Parquet micro-batches to the Data Lake.*

### 4. Launch the Streamlit Monitoring Dashboard
Open the interactive presentation interface:
```powershell
streamlit run dashboard/app.py
```
*Navigate to `http://localhost:8501` to view:*
- **⚡ Tab 0 (Phase 4):** Live sliding-window stream with zero page flicker via `@st.fragment`.
- **🧊 Tab 1 (Phase 5 & 7):** Columnar Data Lakehouse Explorer & Medallion Architecture with dbt Gold Marts.
- **🔮 Tab 2 (Phase 6):** 24-Hour AI Predictive Load Forecast, Automated Peak-Shaving Directives, and Webhook Dispatcher Console.

### 5. Execute dbt Medallion Lakehouse ELT Pipeline
Trigger automated Bronze ➔ Silver ➔ Gold transformations with 34 automated contract assertion tests:
```powershell
python scripts/run_dbt.py --all
```

---

## 🧪 Automated Testing

Run the automated test suite covering all 8 architectural phases:
```powershell
python -m unittest discover -s tests -v
```
- ✅ `test_delta_lakehouse.py`: Delta Lake ACID commits, `_delta_log` audit integrity, schema evolution (`ambient_temp_c`), time-travel queries, and native `OPTIMIZE` in-place compaction.
- ✅ `test_dbt.py`: Medallion layers compilation, 34 schema contract tests, DuckDB objects verification, and Gold mart KPIs sanity.
- ✅ `test_simulator.py`: Physics calculations, electrical conversions, campus topology.
- ✅ `test_lakehouse.py`: Parquet lake metadata extraction, DuckDB partition queries, compaction engine.
- ✅ `test_forecasting.py`: Chronological train/test split, model evaluation, 24-hour forecast array & confidence intervals.
- ✅ `test_dispatch.py`: Peak demand threshold breach triggers, tiered load-shedding directives, webhook payload formatting.

---

## 🛠️ Optimization & Engineering Highlights
- **ACID Lakehouse Table Format:** Engineered an ACID Data Lakehouse using Delta Lake over partitioned Parquet; implemented time-travel snapshot auditing and schema evolution (`ambient_temp_c`), reducing cold-path scan latencies by 70% with DuckDB vectorization.
- **Columnar Speedup:** DuckDB scanned 18,522 records directly over Parquet partitions in **5.33 ms** compared to **2,389 ms** in PostgreSQL — a **448.2x speedup** for historical analytics.
- **Small-File Compaction:** [`scripts/compact_lake.py`](scripts/compact_lake.py) and native Delta `OPTIMIZE` coalesce high-frequency streaming micro-batch files into unified daily Parquet blocks, eliminating file system I/O bottlenecks.
- **Zero Data Leakage:** AI forecaster features temporal cyclical Fourier harmonics and strictly chronological splits.
- **Zero-Flicker Dashboard:** Utilizes Streamlit modern fragments to update real-time charts asynchronously every 3 seconds without full-page re-renders.
