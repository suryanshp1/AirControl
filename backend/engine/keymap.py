"""
AirControl — Gesture-to-Action Keymap Engine v3.0

Manages the mapping between detected gestures and logical actions.
Persists user customizations to a JSON file.

v3.0 changes:
  - VICTORY → PEACE_SIGN
  - Added THREE_FINGERS, OK_SIGN
  - Removed PINCH_UP, PINCH_DOWN
  - Remapped FIST → MUTE (was STOP)
  - Remapped POINTING_UP → NEXT_TRACK (was FULLSCREEN)
  - Remapped PEACE_SIGN → PREVIOUS_TRACK (was VICTORY → MUTE)
  - Remapped THUMB_UP → VOLUME_UP (was SEEK_FORWARD_10S)
  - Remapped THUMB_DOWN → VOLUME_DOWN (was SEEK_BACK_10S)
  - THREE_FINGERS → SEEK_FORWARD_10S
  - OK_SIGN → SEEK_BACK_10S
"""

import json
import os
from dataclasses import dataclass
from typing import Dict, Optional
from .gesture import Gesture


# ── All possible actions AirControl can perform ──
AVAILABLE_ACTIONS = {
    "PLAY_PAUSE":       "Play / Pause",
    "STOP":             "Stop",
    "NEXT_TRACK":       "Next Track",
    "PREVIOUS_TRACK":   "Previous Track",
    "VOLUME_UP":        "Volume Up",
    "VOLUME_DOWN":      "Volume Down",
    "SEEK_FORWARD_10S": "Seek Forward 10s",
    "SEEK_BACK_10S":    "Seek Back 10s",
    "FULLSCREEN":       "Toggle Fullscreen",
    "MUTE":             "Mute / Unmute",
    "NONE":             "No Action",
}

# ── Default gesture → action mapping (v3.0) ──
# Each gesture is uniquely identifiable, no two gestures share the same action.
DEFAULT_KEYMAP: Dict[str, str] = {
    # Static gestures
    Gesture.OPEN_PALM.name:     "PLAY_PAUSE",        # ✋ Open palm  → Play/Pause
    Gesture.FIST.name:          "MUTE",              # ✊ Fist       → Mute (was STOP)
    Gesture.POINTING_UP.name:   "NEXT_TRACK",        # ☝️ Pointing   → Next Track
    Gesture.PEACE_SIGN.name:    "PREVIOUS_TRACK",    # ✌️ Peace      → Prev Track
    Gesture.THUMB_UP.name:      "VOLUME_UP",         # 👍 Thumb Up   → Volume Up
    Gesture.THUMB_DOWN.name:    "VOLUME_DOWN",       # 👎 Thumb Down → Volume Down
    Gesture.THREE_FINGERS.name: "SEEK_FORWARD_10S",  # 🖖 3 Fingers  → Seek +10s
    Gesture.OK_SIGN.name:       "SEEK_BACK_10S",     # 👌 OK sign    → Seek -10s (hold)
    # Dynamic gestures
    Gesture.SWIPE_LEFT.name:    "PREVIOUS_TRACK",    # 👈 Swipe Left  → Prev Track (alt)
    Gesture.SWIPE_RIGHT.name:   "NEXT_TRACK",        # 👉 Swipe Right → Next Track (alt)
}

_CONFIG_FILE = os.path.join(os.path.dirname(__file__), "..", "keymap.json")


class GestureKeymap:
    """
    Enterprise keymap with JSON persistence.
    User overrides are layered on top of defaults.
    """

    def __init__(self):
        self._map: Dict[str, str] = dict(DEFAULT_KEYMAP)
        self._load_from_disk()

    def _load_from_disk(self):
        try:
            if os.path.exists(_CONFIG_FILE):
                with open(_CONFIG_FILE, "r") as f:
                    saved = json.load(f)
                    for gesture_name, action in saved.items():
                        if gesture_name in DEFAULT_KEYMAP and action in AVAILABLE_ACTIONS:
                            self._map[gesture_name] = action
        except Exception:
            pass  # Silently fall back to defaults

    def _save_to_disk(self):
        try:
            with open(_CONFIG_FILE, "w") as f:
                json.dump(self._map, f, indent=2)
        except Exception:
            pass

    def get_action(self, gesture: Gesture) -> str:
        """Returns the action string for a given gesture. 'NONE' if not mapped."""
        return self._map.get(gesture.name, "NONE")

    def set_action(self, gesture_name: str, action: str) -> bool:
        """Update a single gesture's action. Returns False if invalid input."""
        if gesture_name not in DEFAULT_KEYMAP:
            return False
        if action not in AVAILABLE_ACTIONS:
            return False
        self._map[gesture_name] = action
        self._save_to_disk()
        return True

    def reset_to_defaults(self):
        self._map = dict(DEFAULT_KEYMAP)
        self._save_to_disk()

    def to_dict(self) -> Dict[str, Dict[str, str]]:
        """Returns full map including human-readable labels."""
        result = {}
        for gesture_name, action in self._map.items():
            result[gesture_name] = {
                "action":       action,
                "action_label": AVAILABLE_ACTIONS.get(action, action),
            }
        return result
