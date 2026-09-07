import csv
import math
import os
import random
import sys
import time
from datetime import datetime, timedelta

# Add project root to path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    from database.db import (
        init_db,
        seed_dimensions,
        insert_readings_and_alerts,
        get_db_stats,
    )
    DB_AVAILABLE = True
except Exception:
    DB_AVAILABLE = False

# Structured categorization of campus infrastructure
CAMPUS_INFRASTRUCTURE = {
    "Hostels": {
        "BH1": 3,
        "BH2": 3,
        "BH3": 3,
        "BH4": 3,
        "GH": 3,
        "IVH": 3,
        "Satpura": 3,
    },
    "Departments": {
        "Management": 1,
        "IT": 1,
        "CS": 1,
        "EEE": 1,
        "Engineering Science": 1,
        "GEN-LAB": 1,
    },
    "Lecture Theatres": {
        "LT1": 2,
        "LT2": 2,
    },
    "Facilities": {
        "Convention Center": 2,
        "SC": 2,
        "Academic Block": 2,
        "Library": 2,
        "Cafeteria": 1,
        "Powerhouse": 1,
        "OAT": 1,
    },
}

CSV_HEADERS = [
    "event_id",
    "timestamp",
    "meter_id",
    "building_id",
    "building_type",
    "power_kw",
    "voltage_v",
    "current_a",
    "power_factor",
]


def create_meters():
    """Generates a list of meter configurations mapped to campus buildings and categories."""
    meters = []
    meter_number = 1

    for category, buildings in CAMPUS_INFRASTRUCTURE.items():
        for building, number_of_meters in buildings.items():
            for _ in range(number_of_meters):
                meter = {
                    "meter_id": f"M{meter_number:03d}",
                    "building_id": building,
                    "building_type": category,
                }
                meters.append(meter)
                meter_number += 1

    return meters


