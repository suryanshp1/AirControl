"""
AirControl — Training Data Collection Tool
===========================================

Run this script to record static hand gestures for training the neural network.
Press the corresponding number key to record samples for a specific gesture.
It records 63-dimensional normalized hand landmarks.
"""

import cv2
import mediapipe as mp
import time
import os
import csv
import sys
import numpy as np

# Add parent directory to path to import engine modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from engine.gesture import Gesture, _normalize_landmarks, LandmarkPoint

mp_hands = mp.solutions.hands
mp_draw = mp.solutions.drawing_utils

DATA_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'model', 'training_data.csv'))

# Target Gestures mappings (0-8)
GESTURE_MAP = {
    '0': Gesture.NONE,
    '1': Gesture.OPEN_PALM,
    '2': Gesture.FIST,
    '3': Gesture.POINTING_UP,
    '4': Gesture.THUMB_UP,
    '5': Gesture.THUMB_DOWN,
    '6': Gesture.VICTORY,
    # Exclude dynamic gestures (swipes, pinches) from static classifier
}

def lm_to_points(hand_lm) -> list:
    return [
        LandmarkPoint(x=lm.x, y=lm.y, z=lm.z, visibility=1.0)
        for lm in hand_lm.landmark
    ]

def flat_features(norm_lm) -> list:
    """Flatten 21 normalized landmarks into a 63-element list [x0,y0,z0, x1,y1,z1...]"""
    features = []
    for lm in norm_lm:
        features.extend([lm.x, lm.y, lm.z])
    return features

def append_to_csv(features, label_name):
    file_exists = os.path.isfile(DATA_FILE)
    with open(DATA_FILE, 'a', newline='') as f:
        writer = csv.writer(f)
        if not file_exists:
            # Write header
            header = ['label'] + [f'f_{i}' for i in range(63)]
            writer.writerow(header)
        row = [label_name] + features
        writer.writerow(row)

def main():
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("ERROR: Cannot open camera 0")
        return

    recording_state = False
    current_label = None
    frames_recorded = 0
    TARGET_FRAMES = 500

    print("--- AirControl Data Collection ---")
    print(f"Saving to: {DATA_FILE}")
    print("Controls:")
    for key, gest in GESTURE_MAP.items():
        print(f"  [{key}] - Record {gest.name}")
    print("  [r] - Stop current recording")
    print("  [q] - Quit")

    header_written = False

    with mp_hands.Hands(
        static_image_mode=False,
        max_num_hands=1,
        min_detection_confidence=0.6,
        min_tracking_confidence=0.5,
    ) as hands:
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            frame = cv2.flip(frame, 1)
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            result = hands.process(rgb)

            hand_detected = False
            features = None

            if result.multi_hand_landmarks:
                hand_detected = True
                for hand_lm in result.multi_hand_landmarks:
                    mp_draw.draw_landmarks(frame, hand_lm, mp_hands.HAND_CONNECTIONS)
                    lm_pts = lm_to_points(hand_lm)
                    norm_lm = _normalize_landmarks(lm_pts)
                    features = flat_features(norm_lm)

            # Handle recording
            if recording_state and hand_detected and features is not None:
                append_to_csv(features, current_label.name)
                frames_recorded += 1
                
                # Synthetic Augmentation: Mirroring X-axis
                # To make model robust to left/right hands
                mirrored_features = []
                for i in range(0, len(features), 3):
                    mirrored_features.extend([-features[i], features[i+1], features[i+2]])
                append_to_csv(mirrored_features, current_label.name)

                if frames_recorded >= TARGET_FRAMES / 2: # divide by 2 because 1 true + 1 mirrored = 2 recorded per frame
                    recording_state = False
                    print(f"\nDone recording {TARGET_FRAMES} samples for {current_label.name}")

            # Draw HUD
            overlay = frame.copy()
            cv2.rectangle(overlay, (0, 0), (640, 100), (0, 0, 0), -1)
            cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, frame)

            if recording_state:
                cv2.putText(frame, f"RECORDING: {current_label.name}", (10, 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
                progress = int((frames_recorded / (TARGET_FRAMES / 2)) * 100)
                cv2.putText(frame, f"Progress: {progress}% ({frames_recorded * 2}/{TARGET_FRAMES})", (10, 70),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
            else:
                cv2.putText(frame, "IDLE - Press key 0-6 to record", (10, 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)

            cv2.imshow("AirControl Collector", frame)
            
            key = cv2.waitKey(1) & 0xFF
            char_key = chr(key) if key < 256 else ''

            if key == ord('q'):
                break
            elif key == ord('r'):
                recording_state = False
                print("Recording stopped manually.")
            elif char_key in GESTURE_MAP:
                if not recording_state:
                    current_label = GESTURE_MAP[char_key]
                    recording_state = True
                    frames_recorded = 0
                    print(f"Started recording {current_label.name}...")

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
