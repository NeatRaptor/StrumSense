# audio_to_csv.py
"""
Converts audio recordings into a sensor-proxy CSV for ML training.

Each 100ms audio chunk is mapped to physically meaningful sensor proxies:
  vibration        -> RMS energy           (string resonance amplitude)
  impact           -> Peak amplitude        (strumming force)
  tilt             -> Spectral centroid     (tone brightness; good playing = cleaner tone)
  accel_x          -> Onset strength        (strumming attack sharpness)
  accel_y          -> Zero crossing rate    (buzz/muting indicator)
  accel_z          -> Spectral rolloff      (fullness/richness of tone)
  gyro_x           -> Rolling tempo variance(rhythm steadiness)

Usage:
  python audio_to_csv.py --audio good1.wav --label good --out guitar_data.csv
  python audio_to_csv.py --audio bad1.wav  --label bad  --out guitar_data.csv
"""

import argparse
import csv
import os

import librosa
import numpy as np


def audio_to_csv(audio_file, label, output_csv):
    print(f"Loading {audio_file}...")
    y, sr = librosa.load(audio_file, sr=22050)

    # 100ms chunks — matches ESP32 10 Hz reading rate
    chunk_size = int(sr * 0.1)
    chunks = [y[i:i + chunk_size] for i in range(0, len(y) - chunk_size, chunk_size)]

    print(f"Processing {len(chunks)} chunks as '{label}'...")

    # Pre-compute onset envelope for the full signal (needed for onset strength per chunk)
    onset_env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=512)
    # Map each chunk index to an onset envelope index
    hop = 512
    frames_per_chunk = chunk_size // hop

    rows = []
    for i, chunk in enumerate(chunks):
        if len(chunk) < 2:
            continue

        # ── vibration: RMS energy scaled to ESP32 12-bit ADC range (0–4095)
        rms = float(np.sqrt(np.mean(chunk ** 2)))
        vibration = int(np.clip(rms * 4095, 0, 4095))

        # ── impact: peak amplitude scaled to 0–4095
        impact = int(np.clip(np.abs(chunk).max() * 4095, 0, 4095))

        # ── tilt proxy: spectral centroid (Hz), normalized to ~0–90 range
        #    Lower centroid (muddier tone) mimics a bad neck-down tilt
        centroid = librosa.feature.spectral_centroid(y=chunk, sr=sr)
        tilt = float(np.clip(np.mean(centroid) / 200.0, 0, 90))

        # ── accel_x proxy: mean onset strength in this chunk's window
        #    Strong, sharp attacks → higher strumming force
        start_frame = i * frames_per_chunk
        end_frame   = start_frame + frames_per_chunk
        onset_slice = onset_env[start_frame:end_frame]
        accel_x = float(np.mean(onset_slice)) if len(onset_slice) > 0 else 0.0
        accel_x = float(np.clip(accel_x / 10.0, 0.0, 2.0))  # normalise to ≈ g units

        # ── accel_y proxy: zero crossing rate (normalised)
        #    High ZCR = string buzz, muted notes, bad technique
        zcr = librosa.feature.zero_crossing_rate(chunk)
        accel_y = float(np.clip(np.mean(zcr) * 10.0, 0.0, 2.0))

        # ── accel_z proxy: spectral rolloff (normalised)
        #    Good playing → richer harmonic content → higher rolloff
        rolloff = librosa.feature.spectral_rolloff(y=chunk, sr=sr, roll_percent=0.85)
        accel_z = float(np.clip(np.mean(rolloff) / 5000.0, 0.0, 2.0))

        # ── gyro_x proxy: local amplitude variance (rhythm steadiness)
        #    Unsteady strumming → higher variance, like a shaky wrist
        gyro_x = float(np.clip(np.std(np.abs(chunk)) * 50.0, 0.0, 10.0))

        rows.append([vibration, impact, tilt,
                     accel_x, accel_y, accel_z,
                     gyro_x, label])

    # ── Write CSV (append mode so you can run for multiple files)
    file_exists = os.path.isfile(output_csv)
    with open(output_csv, "a", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["vibration", "impact", "tilt",
                             "accel_x", "accel_y", "accel_z",
                             "gyro_x", "label"])
        writer.writerows(rows)

    print(f"Saved {len(rows)} rows to {output_csv}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio", required=True, help="Path to audio/video file (.wav, .mp4, etc.)")
    parser.add_argument("--label", required=True, choices=["good", "bad"])
    parser.add_argument("--out",   default="guitar_data.csv")
    args = parser.parse_args()\

    audio_to_csv(args.audio, args.label, args.out)