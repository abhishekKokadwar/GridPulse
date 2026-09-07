# ⚡ GridPulse - Smart Campus Energy Monitoring

GridPulse is a scalable, end-to-end IoT data pipeline and real-time dashboard built for monitoring power grid telemetry across a university campus. 

It evolves through multiple architectural phases, from simple batch CSV processing to a robust **Real-Time Streaming Analytics** platform powered by Apache Kafka, Apache Spark, PostgreSQL, and Streamlit.

---

## 📚 Documentation
- 📑 **[System Architecture & Design Document (docs/design.md)](docs/design.md)**: Deep dive into the 3-tier architecture, data models (3NF ERD), Kafka schemas, physics formulas, and ML anomaly detection engine.
- 🗺️ **[Phases & Roadmap (docs/phases.md)](docs/phases.md)**: Breakdown of all 6 architectural phases, current milestone status, and execution guides.

---

## 🏗️ Architecture

### **Phase 4: Event Streaming & Real-Time Analytics**
The current architecture processes real-time telemetry from thousands of simulated smart sub-meters.

1. **IoT Telemetry Simulator (`/simulator`)**: A Python-based producer that generates realistic, real-time electrical telemetry (Voltage, Current, Power Factor, active Load) and pushes JSON payloads to Kafka.
2. **Message Broker (`/kafka`)**: A containerized **Apache Kafka** cluster (running via Docker Compose alongside Zookeeper and Kafka UI) to decouple data ingestion from processing.
3. **Stream Processor (`/stream_processor`)**: An **Apache Spark Structured Streaming** job running via PySpark. It:
   - Ingests raw JSON streams from Kafka (`gridpulse.telemetry.raw`).
   - Applies a **5-minute sliding window (1-minute slide)** with a 2-minute watermark.
   - Computes aggregated analytics (average kW, average voltage, etc.) grouped by `building_id`.
   - Writes the micro-batches robustly to PostgreSQL via optimized JDBC connections.
4. **Relational Data Store (`/database`)**: A cloud-hosted **PostgreSQL (Neon)** database containing normalized dimensional tables (`buildings`, `meters`) and fact tables (`energy_readings`, `building_energy_aggregates`).
5. **Real-Time UI (`/dashboard`)**: A **Streamlit** web application utilizing advanced features like `@st.fragment(run_every="3s")` to provide a highly responsive, auto-refreshing UI that visualizes the sliding window aggregates in real-time alongside historical trends without page flickers.

---

## 🚀 Setup & Execution (Phase 4 Streaming Pipeline)

### 1. Start the Kafka Cluster
Ensure Docker is running, then spin up the message broker and Kafka UI:
```powershell
cd kafka
docker-compose up -d
```
*Kafka UI is available at `http://localhost:8080`.*

### 2. Start the IoT Telemetry Producer
Run the Python simulator to start feeding real-time data into the Kafka topic:
```powershell
python simulator/kafka_producer.py
```

### 3. Run the Spark Streaming Processor
Since PySpark requires a JVM, we execute the streaming job inside a dedicated `apache/spark` Docker container to avoid local Java path issues. The script is pre-configured with the required Kafka and PostgreSQL JDBC packages.
```powershell
# Runs the Spark job in daemon mode
.\run_spark.ps1
```
*The processor will automatically pick up data from Kafka, aggregate it, and sink it to the `building_energy_aggregates` table in PostgreSQL.*

### 4. Launch the Streamlit Dashboard
Open the interactive UI to view the live streaming metrics:
```powershell
streamlit run dashboard/app.py
```
*Navigate to the **⚡ Phase 4: Real-Time Stream** tab to watch the live data roll in!*

---

## 🛠️ Optimization Details
- **Trigger Intervals**: Spark streaming trigger time is tuned to **15 seconds** to balance database connection overhead against UI freshness.
- **JDBC Pooling & Inserts**: The Spark JDBC writer is configured with `batchsize=5000` and `isolationLevel=NONE` to maximize throughput during micro-batch writes to PostgreSQL.
- **UI Fragments**: Streamlit's `@st.fragment` is leveraged to isolate the real-time polling logic. This ensures the live charts update seamlessly every 3 seconds without freezing or resetting the rest of the dashboard layout.
