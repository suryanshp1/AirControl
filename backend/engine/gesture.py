"""
AirControl — Enterprise Gesture Engine v3.0
============================================
Complete redesign from v2.1. Key changes:

GESTURE CHANGES:
  - Removed: PINCH_UP, PINCH_DOWN (too fragile, unreliable at 0.06 threshold)
  - Renamed: VICTORY → PEACE_SIGN (widened ring/pinky threshold so it actually fires)
  - Added:   THREE_FINGERS (index+middle+ring extended) → Seek Forward
  - Added:   OK_SIGN (pinch + 3 ext fingers held ≥1s) → Seek Back

THRESHOLD FIXES:
  - EXTENDED_THRESH:     130° → 125°  (more forgiving for real hands)
  - CURLED_THRESH:       120° → 115°  (wider partial zone prevents NONE fallback)
  - TIGHT_CURLED_THRESH: 100° → 105°  (relaxed; natural fists sit at 105–115°)
  - LOOSE_CURLED_THRESH: NEW at 125°  (for thumb gestures - no more tight fist demand)

THUMB DIRECTION FIX:
  - Replaced unreliable dot-product + 2D-projected direction with raw Y-coordinate
    comparison: thumb tip below wrist.y → thumb_down, above wrist.y - offset → thumb_up

DYNAMIC TRACKER FIX:
  - Applied EMA smoothing (α=0.4) to wrist.x before velocity calculation
  - Lowered SWIPE_VELOCITY_THRESH: 0.30 → 0.22 (jitter-corrected raw was too high)
  - Increased MIN_SAMPLES: 6 → 8 for more stable velocity signal
  - Removed PINCH_UP/DOWN tracking entirely

OK_SIGN DETECTOR (new):
  - Tracks pinch distance + 3 ext fingers simultaneously
  - Requires sustained pose for ≥ OK_HOLD_SECONDS (0.8s) to trigger
  - Resets immediately on any hand pose change
"""

import math
import time
import numpy as np
from enum import Enum
from collections import deque
from dataclasses import dataclass, field
import os
import logging
from typing import Optional, List

log = logging.getLogger("aircontrol.gesture")


class Gesture(Enum):
    NONE          = "none"
    OPEN_PALM     = "open_palm"      # All 5 extended          → Play/Pause
    FIST          = "fist"           # All loosely curled      → Mute
    POINTING_UP   = "pointing_up"    # Index ext, others curl  → Next Track
    PEACE_SIGN    = "peace_sign"     # Index+Mid ext, rest curl → Prev Track
    THUMB_UP      = "thumb_up"       # Thumb up, loose fist    → Volume Up
    THUMB_DOWN    = "thumb_down"     # Thumb down, loose fist  → Volume Down
    THREE_FINGERS = "three_fingers"  # Idx+Mid+Ring ext        → Seek Forward
    OK_SIGN       = "ok_sign"        # Pinch+3ext held ≥0.8s   → Seek Back
    SWIPE_LEFT    = "swipe_left"     # Wrist move left         → Prev Track (alt)
    SWIPE_RIGHT   = "swipe_right"    # Wrist move right        → Next Track (alt)


class EngineState(Enum):
    IDLE      = "idle"
    TRACKING  = "tracking"
    CONFIRMED = "confirmed"
    COOLDOWN  = "cooldown"


@dataclass
class GestureEvent:
    gesture:      Gesture
    confidence:   float           # 0.0–1.0
    hand_in_frame: bool
    timestamp_ms: int
    hand_bbox:    Optional[List[float]] = None   # [x, y, w, h] normalized


@dataclass
class LandmarkPoint:
    x: float
    y: float
    z: float = 0.0
    visibility: float = 1.0


# ---------------------------------------------------------------------------
# GEOMETRY HELPERS
# ---------------------------------------------------------------------------

def _vec(a: LandmarkPoint, b: LandmarkPoint) -> np.ndarray:
    """Vector from a → b."""
    return np.array([b.x - a.x, b.y - a.y, b.z - a.z])