def calculate_building_power(building, category, dt):
    """
    Realistic schedule-driven power simulation based on:
    - Time of day (hours 0-24)
    - Weekdays vs Weekends (Mon-Fri vs Sat-Sun)
    - Specific rules:
        * Classes 9 AM - 6 PM on weekdays for Depts and Lecture Theatres
        * Library closed on Sundays (minimal idle power)
        * Hostels peak early morning & late evenings/nights
        * Cafeteria peaks during breakfast, lunch, and dinner
    """
    hour = dt.hour + dt.minute / 60.0
    day_of_week = dt.weekday()  # 0: Monday ... 5: Saturday, 6: Sunday
    is_weekend = day_of_week in [5, 6]
    is_sunday = day_of_week == 6

    # 1. Departments (Management, IT, CS, EEE, Eng Science, GEN-LAB)
    if category == "Departments":
        if not is_weekend and (8.5 <= hour <= 18.5):
            bell_curve = math.sin((hour - 8.5) / 10.0 * math.pi)
            base_power = 22 + 18 * bell_curve + random.uniform(-2, 3)
        elif not is_weekend and (18.5 < hour <= 21.5):
            base_power = random.uniform(8, 15)
        elif is_weekend and (10 <= hour <= 16):
            base_power = random.uniform(5, 11)
        else:
            base_power = random.uniform(3.5, 7.5)

    # 2. Lecture Theatres (LT1, LT2)
    elif category == "Lecture Theatres":
        if not is_weekend and (8.5 <= hour <= 18.0):
            bell_curve = math.sin((hour - 8.5) / 9.5 * math.pi)
            base_power = 18 + 14 * bell_curve + random.uniform(-2, 3)
        elif not is_weekend and (18.0 < hour <= 21.0):
            base_power = random.uniform(6, 12)
        else:
            base_power = random.uniform(1.5, 4.0)

    # 3. Hostels (BH1-BH4, GH, IVH, Satpura)
    elif category == "Hostels":
        if not is_weekend:
            if 6.0 <= hour <= 9.0:
                base_power = random.uniform(20, 32)
            elif 9.0 < hour < 17.5:
                base_power = random.uniform(7, 13)
            elif 17.5 <= hour <= 24.0:
                base_power = random.uniform(22, 36)
            else:
                base_power = random.uniform(9, 16)
        else:
            if 9.0 <= hour <= 24.0:
                base_power = random.uniform(18, 32)
            else:
                base_power = random.uniform(10, 17)

    # 4. Facilities (Library, Cafeteria, Powerhouse, SC, OAT, Academic Block, Convention Center)
    elif category == "Facilities":
        if building == "Library":
            if is_sunday:
                base_power = random.uniform(1.5, 3.5)
            elif not is_sunday and (8.0 <= hour <= 22.0):
                bell_curve = math.sin((hour - 8.0) / 14.0 * math.pi)
                base_power = 20 + 16 * bell_curve + random.uniform(-2, 2.5)
            else:
                base_power = random.uniform(3.0, 5.5)

        elif building == "Convention Center":
            if (is_weekend and 10 <= hour <= 20) or (16 <= hour <= 21):
                base_power = random.uniform(22, 38)
            else:
                base_power = random.uniform(3.0, 7.0)

        elif building == "Cafeteria":
            if (7.0 <= hour <= 9.5) or (12.0 <= hour <= 14.5) or (19.0 <= hour <= 22.0):
                base_power = random.uniform(22, 36)
            elif 15.0 <= hour <= 18.0:
                base_power = random.uniform(10, 16)
            else:
                base_power = random.uniform(4.0, 7.5)

        elif building == "Powerhouse":
            base_power = random.uniform(38, 55)

        elif building in ["SC", "OAT"]:
            if 16.0 <= hour <= 22.5:
                base_power = random.uniform(14, 28)
            else:
                base_power = random.uniform(2.5, 6.0)

        elif building == "Academic Block":
            if not is_weekend and (8.5 <= hour <= 18.0):
                base_power = random.uniform(22, 38)
            else:
                base_power = random.uniform(4.0, 9.0)

        else:
            base_power = random.uniform(6.0, 15.0)

    else:
        base_power = random.uniform(5.0, 15.0)

    return max(1.0, base_power)


def generate_reading(meter, event_id, dt=None):
    """Generates a single simulated meter reading."""
    if dt is None:
        dt = datetime.now()

    building = meter["building_id"]
    category = meter["building_type"]

    power_kw = calculate_building_power(building, category, dt)

    # Voltage simulation: nominal 230V
    base_voltage = 233.0 - (power_kw / 50.0) * 4.0
    voltage_v = base_voltage + random.gauss(0, 2.5)

    # 1.5% chance of realistic grid anomaly injection (sag or surge)
    rand_anom = random.random()
    if rand_anom < 0.01:
        voltage_v = random.uniform(205.0, 217.0)
    elif rand_anom < 0.02:
        voltage_v = random.uniform(242.0, 249.0)

    # Power Factor
    if category in ["Facilities", "Departments"]:
        base_pf = random.uniform(0.86, 0.95)
    else:
        base_pf = random.uniform(0.90, 0.98)

    if random.random() < 0.01:
        base_pf = random.uniform(0.78, 0.84)

    current_a = (power_kw * 1000.0) / voltage_v

    return {
        "event_id": f"E{event_id:06d}",
        "timestamp": dt.isoformat(timespec="seconds"),
        "meter_id": meter["meter_id"],
        "building_id": meter["building_id"],
        "building_type": meter["building_type"],
        "power_kw": round(power_kw, 2),
        "voltage_v": round(voltage_v, 2),
        "current_a": round(current_a, 2),
        "power_factor": round(base_pf, 3),
    }


