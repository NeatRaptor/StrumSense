"""
train_model.py
──────────────
Trains a Random Forest classifier on guitar sensor data.
Outputs: model.pkl  (saved model for Flask API)

Usage:
  python train_model.py --data guitar_data.csv
"""

import argparse
import sys
import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder


sys.stdout.reconfigure(encoding="utf-8", errors="replace")

FEATURES = ["vibration", "impact", "tilt", "accel_x", "accel_y", "accel_z", "gyro_x"]


def load_data(filepath):
    df = pd.read_csv(filepath)
    print(f"Loaded {len(df)} rows | Labels: {df['label'].value_counts().to_dict()}")
    df = df.dropna(subset=FEATURES + ["label"])
    return df


def engineer_features(df):
    """Add rolling stats to capture temporal patterns."""
    df = df.copy()
    df["vib_rolling_mean"] = df["vibration"].rolling(5, min_periods=1).mean()
    df["vib_rolling_std"]  = df["vibration"].rolling(5, min_periods=1).std().fillna(0)
    df["imp_rolling_mean"] = df["impact"].rolling(5, min_periods=1).mean()
    df["tilt_abs"]         = df["tilt"].abs()
    return df


def train(filepath):
    df = load_data(filepath)
    df = engineer_features(df)

    ext_features = FEATURES + ["vib_rolling_mean", "vib_rolling_std", "imp_rolling_mean", "tilt_abs"]

    X = df[ext_features].values
    le = LabelEncoder()
    y = le.fit_transform(df["label"])  # good=1, bad=0

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)

    print(f"\nTraining on {len(X_train)} samples, testing on {len(X_test)} samples...")

    model = RandomForestClassifier(n_estimators=100, max_depth=8, random_state=42)
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)
    print("\n-- Classification Report --")
    print(classification_report(y_test, y_pred, target_names=le.classes_))
    print("-- Confusion Matrix --")
    print(confusion_matrix(y_test, y_pred))

    # Feature importance
    print("\n-- Feature Importance --")
    for feat, imp in sorted(zip(ext_features, model.feature_importances_), key=lambda x: -x[1]):
        print(f"  {feat:<25} {imp:.3f}")

    # Save model + encoder
    joblib.dump({"model": model, "encoder": le, "features": ext_features}, "model.pkl")
    print("\nModel saved to model.pkl")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="guitar_data.csv", help="CSV file from data_collector.py")
    args = parser.parse_args()
    train(args.data)