def _angle_deg(v1: np.ndarray, v2: np.ndarray) -> float:
    """Angle between two vectors in degrees, safe against zero-length."""
    n1, n2 = np.linalg.norm(v1), np.linalg.norm(v2)
    if n1 < 1e-9 or n2 < 1e-9:
        return 0.0
    cos_a = np.clip(np.dot(v1, v2) / (n1 * n2), -1.0, 1.0)
    return math.degrees(math.acos(cos_a))


def _finger_curl(lm: list, tip: int, dip: int, pip: int, mcp: int) -> float:
    """
    Returns the EXTERIOR angle at the PIP joint — the angle between:
      - v_base: direction FROM pip BACK TO mcp  (proximal segment, backward)
      - v_tip:  direction FROM pip FORWARD TO tip (distal segment, forward)

    Geometry:
      Extended finger (straight): both segments point opposite ways → ~180°
      Curled finger (fist):       both segments point same way (toward palm) → ~0-30°

    Reliable range:
      > 125° → extended
      < 115° → curled
      115–125° → ambiguous / partial

    CRITICAL: v_base must be the BACKWARD vector (pip→mcp), NOT the forward
    vector (mcp→pip). Using (mcp→pip) gives 0° for extended — inverted!
    """
    v_base = _vec(lm[pip], lm[mcp])  # pip → mcp  (backward toward wrist)
    v_tip  = _vec(lm[pip], lm[tip])  # pip → tip  (forward toward fingertip)
    return _angle_deg(v_base, v_tip)


def _thumb_curl(lm: list) -> float:
    """
    Thumb exterior angle at MCP joint:
      v_base = direction FROM mcp BACK TO cmc (backward toward wrist)
      v_tip  = direction FROM mcp FORWARD TO tip

    Extended thumb → ~180°,  Curled thumb → small angle.
    Same convention as _finger_curl.
    """
    v_base = _vec(lm[2], lm[1])   # mcp → cmc (backward)
    v_tip  = _vec(lm[2], lm[4])   # mcp → tip (forward)
    return _angle_deg(v_base, v_tip)


def _normalize_landmarks(lm: list) -> list:
    """
    Translate so wrist (lm[0]) is origin, scale by palm width
    (wrist→middle-mcp distance). Makes detection scale-invariant.
    """
    origin   = np.array([lm[0].x, lm[0].y, lm[0].z])
    palm_ref = np.array([lm[9].x, lm[9].y, lm[9].z])
    scale    = np.linalg.norm(palm_ref - origin)
    if scale < 1e-9:
        return lm

    normalized = []
    for p in lm:
        raw = np.array([p.x, p.y, p.z])
        n   = (raw - origin) / scale
        normalized.append(LandmarkPoint(x=n[0], y=n[1], z=n[2],
                                        visibility=p.visibility))
    return normalized


def _pinch_dist(lm: list) -> float:
    """Euclidean distance between thumb tip (4) and index tip (8)."""
    return math.hypot(lm[4].x - lm[8].x, lm[4].y - lm[8].y)


# ---------------------------------------------------------------------------
# THRESHOLDS — v3.0 Calibrated
# ---------------------------------------------------------------------------

# Finger extension (angle between mcp→pip and pip→tip vectors)
EXTENDED_THRESH     = 125.0   # > this → extended       (was 130°, now more forgiving)
CURLED_THRESH       = 115.0   # < this → curled          (was 120°, wider partial zone)

# Tight curl: used for FIST verification only
TIGHT_CURLED_THRESH = 105.0   # < this → tightly curled  (was 100°, natural fists: 105–115°)

# Loose curl: used for THUMB_UP/DOWN — just "not extended"
LOOSE_CURLED_THRESH = 125.0   # < this → loosely curled  (NEW: matches EXTENDED_THRESH)

# OK_SIGN: pinch distance threshold (generous)
OK_PINCH_THRESH     = 0.09    # normalized (generous — was 0.06 for pinch, far too tight)
OK_HOLD_SECONDS     = 0.8     # seconds the OK pose must be held before firing

# Thumb direction (raw Y in normalized coords — after normalization, wrist is origin)
# Positive Y in normalized space = toward fingers (up in palm frame)
THUMB_UP_Y_THRESH   =  0.30   # thumb tip Y > this → thumb pointing up
THUMB_DOWN_Y_THRESH = -0.20   # thumb tip Y < this → thumb pointing down


