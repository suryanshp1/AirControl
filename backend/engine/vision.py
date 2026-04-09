# ── AirControl — Vision Engine (Enterprise)

import cv2
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision as mp_vision
import threading
import asyncio
import time
import os
import ssl
import urllib.request
import logging
import numpy as np
from collections import deque
from typing import Optional, Callable

from .gesture import GestureEngine, GestureEvent, Gesture, LandmarkPoint
from .keymap import GestureKeymap
from .player_adapter import PlayerAdapter, SystemAdapter, build_adapter, get_available_adapters
from . import telemetry

log = logging.getLogger("aircontrol.vision")


# ---------------------------------------------------------------------------
# Landmark skeleton drawing
# ---------------------------------------------------------------------------

_HAND_CONNECTIONS = [
    (0,1),(1,2),(2,3),(3,4),       # Thumb
    (0,5),(5,6),(6,7),(7,8),       # Index
    (5,9),(9,10),(10,11),(11,12),  # Middle
    (9,13),(13,14),(14,15),(15,16),# Ring
    (0,17),(13,17),(17,18),(18,19),(19,20) # Pinky
]

_NEON_CYAN   = (0, 229, 255)   # BGR
_NEON_AMBER  = (0, 180, 255)
_WHITE       = (255, 255, 255)
_DARK        = (20, 20, 30)


def _draw_skeleton(frame: np.ndarray, lm_list: list, h: int, w: int):
    """Draw hand skeleton on frame (BGR)."""
    pts = [(int(lm.x * w), int(lm.y * h)) for lm in lm_list]

    for a, b in _HAND_CONNECTIONS:
        cv2.line(frame, pts[a], pts[b], _NEON_CYAN, 2, cv2.LINE_AA)

    for i, (x, y) in enumerate(pts):
        color = _NEON_AMBER if i in (4, 8, 12, 16, 20) else _WHITE
        cv2.circle(frame, (x, y), 4, color, -1, cv2.LINE_AA)
        cv2.circle(frame, (x, y), 5, _DARK, 1, cv2.LINE_AA)


# v3.0: Human-readable display names for each gesture
_GESTURE_DISPLAY = {
    "NONE":          "—",
    "OPEN_PALM":     "Open Palm  ✋",
    "FIST":          "Fist  ✊",
    "POINTING_UP":   "Pointing Up  ☝️",
    "PEACE_SIGN":    "Peace Sign  ✌️",
    "THUMB_UP":      "Thumb Up  👍",
    "THUMB_DOWN":    "Thumb Down  👎",
    "THREE_FINGERS": "Three Fingers  🖖",
    "OK_SIGN":       "OK Sign  👌",
    "SWIPE_LEFT":    "Swipe Left  👈",
    "SWIPE_RIGHT":   "Swipe Right  👉",
}


def _draw_hud(frame: np.ndarray, gesture: Gesture, confidence: float,
              fps: float, hand_in_frame: bool, ok_progress: float = 0.0):
    """Draw minimal HUD overlay on preview frame."""
    h, w = frame.shape[:2]

    # Semi-transparent dark bar at bottom
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, h - 50), (w, h), (10, 10, 20), -1)
    cv2.addWeighted(overlay, 0.7, frame, 0.3, 0, frame)

    # Status dot
    dot_color = _NEON_CYAN if hand_in_frame else (80, 80, 100)
    cv2.circle(frame, (16, h - 25), 7, dot_color, -1)

    # Gesture name (human-readable)
    gest_label = _GESTURE_DISPLAY.get(gesture.name, gesture.name.replace("_", " "))
    cv2.putText(frame, gest_label, (30, h - 18),
                cv2.FONT_HERSHEY_SIMPLEX, 0.52, _WHITE, 1, cv2.LINE_AA)

    # FPS + confidence
    info = f"{fps:.0f}fps  {confidence*100:.0f}% conf"
    cv2.putText(frame, info, (w - 140, h - 18),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (160, 160, 180), 1, cv2.LINE_AA)

    # OK_SIGN hold progress bar (appears top-right corner)
    if ok_progress > 0.01:
        bar_w = 120
        bar_h = 10
        bar_x = w - bar_w - 10
        bar_y = 10
        cv2.rectangle(frame, (bar_x, bar_y), (bar_x + bar_w, bar_y + bar_h),
                      (40, 40, 60), -1)
        fill = int(bar_w * ok_progress)
        fill_color = (0, int(255 * ok_progress), int(180 * (1 - ok_progress)))
        cv2.rectangle(frame, (bar_x, bar_y), (bar_x + fill, bar_y + bar_h),
                      fill_color, -1)
        cv2.putText(frame, "OK Hold", (bar_x, bar_y + bar_h + 14),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, (160, 160, 200), 1, cv2.LINE_AA)


