"""
data_collector.py
─────────────────
Subscribes to MQTT, collects labeled guitar sensor data,
and saves it as a CSV for ML training.

Usage:
  python data_collector.py --label good  --duration 60  --out data.csv
  python data_collector.py --label bad   --duration 60  --out data.csv
"""

import argparse
import csv
import json
import os
import time
import paho.mqtt.client as mqtt

BROKER = "broker.hivemq.com"
PORT   = 1883
TOPIC  = "guitar/sensors"

rows   = []
label  = ""
start  = None
duration = 60  # seconds


def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print(f"Connected to MQTT broker. Collecting '{label}' data for {duration}s...")
        client.subscribe(TOPIC)
    else:
        print(f"Connection failed with code {rc}")


def on_message(client, userdata, msg):
    global rows, start
    elapsed = time.time() - start
    if elapsed > duration:
        client.disconnect()
        return
    try:
        data = json.loads(msg.payload.decode())
        data["label"] = label
        data["elapsed"] = round(elapsed, 2)
        rows.append(data)
        print(f"[{elapsed:.1f}s] vib={data.get('vibration')} impact={data.get('impact')} tilt={data.get('tilt', 0):.1f}°")
    except Exception as e:
        print(f"Parse error: {e}")


def save_csv(filepath):
    if not rows:
        print("No data collected.")
        return
    file_exists = os.path.isfile(filepath)
    keys = ["ts", "elapsed", "vibration", "impact", "tilt", "accel_x", "accel_y", "accel_z", "gyro_x", "label"]
    with open(filepath, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        if not file_exists:
            writer.writeheader()
        writer.writerows(rows)
    print(f"\nSaved {len(rows)} rows to '{filepath}'")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--label",    required=True, choices=["good", "bad"], help="Technique label")
    parser.add_argument("--duration", type=int, default=60,   help="Collection duration in seconds")
    parser.add_argument("--out",      default="guitar_data.csv", help="Output CSV file")
    args = parser.parse_args()

    label    = args.label
    duration = args.duration
    start    = time.time()

    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message

    client.connect(BROKER, PORT, 60)
    client.loop_forever()

    save_csv(args.out)