def _finger_state(angle: float) -> str:
    """Return 'extended', 'curled', or 'partial'."""
    if angle >= EXTENDED_THRESH:
        return "extended"
    elif angle <= CURLED_THRESH:
        return "curled"
    else:
        return "partial"


def _confidence_from_margin(value: float, threshold: float, scale: float = 15.0) -> float:
    """Convert a margin from a threshold into a 0–1 confidence score."""
    return min(1.0, abs(value - threshold) / scale)


# ---------------------------------------------------------------------------
# STATIC GESTURE CLASSIFIER  — v3.0 (specific → generic priority)
# ---------------------------------------------------------------------------

def classify_static(lm: list) -> tuple[Gesture, float]:
    """
    Classify static hand pose from 21 normalized landmarks.
    Returns (Gesture, confidence 0.0–1.0).

    Landmark layout:
        Thumb:  1(cmc) 2(mcp) 3(ip)  4(tip)
        Index:  5(mcp) 6(pip) 7(dip) 8(tip)
        Middle: 9(mcp) 10(pip) 11(dip) 12(tip)
        Ring:   13(mcp) 14(pip) 15(dip) 16(tip)
        Pinky:  17(mcp) 18(pip) 19(dip) 20(tip)

    Priority order (specific → generic):
        1. THREE_FINGERS (idx+mid+ring ext, pinky curl)
        2. PEACE_SIGN    (idx+mid ext, ring+pinky curl)
        3. POINTING_UP   (idx ext, others curl)
        4. OK_SIGN       → handled by OKSignTracker (not here)
        5. THUMB_UP      (thumb up, 4 fingers loose-curled)
        6. THUMB_DOWN    (thumb down, 4 fingers loose-curled)
        7. OPEN_PALM     (all 5 extended)
        8. FIST          (all 4 tightly curled)
    """
    # ── Compute all curl angles ──────────────────────────────────────────
    idx_curl   = _finger_curl(lm, 8,  7,  6,  5)
    mid_curl   = _finger_curl(lm, 12, 11, 10, 9)
    ring_curl  = _finger_curl(lm, 16, 15, 14, 13)
    pinky_curl = _finger_curl(lm, 20, 19, 18, 17)
    thumb_curl = _thumb_curl(lm)

    # ── Boolean states ────────────────────────────────────────────────────
    idx_ext    = idx_curl   >= EXTENDED_THRESH
    mid_ext    = mid_curl   >= EXTENDED_THRESH
    ring_ext   = ring_curl  >= EXTENDED_THRESH
    pinky_ext  = pinky_curl >= EXTENDED_THRESH
    thumb_ext  = thumb_curl >= EXTENDED_THRESH

    idx_curled   = idx_curl   <= CURLED_THRESH
    mid_curled   = mid_curl   <= CURLED_THRESH
    ring_curled  = ring_curl  <= CURLED_THRESH
    pinky_curled = pinky_curl <= CURLED_THRESH

    # Tight curl: for FIST
    idx_tight   = idx_curl   <= TIGHT_CURLED_THRESH
    mid_tight   = mid_curl   <= TIGHT_CURLED_THRESH
    ring_tight  = ring_curl  <= TIGHT_CURLED_THRESH
    pinky_tight = pinky_curl <= TIGHT_CURLED_THRESH

    # Loose curl: for THUMB_UP/DOWN — just "not extended"
    idx_loose   = idx_curl   < LOOSE_CURLED_THRESH
    mid_loose   = mid_curl   < LOOSE_CURLED_THRESH
    ring_loose  = ring_curl  < LOOSE_CURLED_THRESH
    pinky_loose = pinky_curl < LOOSE_CURLED_THRESH

    # ── Thumb direction via normalized Y coordinate ───────────────────────
    # After normalization wrist is at origin (0,0,0).
    # In MediaPipe image-space: Y increases downward.
    # After normalization relative to palm: thumb tip above origin = negative Y = UP.
    thumb_tip_y = lm[4].y   # normalized Y (wrist=0, middle-MCP=~1.0)
    thumb_is_up   = thumb_tip_y < -THUMB_UP_Y_THRESH    # tip well above wrist
    thumb_is_down = thumb_tip_y > -THUMB_DOWN_Y_THRESH  # tip at or below wrist

    # ── 1. THREE_FINGERS: index+middle+ring extended, pinky curled ───────
    if idx_ext and mid_ext and ring_ext and pinky_curled:
        margins = [
            idx_curl  - EXTENDED_THRESH,
            mid_curl  - EXTENDED_THRESH,
            ring_curl - EXTENDED_THRESH,
            CURLED_THRESH - pinky_curl,
        ]
        conf = min(1.0, sum(margins) / 40.0)
        return Gesture.THREE_FINGERS, max(0.65, conf)

    # ── 2. PEACE_SIGN: index+middle extended, ring+pinky loosely curled ──
    if idx_ext and mid_ext and ring_curl < LOOSE_CURLED_THRESH and pinky_curl < LOOSE_CURLED_THRESH:
        # Ensure ring and pinky aren't also extended (would be OPEN_PALM/THREE_FINGERS)
        if not ring_ext and not pinky_ext:
            idx_m   = idx_curl  - EXTENDED_THRESH
            mid_m   = mid_curl  - EXTENDED_THRESH
            ring_m  = LOOSE_CURLED_THRESH - ring_curl
            pinky_m = LOOSE_CURLED_THRESH - pinky_curl
            conf = min(1.0, (idx_m + mid_m + ring_m + pinky_m) / 40.0)
            return Gesture.PEACE_SIGN, max(0.65, conf)

    # ── 3. POINTING_UP: index extended, middle+ring+pinky curled ─────────
    if idx_ext and mid_curled and ring_curled and pinky_curled:
        idx_m   = idx_curl   - EXTENDED_THRESH
        other_m = (CURLED_THRESH - mid_curl + CURLED_THRESH - ring_curl +
                   CURLED_THRESH - pinky_curl) / 3.0
        conf = min(1.0, (idx_m + other_m) / 30.0)
        return Gesture.POINTING_UP, max(0.65, conf)

    # ── 4. THUMB_UP: thumb extended upward, 4 fingers loosely curled ──────
    if thumb_ext and thumb_is_up and idx_loose and mid_loose and ring_loose and pinky_loose:
        thumb_m   = thumb_curl - EXTENDED_THRESH
        fingers_m = (LOOSE_CURLED_THRESH - idx_curl + LOOSE_CURLED_THRESH - mid_curl +
                     LOOSE_CURLED_THRESH - ring_curl + LOOSE_CURLED_THRESH - pinky_curl) / 4.0
        conf = min(1.0, (thumb_m + max(0.0, fingers_m)) / 30.0)
        return Gesture.THUMB_UP, max(0.70, conf)

    # ── 5. THUMB_DOWN: thumb extended downward, 4 fingers loosely curled ─
    if thumb_ext and thumb_is_down and idx_loose and mid_loose and ring_loose and pinky_loose:
        thumb_m   = thumb_curl - EXTENDED_THRESH
        fingers_m = (LOOSE_CURLED_THRESH - idx_curl + LOOSE_CURLED_THRESH - mid_curl +
                     LOOSE_CURLED_THRESH - ring_curl + LOOSE_CURLED_THRESH - pinky_curl) / 4.0
        conf = min(1.0, (thumb_m + max(0.0, fingers_m)) / 30.0)
        return Gesture.THUMB_DOWN, max(0.70, conf)

    # ── 6. OPEN_PALM: all 5 fingers extended ──────────────────────────────
    if idx_ext and mid_ext and ring_ext and pinky_ext:
        avg_angle = (idx_curl + mid_curl + ring_curl + pinky_curl) / 4.0
        conf = min(1.0, (avg_angle - EXTENDED_THRESH) / 20.0)
        return Gesture.OPEN_PALM, max(0.60, conf)

    # ── 7. FIST: all 4 fingers tightly curled ─────────────────────────────
    if idx_tight and mid_tight and ring_tight and pinky_tight:
        avg_angle = (idx_curl + mid_curl + ring_curl + pinky_curl) / 4.0
        conf = min(1.0, (TIGHT_CURLED_THRESH - avg_angle) / 20.0)
        return Gesture.FIST, max(0.60, conf)

    return Gesture.NONE, 0.0


