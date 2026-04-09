"""
AirControl — Player Adapter System

Abstracts player-specific control behind a unified interface.
Each adapter knows how to control its target player without any
global media key assumptions.

Supported:
  - SystemAdapter  : macOS global media keys (pynput) — universal fallback
  - VLCAdapter     : VLC HTTP API (no window focus needed)
  - SpotifyAdapter : macOS AppleScript (Spotify must be running)
  - YoutubeAdapter : Keyboard shortcuts focused to browser window
"""

import subprocess
import time
import logging
import platform
from abc import ABC, abstractmethod
from typing import Optional

log = logging.getLogger("aircontrol.player")

# ── Lazy import pynput to avoid errors on unsupported systems ──
try:
    from pynput.keyboard import Key, Controller as KeyboardController
    _keyboard = KeyboardController()
    PYNPUT_OK = True
except Exception:
    PYNPUT_OK = False
    _keyboard = None


# ---------------------------------------------------------------------------
# Base Adapter
# ---------------------------------------------------------------------------

class PlayerAdapter(ABC):
    name: str = "base"
    label: str = "Base Adapter"
    platform: str = "all"

    @abstractmethod
    def execute(self, action: str) -> dict:
        """Execute an action string. Returns {success, action_name, error?}."""
        ...

    def is_available(self) -> bool:
        """Override to check if this player is currently running."""
        return True

    def _ok(self, action: str) -> dict:
        return {"success": True, "action_name": action, "adapter": self.name}

    def _err(self, action: str, msg: str) -> dict:
        log.error("[%s] %s: %s", self.name, action, msg)
        return {"success": False, "action_name": action, "adapter": self.name, "error": msg}


# ---------------------------------------------------------------------------
# System Adapter (Global macOS Media Keys) — Universal Fallback
# ---------------------------------------------------------------------------

class SystemAdapter(PlayerAdapter):
    name  = "system"
    label = "System (Global Media Keys)"
    platform = "all"

    _ACTION_MAP = {
        "PLAY_PAUSE":       lambda: SystemAdapter._press(Key.media_play_pause),
        "STOP":             lambda: SystemAdapter._press(Key.media_play_pause),  # media_stop not universally supported
        "NEXT_TRACK":       lambda: SystemAdapter._press(Key.media_next),
        "PREVIOUS_TRACK":   lambda: SystemAdapter._press(Key.media_previous),
        "VOLUME_UP":        lambda: SystemAdapter._applescript("set volume output volume (output volume of (get volume settings) + 10)"),
        "VOLUME_DOWN":      lambda: SystemAdapter._applescript("set volume output volume (output volume of (get volume settings) - 10)"),
        "MUTE":             lambda: SystemAdapter._press(Key.media_volume_mute),
        "SEEK_FORWARD_10S": lambda: None,   # not available via global media keys
        "SEEK_BACK_10S":    lambda: None,
        "FULLSCREEN":       lambda: None,
    }

    @staticmethod
    def _press(key):
        if PYNPUT_OK:
            _keyboard.press(key)
            _keyboard.release(key)

    @staticmethod
    def _applescript(script: str):
        subprocess.run(["osascript", "-e", script], check=True,
                       capture_output=True)

    def execute(self, action: str) -> dict:
        fn = self._ACTION_MAP.get(action)
        if fn is None:
            return self._err(action, f"No system binding for action '{action}'")
        try:
            fn()
            log.info("[system] Executed: %s", action)
            return self._ok(action)
        except Exception as e:
            return self._err(action, str(e))


# ---------------------------------------------------------------------------
# VLC Adapter — Uses VLC's built-in HTTP interface
# ---------------------------------------------------------------------------

class VLCAdapter(PlayerAdapter):
    name    = "vlc"
    label   = "VLC Media Player"
    platform = "all"

    # VLC HTTP API: enable via VLC > Preferences > Interface > Main Interfaces > Web
    # Default: http://localhost:8080

    def __init__(self, host: str = "localhost", port: int = 8080,
                 password: str = ""):
        self._base = f"http://{host}:{port}"
        self._auth = ("", password)

    def _vlc(self, command: str) -> bool:
        """Send a command to VLC HTTP API."""
        try:
            import urllib.request, urllib.parse, base64
            url = f"{self._base}/requests/status.json?command={command}"
            req = urllib.request.Request(url)
            credentials = base64.b64encode(
                f":{self._auth[1]}".encode()).decode("ascii")
            req.add_header("Authorization", f"Basic {credentials}")
            with urllib.request.urlopen(req, timeout=1.5) as r:
                return r.status == 200
        except Exception:
            return False

    def is_available(self) -> bool:
        return self._vlc("pl_pause")  # lightweight check — VLC responds 200 even when paused

    _COMMAND_MAP = {
        "PLAY_PAUSE":       "pl_pause",
        "STOP":             "pl_stop",
        "NEXT_TRACK":       "pl_next",
        "PREVIOUS_TRACK":   "pl_previous",
        "VOLUME_UP":        "volume&val=%2B10",
        "VOLUME_DOWN":      "volume&val=-10",
        "MUTE":             "volume&val=0",
        "SEEK_FORWARD_10S": "seek&val=%2B10",
        "SEEK_BACK_10S":    "seek&val=-10",
        "FULLSCREEN":       "fullscreen",
    }

    def execute(self, action: str) -> dict:
        cmd = self._COMMAND_MAP.get(action)
        if cmd is None:
            return self._err(action, f"VLC has no command for '{action}'")
        success = self._vlc(cmd)
        if success:
            return self._ok(action)
        return self._err(action, "VLC HTTP API not reachable — is VLC running with Web Interface enabled?")


