"""
AirControl — Operational Telemetry

Provides system health, FPS rates, and gesture statistics for the enterprise
observability endpoint.
"""

import time
import psutil
from dataclasses import dataclass, field
from collections import defaultdict


@dataclass
class TelemetryData:
    start_time: float = field(default_factory=time.time)
    total_frames: int = 0
    total_gestures: int = 0
    gesture_counts: dict = field(default_factory=lambda: defaultdict(int))
    errors: int = 0

_data = TelemetryData()

def record_frame():
    _data.total_frames += 1

def record_gesture(gesture_name: str):
    _data.total_gestures += 1
    _data.gesture_counts[gesture_name] += 1

def record_error():
    _data.errors += 1

def get_metrics(fps: float, camera_status: bool, adapter_id: str) -> dict:
    now = time.time()
    uptime_s = int(now - _data.start_time)
    
    # get memory and cpu
    try:
        mem_info = psutil.Process().memory_info()
        mem_mb = round(mem_info.rss / 1024 / 1024, 1)
        cpu_percent = psutil.Process().cpu_percent(interval=None)
    except Exception:
        mem_mb = 0.0
        cpu_percent = 0.0

    return {
        "status": "healthy" if camera_status else "idle_or_failed",
        "uptime_s": uptime_s,
        "engine_fps": round(fps, 1),
        "total_gestures_detected": _data.total_gestures,
        "gesture_distribution": dict(_data.gesture_counts),
        "active_adapter": adapter_id,
        "system_cpu_percent": cpu_percent,
        "process_memory_mb": mem_mb,
        "total_errors": _data.errors
    }