# ---------------------------------------------------------------------------
# OK SIGN TRACKER — Hold-based detection
# ---------------------------------------------------------------------------

class OKSignTracker:
    """
    Detects the OK sign: thumb-index pinch (generous threshold) while
    middle, ring, and pinky fingers are extended — held for OK_HOLD_SECONDS.

    This hold requirement prevents false triggers during pinch-approach frames.
    Resets immediately if hand leaves the OK pose.
    """

    def __init__(self):
        self._hold_start: Optional[float] = None

    def update(self, lm: list) -> tuple[Gesture, float]:
        """Call each frame. Returns (OK_SIGN, conf) when hold completes, else NONE."""
        dist       = _pinch_dist(lm)
        mid_curl   = _finger_curl(lm, 12, 11, 10, 9)
        ring_curl  = _finger_curl(lm, 16, 15, 14, 13)
        pinky_curl = _finger_curl(lm, 20, 19, 18, 17)

        mid_ext   = mid_curl   >= EXTENDED_THRESH
        ring_ext  = ring_curl  >= EXTENDED_THRESH
        pinky_ext = pinky_curl >= EXTENDED_THRESH

        is_ok_pose = dist < OK_PINCH_THRESH and mid_ext and ring_ext and pinky_ext

        if is_ok_pose:
            now = time.time()
            if self._hold_start is None:
                self._hold_start = now
            hold_duration = now - self._hold_start
            if hold_duration >= OK_HOLD_SECONDS:
                self._hold_start = None   # reset after fire
                # Confidence based on how well fingers are extended
                conf = min(1.0, (mid_curl + ring_curl + pinky_curl - 3 * EXTENDED_THRESH) / 30.0)
                return Gesture.OK_SIGN, max(0.75, conf)
        else:
            self._hold_start = None

        return Gesture.NONE, 0.0

    def reset(self):
        self._hold_start = None

    @property
    def hold_progress(self) -> float:
        """0.0–1.0 how far into the hold we are (for UI indicator)."""
        if self._hold_start is None:
            return 0.0
        return min(1.0, (time.time() - self._hold_start) / OK_HOLD_SECONDS)