def save_readings_to_csv(readings, filepath="data/raw/energy_data.csv", overwrite=False):
    """Appends or writes readings to CSV file."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    mode = "w" if overwrite else "a"
    file_exists = os.path.exists(filepath) and os.path.getsize(filepath) > 0 and not overwrite

    with open(filepath, mode=mode, newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        if not file_exists:
            writer.writeheader()
        writer.writerows(readings)


def generate_historical_batch(
    days=7,
    interval_minutes=30,
    output_path="data/raw/energy_data.csv",
    save_to_db=True,
    overwrite_csv=True,
):
    """
    Generates realistic multi-day historical time-series data:
    - Sinks to normalized PostgreSQL tables (`energy_readings` and `alerts`)
    - Sinks to raw CSV for backward compatibility
    """
    meters = create_meters()
    readings = []
    event_id = 1

    total_intervals = int((days * 24 * 60) / interval_minutes)
    now = datetime.now()
    start_time = now - timedelta(days=days)

    print(f"[SIMULATOR] Generating {days}-day dataset ({interval_minutes}m interval across {len(meters)} meters)...")

    for i in range(total_intervals):
        current_dt = start_time + timedelta(minutes=i * interval_minutes)
        for meter in meters:
            reading = generate_reading(meter, event_id=event_id, dt=current_dt)
            readings.append(reading)
            event_id += 1

    # Save to CSV
    save_readings_to_csv(readings, output_path, overwrite=overwrite_csv)
    print(f"[CSV] Saved {len(readings)} records -> {output_path}")

    # Save to PostgreSQL
    if save_to_db and DB_AVAILABLE:
        try:
            print("[POSTGRES] Seeding dimension tables (buildings, meters)...")
            seed_dimensions(CAMPUS_INFRASTRUCTURE)

            print("[POSTGRES] Ingesting historical batch into energy_readings & alerts...")
            chunk_size = 4000
            total_readings = 0
            total_alerts = 0
            for k in range(0, len(readings), chunk_size):
                chunk = readings[k : k + chunk_size]
                n_readings, n_alerts = insert_readings_and_alerts(chunk)
                total_readings += n_readings
                total_alerts += n_alerts

            print(f"[POSTGRES] Ingested {total_readings} rows into `energy_readings` and {total_alerts} alerts into `alerts` table!")
            stats = get_db_stats()
            print(f"[POSTGRES STATS] Current DB State: {stats}")
        except Exception as e:
            print(f"[POSTGRES ERROR] Failed inserting to DB: {e}")

    return readings


def run_live_simulation(interval_sec=3, save_to_db=True, output_path="data/raw/energy_data.csv"):
    """Continuously generates live readings and streams them into PostgreSQL & CSV."""
    meters = create_meters()
    print(f"[START] Live Simulator active ({len(meters)} meters, interval: {interval_sec}s)")
    if save_to_db and DB_AVAILABLE:
        seed_dimensions(CAMPUS_INFRASTRUCTURE)
        print("[SINK] Streaming to normalized Neon PostgreSQL schema and CSV.")
    print("Press Ctrl+C to stop.\n")

    event_id = int(time.time())
    iteration = 0
    try:
        while True:
            batch = []
            now = datetime.now()
            for meter in meters:
                batch.append(generate_reading(meter, event_id=event_id, dt=now))
                event_id += 1

            # Save to CSV
            save_readings_to_csv(batch, output_path, overwrite=False)

            # Insert into PostgreSQL
            if save_to_db and DB_AVAILABLE:
                try:
                    insert_readings_and_alerts(batch)
                except Exception as e:
                    print(f"[DB ERROR] {e}")

            iteration += 1
            print(f"[{now.strftime('%Y-%m-%d %H:%M:%S')}] Ingested {len(batch)} readings to DB & CSV (Batch #{iteration})")
            time.sleep(interval_sec)
    except KeyboardInterrupt:
        print("\n[STOP] Simulation stopped by user.")


if __name__ == "__main__":
    output_csv = os.path.join("data", "raw", "energy_data.csv")
    generate_historical_batch(days=7, interval_minutes=30, output_path=output_csv, save_to_db=True)