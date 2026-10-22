"""
app.py
──────
Flask server that:
  1. Subscribes to MQTT (guitar/sensors)
  2. Runs ML prediction on each reading
  3. Serves a REST API + WebSocket for the dashboard

Endpoints:
  GET  /api/latest     → latest sensor reading + prediction
  GET  /api/history    → last 100 readings
  GET  /api/stats      → session stats (duration, good%, bad%)

Usage:
  python app.py
"""

import json
import threading
import time
from collections import deque
from datetime import datetime

import joblib
import numpy as np
import paho.mqtt.client as mqtt
from flask import Flask, jsonify
from flask_cors import CORS

# ─── Load Model ───────────────────────────────────────────────
try:
    bundle   = joblib.load("model.pkl")
    model    = bundle["model"]
    encoder  = bundle["encoder"]
    features = bundle["features"]
    print("Model loaded successfully.")
    MODEL_READY = True
except FileNotFoundError:
    print("WARNING: model.pkl not found. Run train_model.py first.")
    print("Running in DATA-ONLY mode (no predictions).")
    MODEL_READY = False

# ─── State ────────────────────────────────────────────────────
history     = deque(maxlen=100)
latest      = {}
session_start = time.time()

BROKER = "broker.hivemq.com"
PORT   = 1883
TOPIC  = "guitar/sensors"

# ─── Rule-Based Thresholds ───────────────────────────────────────
# For each sensor: value BELOW threshold → parameter is "good".
# Decision rule: if 2 or more parameters fail → overall = "bad".
VIB_THRESHOLD  = 150    # Piezo bridge  — vibration ADC count
IMP_THRESHOLD  = 1000   # Piezo pickguard — impact ADC count
TILT_THRESHOLD = 40     # MPU6050 — change in degrees from boot baseline

# ─── Feature Engineering (must match train_model.py) ──────────
recent_vib = deque(maxlen=5)
recent_imp = deque(maxlen=5)

def engineer(data):
    recent_vib.append(data.get("vibration", 0))
    recent_imp.append(data.get("impact", 0))
    row = [
        data.get("vibration", 0),
        data.get("impact", 0),
        data.get("tilt", 0),
        data.get("accel_x", 0),
        data.get("accel_y", 0),
        data.get("accel_z", 0),
        data.get("gyro_x", 0),
        np.mean(recent_vib),
        np.std(recent_vib) if len(recent_vib) > 1 else 0,
        np.mean(recent_imp),
        abs(data.get("tilt", 0)),
    ]
    return np.array(row).reshape(1, -1)

# ─── MQTT Callbacks ───────────────────────────────────────────
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("MQTT connected. Listening for guitar data...")
        client.subscribe(TOPIC)
    else:
        print(f"MQTT connection failed: {rc}")

def on_message(client, userdata, msg):
    global latest
    try:
        data = json.loads(msg.payload.decode())
        data["server_ts"] = datetime.now().isoformat()

        # ── Rule-based prediction ─────────────────────────────────────
        vibration = data.get("vibration", 0)
        impact    = data.get("impact",    0)
        tilt      = abs(data.get("tilt",  0))  # tilt is already delta from baseline

        vib_ok  = vibration < VIB_THRESHOLD
        imp_ok  = impact    < IMP_THRESHOLD
        tilt_ok = tilt      < TILT_THRESHOLD

        fail_count = sum([not vib_ok, not imp_ok, not tilt_ok])
        prediction = "good" if fail_count < 2 else "bad"

        data["prediction"]  = prediction
        data["confidence"]  = 100  # rule-based = deterministic
        data["vib_ok"]      = vib_ok
        data["imp_ok"]      = imp_ok
        data["tilt_ok"]     = tilt_ok
        data["fail_count"]  = fail_count
        # ─────────────────────────────────────────────────────────────

        latest = data
        history.append(data)

    except Exception as e:
        print(f"Message error: {e}")

# ─── MQTT Thread ──────────────────────────────────────────────
def start_mqtt():
    mq = mqtt.Client()
    mq.on_connect = on_connect
    mq.on_message = on_message
    mq.connect(BROKER, PORT, 60)
    mq.loop_forever()

mqtt_thread = threading.Thread(target=start_mqtt, daemon=True)
mqtt_thread.start()

# ─── Flask App ────────────────────────────────────────────────
app = Flask(__name__)
CORS(app)

@app.route("/api/latest")
def get_latest():
    return jsonify(latest)

@app.route("/api/history")
def get_history():
    return jsonify(list(history))

@app.route("/api/stats")
def get_stats():
    if not history:
        return jsonify({"message": "No data yet"})
    elapsed = round(time.time() - session_start)
    preds   = [r.get("prediction") for r in history if r.get("prediction") != "unknown"]
    good    = preds.count("good")
    bad     = preds.count("bad")
    total   = good + bad
    return jsonify({
        "session_duration_s": elapsed,
        "total_readings":     len(history),
        "good_count":         good,
        "bad_count":          bad,
        "good_pct":           round(good / total * 100, 1) if total else 0,
        "bad_pct":            round(bad  / total * 100, 1) if total else 0,
    })

if __name__ == "__main__":
    print("Starting Guitar Analytics API on http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, debug=False)