# ---------------------------------------------------------------------------
# DYNAMIC GESTURE TRACKER — EMA-Smoothed Swipe Detection
# ---------------------------------------------------------------------------

class DynamicTracker:
    """
    Tracks wrist velocity over a rolling window using EMA smoothing.

    v2.1 problem: raw wrist.x velocity was noisy (MediaPipe jitters ±0.02–0.04
    normalized per frame). The fix: apply EMA (α=0.4) to wrist.x before
    computing velocity. This kills per-frame noise while preserving macro motion.

    Thresholds reduced: 0.30 → 0.22 normalized/sec (now achievable after smoothing).
    """

    SWIPE_VELOCITY_THRESH = 0.22   # normalized units/sec (was 0.30 — raw was too strict)
    EMA_ALPHA             = 0.4    # smoothing factor (0 = no smoothing, 1 = no memory)
    MIN_SAMPLES           = 8      # minimum history entries before swipe evaluation

    def __init__(self):
        self._wrist_history: deque = deque()   # (time, smoothed_x)
        self._smoothed_x: Optional[float] = None

    def update(self, lm: list) -> tuple[Gesture, float]:
        now   = time.time()
        wrist = lm[0]

        # ── EMA smoothing on wrist.x ──
        if self._smoothed_x is None:
            self._smoothed_x = wrist.x
        else:
            self._smoothed_x = (self.EMA_ALPHA * wrist.x +
                                 (1.0 - self.EMA_ALPHA) * self._smoothed_x)

        # ── Prune history to 1 second ──
        cutoff = now - 1.0
        while self._wrist_history and self._wrist_history[0][0] < cutoff:
            self._wrist_history.popleft()

        self._wrist_history.append((now, self._smoothed_x))

        # ── SWIPE detection (needs ≥ MIN_SAMPLES for stable velocity) ──
        if len(self._wrist_history) >= self.MIN_SAMPLES:
            dt = self._wrist_history[-1][0] - self._wrist_history[0][0]
            dx = self._wrist_history[-1][1] - self._wrist_history[0][1]
            if dt > 0.08:
                velocity = dx / dt
                if velocity > self.SWIPE_VELOCITY_THRESH:
                    self._wrist_history.clear()
                    self._smoothed_x = None
                    return Gesture.SWIPE_RIGHT, min(1.0, velocity / 0.40)
                elif velocity < -self.SWIPE_VELOCITY_THRESH:
                    self._wrist_history.clear()
                    self._smoothed_x = None
                    return Gesture.SWIPE_LEFT, min(1.0, -velocity / 0.40)

        return Gesture.NONE, 0.0

    def reset(self):
        self._wrist_history.clear()
        self._smoothed_x = None


