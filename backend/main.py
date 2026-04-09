"""
AirControl — FastAPI Backend (Enterprise)

Endpoints:
  REST  — /start  /stop  /status  /config  /players  /keymap
  WS    — /ws     (real-time gesture event stream)
  Stream— /stream (MJPEG camera preview)
"""

import asyncio
import json
import logging
import time
from typing import Set

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from engine.vision import VisionEngine
from engine.keymap import AVAILABLE_ACTIONS
from engine.player_adapter import get_available_adapters

# ── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
log = logging.getLogger("aircontrol.api")

# ── App Init ─────────────────────────────────────────────────────────────────
app = FastAPI(title="AirControl API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

engine = VisionEngine()

# ── WebSocket Connection Manager ─────────────────────────────────────────────

class ConnectionManager:
    def __init__(self):
        self._clients: Set[WebSocket] = set()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self._clients.add(ws)
        log.info("WS client connected — total=%d", len(self._clients))

    def disconnect(self, ws: WebSocket):
        self._clients.discard(ws)
        log.info("WS client disconnected — total=%d", len(self._clients))

    async def broadcast(self, payload: dict):
        msg = json.dumps(payload)
        dead = set()
        for ws in self._clients:
            try:
                await ws.send_text(msg)
            except Exception:
                dead.add(ws)
        for ws in dead:
            self._clients.discard(ws)

ws_manager = ConnectionManager()

# ── Event Queue Broadcaster ───────────────────────────────────────────────────

_event_queue: asyncio.Queue = asyncio.Queue(maxsize=100)

@app.on_event("startup")
async def _startup():
    loop = asyncio.get_event_loop()
    engine.set_event_loop(loop, _event_queue)
    asyncio.create_task(_broadcast_loop())
    log.info("AirControl API v2.0.0 started")

async def _broadcast_loop():
    """Continuously pull from queue and broadcast to all WS clients."""
    while True:
        try:
            payload = await asyncio.wait_for(_event_queue.get(), timeout=5.0)
            if ws_manager._clients:
                await ws_manager.broadcast(payload)
        except asyncio.TimeoutError:
            # Send a heartbeat so clients can detect connection health
            if engine.running and ws_manager._clients:
                await ws_manager.broadcast({
                    "type": "heartbeat",
                    "ts":   int(time.time() * 1000),
                    "fps":  round(engine.fps, 1),
                })
        except Exception as exc:
            log.error("Broadcast error: %s", exc)


# ── Pydantic Models ───────────────────────────────────────────────────────────

class StartPayload(BaseModel):
    camera_index: int = Field(default=0, ge=0, le=10)

class ConfigPayload(BaseModel):
    debounce_time: float = Field(default=1.2, ge=0.3, le=5.0)
    adapter_id: str     = Field(default="system")

class KeymapUpdatePayload(BaseModel):
    gesture_name: str
    action: str


# ── REST Endpoints ────────────────────────────────────────────────────────────

@app.get("/status")
def get_status():
    return engine.status

@app.post("/start")
def start_camera(payload: StartPayload = StartPayload()):
    if engine.start(camera_index=payload.camera_index):
        return {"status": "started", "camera_index": payload.camera_index}
    raise HTTPException(status_code=500, detail="Cannot open camera")

@app.post("/stop")
def stop_camera():
    engine.stop()
    return {"status": "stopped"}

@app.post("/config")
def update_config(config: ConfigPayload):
    engine.set_sensitivity(config.debounce_time)
    engine.set_adapter(config.adapter_id)
    return {"status": "updated", "config": config.model_dump()}

@app.get("/players")
def list_players():
    return {"players": get_available_adapters()}

@app.get("/keymap")
def get_keymap():
    return {
        "keymap":  engine.keymap.to_dict(),
        "actions": AVAILABLE_ACTIONS,
    }

@app.put("/keymap")
def update_keymap(payload: KeymapUpdatePayload):
    success = engine.keymap.set_action(payload.gesture_name, payload.action)
    if not success:
        raise HTTPException(status_code=400,
                            detail=f"Invalid gesture '{payload.gesture_name}' or action '{payload.action}'")
    return {"status": "updated", "gesture": payload.gesture_name, "action": payload.action}

@app.post("/keymap/reset")
def reset_keymap():
    engine.keymap.reset_to_defaults()
    return {"status": "reset", "keymap": engine.keymap.to_dict()}

from engine.telemetry import get_metrics

@app.get("/metrics")
def metrics():
    return get_metrics(engine.fps, engine.running, engine._adapter_id)


# ── WebSocket Endpoint ────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws_manager.connect(ws)
    try:
        # Send current status immediately on connect
        await ws.send_text(json.dumps({
            "type":    "connected",
            "status":  engine.status,
        }))
        while True:
            # Keep connection alive — client can send pings
            data = await ws.receive_text()
            if data == "ping":
                await ws.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        ws_manager.disconnect(ws)
    except Exception as e:
        log.warning("WS error: %s", e)
        ws_manager.disconnect(ws)


# ── MJPEG Camera Preview Stream ───────────────────────────────────────────────

async def _mjpeg_generator():
    """Yields MJPEG frames from the vision engine's latest preview frame."""
    boundary = b"--aircontrol_frame"
    while True:
        frame = engine.get_preview_frame()
        if frame:
            header = (
                boundary + b"\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Content-Length: " + str(len(frame)).encode() + b"\r\n\r\n"
            )
            yield header + frame + b"\r\n"
        await asyncio.sleep(1.0 / 20)   # 20fps preview cap

@app.get("/stream")
async def camera_stream():
    if not engine.running:
        raise HTTPException(status_code=503, detail="Engine not running")
    return StreamingResponse(
        _mjpeg_generator(),
        media_type="multipart/x-mixed-replace; boundary=aircontrol_frame",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False,
                log_level="info")
