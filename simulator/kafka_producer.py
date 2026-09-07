import json
import os
import sys
import time
from datetime import datetime

# Prevent OpenBLAS Memory Allocation errors on Windows with multiple processes
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"

# Remove the script's directory from sys.path to prevent import collisions
# when running `python simulator/kafka_producer.py`
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir in sys.path:
    sys.path.remove(script_dir)

# Add project root to path
PROJECT_ROOT = os.path.abspath(os.path.join(script_dir, ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from confluent_kafka import Producer
from simulator.simulator import create_meters, generate_reading, CAMPUS_INFRASTRUCTURE

DEFAULT_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
DEFAULT_TOPIC = os.getenv("KAFKA_TOPIC", "gridpulse.telemetry.raw")


def delivery_report(err, msg):
    """Called once for each message produced to indicate delivery result."""
    if err is not None:
        print(f"[KAFKA DELIVERY FAILED] {msg.key()}: {err}")


def get_kafka_producer(bootstrap_servers=DEFAULT_BOOTSTRAP_SERVERS):
    """Creates a high-throughput confluent-kafka Producer."""
    conf = {
        "bootstrap.servers": bootstrap_servers,
        "client.id": "gridpulse-simulator-producer",
        "acks": "all",
        "retries": 3,
        "linger.ms": 10,
    }
    return Producer(conf)


def stream_to_kafka(
    interval_sec=2,
    topic=DEFAULT_TOPIC,
    bootstrap_servers=DEFAULT_BOOTSTRAP_SERVERS,
    max_batches=None,
):
    """
    Streams simulated IoT energy readings to Apache Kafka in real-time.
    Every message is keyed by `meter_id` to ensure per-meter partition ordering.
    """
    meters = create_meters()
    try:
        producer = get_kafka_producer(bootstrap_servers)
    except Exception as e:
        print(f"[KAFKA ERROR] Failed to connect to Kafka at {bootstrap_servers}: {e}")
        return

    print(f"\n[KAFKA PRODUCER ACTIVE] Streaming {len(meters)} meters -> Topic: '{topic}' @ {bootstrap_servers}")
    print(f"Interval: {interval_sec}s | Press Ctrl+C to stop.\n")

    event_counter = int(time.time())
    batch_num = 1

    try:
        while True:
            now_dt = datetime.now()
            batch_count = 0

            for meter in meters:
                reading = generate_reading(meter, event_id=event_counter, dt=now_dt)
                event_counter += 1

                payload = json.dumps(reading).encode("utf-8")
                key_bytes = str(reading["meter_id"]).encode("utf-8")

                producer.produce(
                    topic=topic,
                    key=key_bytes,
                    value=payload,
                    on_delivery=delivery_report,
                )
                batch_count += 1

            # Trigger delivery callbacks and flush
            producer.poll(0)
            producer.flush()

            print(
                f"[{now_dt.strftime('%H:%M:%S')}] Published Batch #{batch_num} "
                f"({batch_count} messages) -> Kafka Topic: '{topic}'"
            )

            batch_num += 1
            if max_batches and batch_num > max_batches:
                break

            time.sleep(interval_sec)

    except KeyboardInterrupt:
        print("\n[STOP] Kafka Producer stopped by user.")
    finally:
        producer.flush()
        print("[KAFKA] Producer flushed and closed.")


if __name__ == "__main__":
    stream_to_kafka(interval_sec=2)