# ---------------------------------------------------------------------------
# NEURAL CLASSIFIER WRAPPER (optional — falls back to classify_static)
# ---------------------------------------------------------------------------

class NeuralGestureClassifier:
    """Wrapper for the TorchScript MLP gesture classifier."""
    def __init__(self, model_path: str):
        self.model = None
        self.enabled = False
        # Updated labels to match v3.0 gesture set
        self.labels = [
            "none", "open_palm", "fist", "pointing_up",
            "thumb_up", "thumb_down", "peace_sign",
            "three_fingers", "ok_sign"
        ]

        try:
            import torch
            if os.path.exists(model_path):
                self.model = torch.jit.load(model_path)
                self.model.eval()
                self.enabled = True
                log.info(f"Neural gesture classifier loaded from {model_path}")
            else:
                log.warning(f"Neural model not found at {model_path}. Falling back to static thresholds.")
        except ImportError:
            log.warning("PyTorch not installed. Falling back to static angle thresholds.")
        except Exception as e:
            log.error(f"Error loading neural model: {e}")

    def predict(self, norm_lm: list) -> tuple[Gesture, float]:
        if not self.enabled:
            return classify_static(norm_lm)

        import torch
        features = []
        for lm in norm_lm:
            features.extend([lm.x, lm.y, lm.z])

        with torch.no_grad():
            x = torch.tensor([features], dtype=torch.float32)
            outputs = self.model(x)
            probs = torch.nn.functional.softmax(outputs, dim=1)
            conf, pred = torch.max(probs, 1)
            label = self.labels[pred.item()]
            try:
                return Gesture(label), conf.item()
            except ValueError:
                # Label from old model not in new enum — fall back
                return classify_static(norm_lm)


# ---------------------------------------------------------------------------
# FINITE STATE MACHINE GESTURE ENGINE — v3.0
# ---------------------------------------------------------------------------

