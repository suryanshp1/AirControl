"""
AirControl — Live Gesture Debug Tool v3.0
=========================================
Run this directly to see live curl angles and gesture classification in terminal.
Updated for v3.0: shows THREE_FINGERS, PEACE_SIGN, OK_SIGN hold progress,
and EMA-smoothed wrist velocity.

Usage:
    cd backend
    python debug_gestures.py

Press Q to quit.
"""

import cv2
import time
import math
import mediapipe as mp
from engine.gesture import (
    LandmarkPoint, _normalize_landmarks,
    _finger_curl, _thumb_curl, _pinch_dist,
    classify_static, EXTENDED_THRESH, CURLED_THRESH,
    TIGHT_CURLED_THRESH, LOOSE_CURLED_THRESH,
    OK_PINCH_THRESH, OK_HOLD_SECONDS,
    OKSignTracker, DynamicTracker
)

mp_hands = mp.solutions.hands
mp_draw  = mp.solutions.drawing_utils

# EMA state for wrist velocity display
_ema_x: float = None
_EMA_ALPHA = 0.4
_wrist_prev_time: float = None
_wrist_prev_x: float = None


def lm_to_points(hand_lm) -> list:
    return [
        LandmarkPoint(x=lm.x, y=lm.y, z=lm.z, visibility=1.0)
        for lm in hand_lm.landmark
    ]


def draw_debug(frame, norm_lm, raw_lm, ok_tracker: OKSignTracker, dyn_tracker: DynamicTracker):
    global _ema_x, _wrist_prev_time, _wrist_prev_x

    idx_curl   = _finger_curl(norm_lm, 8,  7,  6,  5)
    mid_curl   = _finger_curl(norm_lm, 12, 11, 10, 9)
    ring_curl  = _finger_curl(norm_lm, 16, 15, 14, 13)
    pinky_curl = _finger_curl(norm_lm, 20, 19, 18, 17)
    thumb_curl = _thumb_curl(norm_lm)
    thumb_y    = norm_lm[4].y
    pinch      = _pinch_dist(norm_lm)

    gesture, conf = classify_static(norm_lm)

    # OK hold check
    ok_gesture, ok_conf = ok_tracker.update(norm_lm)
    ok_progress = ok_tracker.hold_progress
    if ok_gesture.value != "none":
        gesture_label = f"OK_SIGN ({ok_conf:.2f})"
    else:
        gesture_label = f"{gesture.value}  conf={conf:.2f}"

    # EMA wrist velocity
    now = time.time()
    wrist_x = raw_lm[0].x   # raw normalized (not palm-normalized) for velocity
    if _ema_x is None:
        _ema_x = wrist_x
    _ema_x = _EMA_ALPHA * wrist_x + (1 - _EMA_ALPHA) * _ema_x
    if _wrist_prev_time and now - _wrist_prev_time > 0.001:
        wrist_vel = (_ema_x - _wrist_prev_x) / (now - _wrist_prev_time)
    else:
        wrist_vel = 0.0
    _wrist_prev_time = now
    _wrist_prev_x    = _ema_x

    def state(angle):
        if angle >= EXTENDED_THRESH:  return "EXT"
        elif angle <= CURLED_THRESH:  return "CRL"
        else:                         return "PAR"

    def thumb_dir_label():
        if thumb_y < -0.30: return "UP"
        if thumb_y > 0.20:  return "DOWN"
        return "MID"

    lines = [
        f"Gesture: {gesture_label}",
        f"Thresh: ext>={EXTENDED_THRESH:.0f} curl<={CURLED_THRESH:.0f} tight<={TIGHT_CURLED_THRESH:.0f} loose<{LOOSE_CURLED_THRESH:.0f}",
        f"Index:  {idx_curl:6.1f}  {state(idx_curl)}",
        f"Middle: {mid_curl:6.1f}  {state(mid_curl)}",
        f"Ring:   {ring_curl:6.1f}  {state(ring_curl)}",
        f"Pinky:  {pinky_curl:6.1f}  {state(pinky_curl)}",
        f"Thumb:  {thumb_curl:6.1f}  {'EXT' if thumb_curl>=EXTENDED_THRESH else 'CRL'}  Y={thumb_y:+.2f}  {thumb_dir_label()}",
        f"Pinch dist: {pinch:.3f}  (OK thresh < {OK_PINCH_THRESH})",
        f"OK Hold: {'█' * int(ok_progress * 10):<10} {ok_progress*100:.0f}%  ({OK_HOLD_SECONDS}s needed)",
        f"Wrist vel (EMA): {wrist_vel:+.3f}  (swipe thresh ±0.22)",
    ]

    # Semi-transparent overlay
    overlay = frame.copy()
    panel_h = len(lines) * 22 + 16
    cv2.rectangle(overlay, (8, 8), (385, 8 + panel_h), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.60, frame, 0.40, 0, frame)

    for i, line in enumerate(lines):
        if i == 0:
            color = (0, 255, 100)   # gesture name — green
        elif i == 8:
            # OK hold bar — color based on progress
            r = int(255 * (1 - ok_progress))
            g = int(255 * ok_progress)
            color = (0, g, r)
        elif i == 9:
            # velocity — red if near threshold
            color = (0, 180, 255) if abs(wrist_vel) > 0.15 else (180, 180, 180)
        else:
            color = (200, 200, 200)

        cv2.putText(frame, line, (14, 26 + i * 22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.52, color, 1, cv2.LINE_AA)


def main():
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("ERROR: Cannot open camera 0")
        return

    ok_tracker  = OKSignTracker()
    dyn_tracker = DynamicTracker()

    with mp_hands.Hands(
        static_image_mode=False,
        max_num_hands=1,
        min_detection_confidence=0.6,
        min_tracking_confidence=0.5,
    ) as hands:
        print("AirControl Debug v3.0 — press Q to quit")
        print("Gestures: OpenPalm | Fist | PointingUp | PeaceSign | ThumbUp | ThumbDown | ThreeFingers | OKSign (hold) | SwipeL/R")
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            frame  = cv2.flip(frame, 1)
            rgb    = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            result = hands.process(rgb)

            if result.multi_hand_landmarks:
                for hand_lm in result.multi_hand_landmarks:
                    mp_draw.draw_landmarks(frame, hand_lm, mp_hands.HAND_CONNECTIONS)
                    raw_pts  = lm_to_points(hand_lm)
                    norm_pts = _normalize_landmarks(raw_pts)
                    draw_debug(frame, norm_pts, raw_pts, ok_tracker, dyn_tracker)
            else:
                ok_tracker.reset()
                cv2.putText(frame, "No hand detected", (14, 40),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (80, 80, 255), 2)

            cv2.imshow("AirControl Gesture Debug v3.0", frame)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