# ---------------------------------------------------------------------------
# Vision Engine
# ---------------------------------------------------------------------------

class VisionEngine:
    MODEL_URL = (
        "https://storage.googleapis.com/mediapipe-models/"
        "hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"
    )
    MODEL_PATH = os.path.join(os.path.dirname(__file__), "..", "hand_landmarker.task")

    def __init__(self):
        self._ensure_model()
        self._build_detector()

        self.gesture_engine = GestureEngine(debounce_time=1.2)
        self.keymap         = GestureKeymap()
        self._adapter: PlayerAdapter = SystemAdapter()
        self._adapter_id: str = "system"

        # ── Runtime state ──
        self.running:      bool    = False
        self.cap:                  Optional[cv2.VideoCapture] = None
        self._thread:              Optional[threading.Thread] = None

        # ── Live state (thread-safe via GIL) ──
        self.latest_event:   Optional[GestureEvent] = None
        self.latest_action:  str = "Waiting for camera..."
        self._preview_frame: Optional[bytes] = None  # MJPEG JPEG bytes
        self._fps_history:   deque = deque(maxlen=30)
        self.fps:            float = 0.0

        # ── Async event queue for WebSocket broadcasting ──
        self._event_loop:       Optional[asyncio.AbstractEventLoop] = None
        self._event_queue:      Optional[asyncio.Queue] = None

    # ── Model Setup ──────────────────────────────────────────────────────────

    def _ensure_model(self):
        if os.path.exists(self.MODEL_PATH):
            return
        log.info("Downloading hand_landmarker.task...")
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(self.MODEL_URL, context=ctx) as r, \
             open(self.MODEL_PATH, "wb") as f:
            f.write(r.read())
        log.info("Model downloaded.")

    def _build_detector(self):
        base_opts = python.BaseOptions(model_asset_path=self.MODEL_PATH)
        opts = mp_vision.HandLandmarkerOptions(
            base_options=base_opts,
            num_hands=1,
            min_hand_detection_confidence=0.65,
            min_hand_presence_confidence=0.65,
            min_tracking_confidence=0.60,
        )
        self.detector = mp_vision.HandLandmarker.create_from_options(opts)

    # ── Public API ────────────────────────────────────────────────────────────

    def set_event_loop(self, loop: asyncio.AbstractEventLoop,
                       queue: asyncio.Queue):
        """Attach the FastAPI asyncio event loop and broadcast queue."""
        self._event_loop = loop
        self._event_queue = queue

    def start(self, camera_index: int = 0) -> bool:
        if self.running:
            return True
        cap = cv2.VideoCapture(camera_index)
        if not cap.isOpened():
            log.error("Cannot open camera %d", camera_index)
            return False
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        cap.set(cv2.CAP_PROP_FPS, 30)
        self.cap = cap
        self.running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True,
                                        name="vision-engine")
        self._thread.start()
        log.info("Vision engine started (camera %d)", camera_index)
        return True

    def stop(self):
        self.running = False
        if self._thread:
            self._thread.join(timeout=3.0)
        if self.cap:
            self.cap.release()
            self.cap = None
        self.latest_event = None
        self.latest_action = "Camera stopped"
        self._preview_frame = None
        log.info("Vision engine stopped")

    def set_adapter(self, adapter_id: str, **kwargs) -> bool:
        try:
            self._adapter = build_adapter(adapter_id, **kwargs)
            self._adapter_id = adapter_id
            log.info("Active player adapter → %s", adapter_id)
            return True
        except Exception as e:
            log.error("Failed to set adapter '%s': %s", adapter_id, e)
            return False

    def set_sensitivity(self, debounce_time: float):
        self.gesture_engine.set_debounce(debounce_time)

    @property
    def status(self) -> dict:
        evt = self.latest_event
        return {
            "is_running":        self.running,
            "adapter":           self._adapter_id,
            "fps":               round(self.fps, 1),
            "gesture":           evt.gesture.name if evt else "NONE",
            "confidence":        round(evt.confidence, 3) if evt else 0.0,
            "hand_in_frame":     evt.hand_in_frame if evt else False,
            "latest_action":     self.latest_action,
            "debounce_time":     self.gesture_engine.debounce_time,
        }

    def get_preview_frame(self) -> Optional[bytes]:
        return self._preview_frame

    # ── Camera Loop ───────────────────────────────────────────────────────────

    def _run_loop(self):
        last_time = time.perf_counter()

        while self.running:
            success, bgr = self.cap.read()
            if not success:
                time.sleep(0.01)
                continue

            now = time.perf_counter()
            frame_dt = now - last_time
            last_time = now
            self._fps_history.append(1.0 / max(frame_dt, 0.001))
            self.fps = sum(self._fps_history) / len(self._fps_history)
            telemetry.record_frame()

            # Mirror for natural selfie view
            bgr = cv2.flip(bgr, 1)
            h, w = bgr.shape[:2]

            # ── MediaPipe detect ──
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            result = self.detector.detect(mp_img)

            hand_lm_list = None
            if result.hand_landmarks:
                raw = result.hand_landmarks[0]
                hand_lm_list = [
                    LandmarkPoint(x=p.x, y=p.y, z=p.z, visibility=p.presence)
                    for p in raw
                ]
                _draw_skeleton(bgr, raw, h, w)

            # ── Gesture FSM ──
            event = self.gesture_engine.process(hand_lm_list)
            self.latest_event = event

            # ── Dispatch action if gesture confirmed ──
            if event and event.gesture != Gesture.NONE:
                telemetry.record_gesture(event.gesture.name)
                self._dispatch(event)

            # ── HUD overlay ──
            current_gesture = event.gesture if event else Gesture.NONE
            current_conf    = event.confidence if event else 0.0
            hand_in         = event.hand_in_frame if event else False
            ok_prog         = self.gesture_engine.ok_progress
            _draw_hud(bgr, current_gesture, current_conf, self.fps, hand_in, ok_prog)

            # ── MJPEG frame encode ──
            encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 65]
            preview_w = min(w, 640)
            preview_h = int(h * preview_w / w)
            small = cv2.resize(bgr, (preview_w, preview_h))
            _, buf = cv2.imencode(".jpg", small, encode_param)
            self._preview_frame = buf.tobytes()

            # ── Push event to WebSocket queue ──
            if event and self._event_loop and self._event_queue:
                payload = {
                    "type":          "gesture_event",
                    "gesture":       event.gesture.name,
                    "confidence":    round(event.confidence, 3),
                    "hand_in_frame": event.hand_in_frame,
                    "timestamp_ms":  event.timestamp_ms,
                    "fps":           round(self.fps, 1),
                    "action":        self.latest_action,
                    "adapter":       self._adapter_id,
                }
                asyncio.run_coroutine_threadsafe(
                    self._event_queue.put(payload),
                    self._event_loop
                )

    def _dispatch(self, event: GestureEvent):
        action = self.keymap.get_action(event.gesture)
        if action == "NONE":
            return
        result = self._adapter.execute(action)
        if result["success"]:
            self.latest_action = f"{action.replace('_', ' ').title()} via {self._adapter_id}"
        else:
            telemetry.record_error()
            self.latest_action = f"Failed: {result.get('error', 'unknown')}"
        log.info("Gesture=%s → Action=%s [%s] success=%s",
                 event.gesture.name, action, self._adapter_id, result["success"])