class GestureEngine:
    """
    Enterprise FSM gesture engine — v3.0.

    States:
        IDLE     → No hand / no candidate gesture
        TRACKING → Candidate gesture detected, building confidence window
        CONFIRMED→ Gesture fired (event emitted)
        COOLDOWN → Debounce period, ignore new gestures

    Confidence Window: Gesture must appear in N consecutive frames to confirm.
    Dynamic gestures (swipes, ok_sign) bypass the window — they self-confirm.
    """

    CONFIDENCE_WINDOW_SIZE = 7      # frames
    MIN_AVG_CONFIDENCE     = 0.65   # avg window confidence required to confirm

    def __init__(self, debounce_time: float = 1.2):
        self.debounce_time = debounce_time

        self._state                 = EngineState.IDLE
        self._candidate: Gesture    = Gesture.NONE
        self._candidate_confidence  = 0.0
        self._window: deque         = deque(maxlen=self.CONFIDENCE_WINDOW_SIZE)
        self._last_confirm_time     = 0.0
        self._dynamic               = DynamicTracker()
        self._ok_tracker            = OKSignTracker()

        # Public readable state
        self.hand_in_frame: bool  = False
        self.current_confidence:  float = 0.0
        self.ok_progress: float   = 0.0    # 0.0–1.0 hold progress for UI

        model_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), '..', 'model', 'gesture_clf.pt')
        )
        self._classifier = NeuralGestureClassifier(model_path)

    def process(self, landmarks: list) -> Optional[GestureEvent]:
        """
        Main entry point. Call once per camera frame.
        Returns a GestureEvent if a gesture was confirmed, else None.
        """
        now    = time.time()
        now_ms = int(now * 1000)

        if not landmarks:
            self.hand_in_frame      = False
            self.current_confidence = 0.0
            self.ok_progress        = 0.0
            self._state             = EngineState.IDLE
            self._window.clear()
            self._dynamic.reset()
            self._ok_tracker.reset()
            return GestureEvent(
                gesture=Gesture.NONE,
                confidence=0.0,
                hand_in_frame=False,
                timestamp_ms=now_ms,
            )

        self.hand_in_frame = True

        # ── Normalize landmarks ──
        norm_lm = _normalize_landmarks(landmarks)

        # ── Run all detectors ──
        dynamic_gest, dynamic_conf = self._dynamic.update(norm_lm)
        ok_gest,      ok_conf      = self._ok_tracker.update(norm_lm)
        static_gest,  static_conf  = self._classifier.predict(norm_lm)

        # Update OK progress for UI
        self.ok_progress = self._ok_tracker.hold_progress

        # ── Priority: OK_SIGN > Swipe > Static ──
        if ok_gest != Gesture.NONE:
            detected = ok_gest
            conf     = ok_conf
        elif dynamic_gest != Gesture.NONE:
            detected = dynamic_gest
            conf     = dynamic_conf
        else:
            detected = static_gest
            conf     = static_conf

        self.current_confidence = conf

        # ── COOLDOWN: wait out debounce ──
        if self._state == EngineState.COOLDOWN:
            if now - self._last_confirm_time >= self.debounce_time:
                self._state = EngineState.IDLE
                self._window.clear()
            else:
                return GestureEvent(
                    gesture=Gesture.NONE,
                    confidence=conf,
                    hand_in_frame=True,
                    timestamp_ms=now_ms,
                )

        # ── Dynamic / OK_SIGN bypass confidence window — self-confirmed ──
        if ok_gest != Gesture.NONE or dynamic_gest != Gesture.NONE:
            self._state             = EngineState.COOLDOWN
            self._last_confirm_time = now
            self._window.clear()
            return GestureEvent(
                gesture=detected,
                confidence=conf,
                hand_in_frame=True,
                timestamp_ms=now_ms,
            )

        # ── IDLE / TRACKING: static gesture confidence window ──
        if detected == Gesture.NONE:
            self._window.clear()
            self._candidate = Gesture.NONE
            self._state     = EngineState.IDLE
            return GestureEvent(
                gesture=Gesture.NONE,
                confidence=0.0,
                hand_in_frame=True,
                timestamp_ms=now_ms,
            )

        # Same candidate — accumulate
        if detected == self._candidate:
            self._window.append(conf)
            self._state = EngineState.TRACKING
        else:
            # New candidate — reset window
            self._candidate            = detected
            self._candidate_confidence = conf
            self._window.clear()
            self._window.append(conf)
            self._state = EngineState.TRACKING

        # ── CONFIRM if window full and avg confidence sufficient ──
        if (len(self._window) >= self.CONFIDENCE_WINDOW_SIZE
                and sum(self._window) / len(self._window) >= self.MIN_AVG_CONFIDENCE):
            avg_conf                = sum(self._window) / len(self._window)
            self._state             = EngineState.COOLDOWN
            self._last_confirm_time = now
            self._window.clear()
            self._candidate         = Gesture.NONE

            return GestureEvent(
                gesture=detected,
                confidence=avg_conf,
                hand_in_frame=True,
                timestamp_ms=now_ms,
            )

        return GestureEvent(
            gesture=Gesture.NONE,
            confidence=conf,
            hand_in_frame=True,
            timestamp_ms=now_ms,
        )

    def set_debounce(self, seconds: float):
        self.debounce_time = max(0.3, seconds)