# ---------------------------------------------------------------------------
# Spotify Adapter — macOS AppleScript
# ---------------------------------------------------------------------------

class SpotifyAdapter(PlayerAdapter):
    name    = "spotify"
    label   = "Spotify"
    platform = "darwin"

    def _spotify(self, script: str) -> bool:
        try:
            result = subprocess.run(
                ["osascript", "-e", f'tell application "Spotify" to {script}'],
                capture_output=True, timeout=3, check=True)
            return True
        except subprocess.CalledProcessError:
            return False
        except FileNotFoundError:
            return False

    def is_available(self) -> bool:
        if platform.system() != "Darwin":
            return False
        result = subprocess.run(
            ["osascript", "-e",
             'tell application "System Events" to (name of processes) contains "Spotify"'],
            capture_output=True, text=True, timeout=2)
        return "true" in result.stdout.lower()

    _SCRIPT_MAP = {
        "PLAY_PAUSE":       "playpause",
        "STOP":             "pause",
        "NEXT_TRACK":       "next track",
        "PREVIOUS_TRACK":   "previous track",
        "VOLUME_UP":        "set sound volume to (sound volume + 10)",
        "VOLUME_DOWN":      "set sound volume to (sound volume - 10)",
        "MUTE":             "set sound volume to 0",
        "SEEK_FORWARD_10S": "set player position to (player position + 10)",
        "SEEK_BACK_10S":    "set player position to (player position - 10)",
        "FULLSCREEN":       None,
    }

    def execute(self, action: str) -> dict:
        script = self._SCRIPT_MAP.get(action)
        if script is None:
            return self._err(action, f"Spotify has no action for '{action}'")
        if self._spotify(script):
            return self._ok(action)
        return self._err(action, "Spotify AppleScript failed — is Spotify running?")


# ---------------------------------------------------------------------------
# YouTube/Browser Adapter — Window-focused keyboard shortcuts
# ---------------------------------------------------------------------------

class YouTubeAdapter(PlayerAdapter):
    name    = "youtube"
    label   = "YouTube (Browser)"
    platform = "darwin"

    # YouTube keyboard shortcuts
    _KEY_MAP = {
        "PLAY_PAUSE":       "space",
        "STOP":             None,
        "NEXT_TRACK":       None,
        "PREVIOUS_TRACK":   None,
        "VOLUME_UP":        "up",
        "VOLUME_DOWN":      "down",
        "MUTE":             "m",
        "SEEK_FORWARD_10S": "l",
        "SEEK_BACK_10S":    "j",
        "FULLSCREEN":       "f",
    }

    def _focus_and_press(self, browser_name: str, key: str) -> bool:
        """Focus the browser window and press a key via AppleScript."""
        script = f'''
tell application "{browser_name}"
    activate
end tell
delay 0.1
tell application "System Events"
    keystroke "{key}"
end tell
'''
        try:
            subprocess.run(["osascript", "-e", script],
                           capture_output=True, timeout=3, check=True)
            return True
        except Exception:
            return False

    def _find_running_browser(self) -> Optional[str]:
        for browser in ["Google Chrome", "Firefox", "Safari", "Brave Browser", "Arc"]:
            r = subprocess.run(
                ["osascript", "-e",
                 f'tell application "System Events" to (name of processes) contains "{browser}"'],
                capture_output=True, text=True, timeout=2)
            if "true" in r.stdout.lower():
                return browser
        return None

    def is_available(self) -> bool:
        return platform.system() == "Darwin" and self._find_running_browser() is not None

    def execute(self, action: str) -> dict:
        key = self._KEY_MAP.get(action)
        if key is None:
            return self._err(action, f"YouTube has no key binding for '{action}'")
        browser = self._find_running_browser()
        if not browser:
            return self._err(action, "No supported browser found running")
        if self._focus_and_press(browser, key):
            return self._ok(action)
        return self._err(action, f"Failed to send key to {browser}")


# ---------------------------------------------------------------------------
# Adapter Registry
# ---------------------------------------------------------------------------

ALL_ADAPTERS = {
    "system":  SystemAdapter,
    "vlc":     VLCAdapter,
    "spotify": SpotifyAdapter,
    "youtube": YouTubeAdapter,
}

def get_available_adapters() -> list[dict]:
    """Return list of all adapters with their availability status."""
    result = []
    for key, cls in ALL_ADAPTERS.items():
        try:
            adapter = cls()
            available = adapter.is_available()
        except Exception:
            available = False
        result.append({
            "id":        key,
            "label":     cls.label,
            "platform":  cls.platform,
            "available": available,
        })
    return result

def build_adapter(adapter_id: str, **kwargs) -> PlayerAdapter:
    cls = ALL_ADAPTERS.get(adapter_id, SystemAdapter)
    return cls(**kwargs)
