#include <Wire.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>

// ─── WiFi & MQTT Config ────────────────────────────────────────
const char* ssid       = "xxxx";
const char* password   = "xxxx";
const char* mqtt_server = "broker.hivemq.com";  // Free public broker
const int   mqtt_port   = 1883;
const char* mqtt_topic  = "guitar/sensors";

// ─── Pin Definitions ──────────────────────────────────────────
#define PIEZO_BRIDGE    34   // Piezo disc #1 — bridge (vibration)
#define PIEZO_PICKGUARD 35   // Piezo disc #2 — pick guard (impact)
#define MPU_SDA         21
#define MPU_SCL         22

// ─── MPU6050 Registers ────────────────────────────────────────
#define MPU6050_ADDR    0x68
#define PWR_MGMT_1      0x6B
#define ACCEL_XOUT_H    0x3B
#define GYRO_XOUT_H     0x43

WiFiClient   espClient;
PubSubClient client(espClient);

// ─── Tilt Calibration ─────────────────────────────────────────
float baselineTilt = 0.0;   // Set on first power-up in setup()

// ─── MPU6050 Init ─────────────────────────────────────────────
void initMPU6050() {
  Wire.beginTransmission(MPU6050_ADDR);
  Wire.write(PWR_MGMT_1);
  Wire.write(0x00);  // Wake up MPU6050
  Wire.endTransmission(true);
  Serial.println("MPU6050 initialized.");
}

// ─── Read MPU6050 ─────────────────────────────────────────────
void readMPU6050(float &ax, float &ay, float &az, float &gx, float &gy, float &gz) {
  Wire.beginTransmission(MPU6050_ADDR);
  Wire.write(ACCEL_XOUT_H);
  Wire.endTransmission(false);
  Wire.requestFrom(MPU6050_ADDR, 14, true);

  int16_t rawAx = Wire.read() << 8 | Wire.read();
  int16_t rawAy = Wire.read() << 8 | Wire.read();
  int16_t rawAz = Wire.read() << 8 | Wire.read();
  Wire.read(); Wire.read(); // skip temp
  int16_t rawGx = Wire.read() << 8 | Wire.read();
  int16_t rawGy = Wire.read() << 8 | Wire.read();
  int16_t rawGz = Wire.read() << 8 | Wire.read();

  ax = rawAx / 16384.0;  // ±2g range
  ay = rawAy / 16384.0;
  az = rawAz / 16384.0;
  gx = rawGx / 131.0;    // ±250°/s range
  gy = rawGy / 131.0;
  gz = rawGz / 131.0;
}

// ─── WiFi Connect ─────────────────────────────────────────────
void connectWiFi() {
  Serial.print("Connecting to WiFi");
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWiFi connected. IP: " + WiFi.localIP().toString());
}

// ─── MQTT Connect ─────────────────────────────────────────────
void connectMQTT() {
  client.setServer(mqtt_server, mqtt_port);
  while (!client.connected()) {
    Serial.print("Connecting to MQTT...");
    String clientId = "GuitarSensor-" + String(random(0xffff), HEX);
    if (client.connect(clientId.c_str())) {
      Serial.println("connected.");
    } else {
      Serial.print("failed, rc=");
      Serial.println(client.state());
      delay(2000);
    }
  }
}

// ─── Setup ────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  Wire.begin(MPU_SDA, MPU_SCL);

  // Set analog resolution to 12-bit (0–4095)
  analogReadResolution(12);

  initMPU6050();

  // ── Tilt baseline calibration ──────────────────────────────
  // Average 20 readings at boot to set the zero-reference tilt
  Serial.println("Calibrating tilt baseline...");
  delay(500);  // Let MPU6050 settle
  float sumTilt = 0.0;
  const int CAL_SAMPLES = 20;
  for (int i = 0; i < CAL_SAMPLES; i++) {
    float ax, ay, az, gx, gy, gz;
    readMPU6050(ax, ay, az, gx, gy, gz);
    sumTilt += atan2(ay, az) * 180.0 / PI;
    delay(50);
  }
  baselineTilt = sumTilt / CAL_SAMPLES;
  Serial.printf("Baseline tilt set to: %.2f degrees\n", baselineTilt);
  // ─────────────────────────────────────────────────────────────

  connectWiFi();
  connectMQTT();

  Serial.println("Setup complete. Streaming sensor data...");
}

// ─── Loop ─────────────────────────────────────────────────────
void loop() {
  if (!client.connected()) connectMQTT();
  client.loop();

  // Read piezos
  int bridgeRaw    = analogRead(PIEZO_BRIDGE);
  int pickguardRaw = analogRead(PIEZO_PICKGUARD);

  // Read MPU6050
  float ax, ay, az, gx, gy, gz;
  readMPU6050(ax, ay, az, gx, gy, gz);

  // Calculate tilt as DELTA from the power-on baseline (always starts at 0°)
  float rawTilt   = atan2(ay, az) * 180.0 / PI;
  float tiltAngle = rawTilt - baselineTilt;

  // Build JSON payload
  StaticJsonDocument<256> doc;
  doc["ts"]          = millis();
  doc["vibration"]   = bridgeRaw;      // String resonance
  doc["impact"]      = pickguardRaw;   // Strumming force
  doc["tilt"]        = tiltAngle;      // Neck angle in degrees
  doc["accel_x"]     = ax;
  doc["accel_y"]     = ay;
  doc["accel_z"]     = az;
  doc["gyro_x"]      = gx;

  char payload[256];
  serializeJson(doc, payload);

  // Publish to MQTT
  client.publish(mqtt_topic, payload);

  // Serial monitor output (tilt is relative to boot position)
  Serial.printf("Vibration: %d | Impact: %d | Tilt(delta): %.1f° | AX: %.2f\n",
                bridgeRaw, pickguardRaw, tiltAngle, ax);

  delay(100);  // 10 readings per second
}
