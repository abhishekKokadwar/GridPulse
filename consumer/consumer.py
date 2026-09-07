import json
import os
import sys
import time
from datetime import datetime

# Prevent OpenBLAS Memory Allocation errors on Windows with multiple processes
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"

# Remove the script's directory from sys.path to prevent import collisions
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir in sys.path:
    sys.path.remove(script_dir)

# Add project root to path
PROJECT_ROOT = os.path.abspath(os.path.join(script_dir, ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from confluent_kafka import Consumer, KafkaError
from database.db import insert_readings_and_alerts, DB_AVAILABLE
from analysis.ml_anomaly_detector import MLAnomalyDetector
from analysis.analysis import load_energy_data

DEFAULT_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
DEFAULT_TOPIC = os.getenv("KAFKA_TOPIC", "gridpulse.telemetry.raw")
DEFAULT_GROUP_ID = os.getenv("KAFKA_GROUP_ID", "gridpulse-consumer-group")


def start_telemetry_consumer(
    topic=DEFAULT_TOPIC,
    bootstrap_servers=DEFAULT_BOOTSTRAP_SERVERS,
    group_id=DEFAULT_GROUP_ID,
    sink_to_postgres=True,
    max_messages=None,
):
    """
    Consumes IoT energy readings from Kafka in real-time,
    evaluates them against the ML Anomaly Detection Engine (Isolation Forest + Z-Score),
    and sinks telemetry + detected anomalies to PostgreSQL.
    """
    print(f"\n[KAFKA CONSUMER STARTING]")
    print(f"  * Topic: '{topic}'")
    print(f"  * Bootstrap Server: {bootstrap_servers}")
    print(f"  * Consumer Group: '{group_id}'")
    print(f"  * PostgreSQL Auto-Sink: {'ENABLED' if (sink_to_postgres and DB_AVAILABLE) else 'DISABLED'}")
    print("---------------------------------------------------------------")

    # 1. Initialize & Train ML Anomaly Detector on Historical Baseline
    ml_detector = MLAnomalyDetector()
    raw_csv = os.path.join(PROJECT_ROOT, "data", "raw", "energy_data.csv")
    if os.path.exists(raw_csv):
        try:
            df_hist = load_energy_data(raw_csv)
            ml_detector.train_on_historical(df_hist)
        except Exception as e:
            print(f"[ML WARNING] Could not train baseline model: {e}")

    # 2. Configure Confluent Kafka Consumer
    conf = {
        "bootstrap.servers": bootstrap_servers,
        "group.id": group_id,
        "auto.offset.reset": "earliest",
        "enable.auto.commit": True,
    }

    try:
        consumer = Consumer(conf)
        consumer.subscribe([topic])
    except Exception as e:
        print(f"[KAFKA ERROR] Failed to connect to Kafka at {bootstrap_servers}: {e}")
        return

    print("[OK] Connected to Kafka broker! Listening for streaming telemetry...\n")

    message_count = 0
    buffer = []
    last_flush_time = time.time()

    try:
        while True:
            msg = consumer.poll(timeout=1.0)
            if msg is None:
                continue
            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    continue
                else:
                    print(f"[KAFKA ERROR] {msg.error()}")
                    break

            try:
                reading = json.loads(msg.value().decode("utf-8"))
            except Exception as e:
                print(f"[JSON ERROR] Failed parsing message: {e}")
                continue

            key = msg.key().decode("utf-8") if msg.key() else "N/A"
            partition = msg.partition()
            offset = msg.offset()

            message_count += 1
            buffer.append(reading)

            # 3. Real-Time ML & Statistical Anomaly Scoring
            eval_result = ml_detector.score_single_reading(reading)

            pwr = reading.get("power_kw", 0)
            volt = reading.get("voltage_v", 0)
            pf = reading.get("power_factor", 0)
            bldg = reading.get("building_id", "N/A")

            # Clean ASCII Tag representation
            if eval_result["is_anomaly"]:
                tag = f"[ANOMALY: {eval_result['primary_reason']}]"
            else:
                tag = "[NOMINAL]"

            print(
                f"[P{partition}:O{offset:05d}] {reading.get('timestamp')} | Meter: {key:<5} | "
                f"Bldg: {bldg:<18} | {pwr:5.1f} kW | {volt:5.1f} V | PF: {pf:.3f} | {tag}"
            )

            # 4. Periodic Batch Flush to PostgreSQL
            if sink_to_postgres and DB_AVAILABLE:
                if len(buffer) >= 20 or (time.time() - last_flush_time >= 2.0 and buffer):
                    insert_readings_and_alerts(buffer)
                    buffer = []
                    last_flush_time = time.time()

            if max_messages and message_count >= max_messages:
                break

    except KeyboardInterrupt:
        print(f"\n[STOP] Consumer stopped by user. Total messages processed: {message_count}")
    finally:
        consumer.close()
        print("[KAFKA] Consumer connection closed.")


if __name__ == "__main__":
    start_telemetry_consumer()
