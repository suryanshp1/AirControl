# AirControl — Neural Gesture Command Center ✋🎵

> **Control your system media entirely hands-free.** AirControl uses your webcam and a local AI vision engine to translate real-time hand gestures into OS-level media commands — no cloud, no tracking, no latency.

![Platform](https://img.shields.io/badge/platform-macOS-black?style=flat-square&logo=apple)
![Python](https://img.shields.io/badge/python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)
![Tauri](https://img.shields.io/badge/tauri-v2-FFC131?style=flat-square&logo=tauri&logoColor=black)
![React](https://img.shields.io/badge/react-19-61DAFB?style=flat-square&logo=react&logoColor=black)
![FastAPI](https://img.shields.io/badge/fastapi-latest-009688?style=flat-square&logo=fastapi&logoColor=white)
![MediaPipe](https://img.shields.io/badge/mediapipe-hands-FF6F00?style=flat-square&logo=google&logoColor=white)

---

## 🎯 Gesture Set (v3.0)

AirControl v3.0 ships **10 uniquely identifiable gestures** — redesigned from the ground up for reliability, zero ambiguity, and natural feel.

| Gesture | Emoji | How to Perform | Default Action |
|:--------|:-----:|:---------------|:---------------|
| **Open Palm** | ✋ | All 5 fingers extended, palm facing camera | Play / Pause |
| **Fist** | ✊ | Close all fingers into a fist | Mute / Unmute |
| **Point Up** | ☝️ | Extend only your index finger | Next Track |
| **Peace Sign** | ✌️ | Extend index + middle, curl others | Previous Track |
| **Thumb Up** | 👍 | Thumb pointing up, fingers loosely closed | Volume Up |
| **Thumb Down** | 👎 | Thumb pointing down, fingers loosely closed | Volume Down |
| **3 Fingers** | 🖖 | Extend index, middle & ring fingers | Seek Forward 10s |
| **OK Sign** | 👌 | Pinch thumb + index, hold for **0.8s** | Seek Back 10s |
| **Swipe Right** | 👉 | Move hand quickly to the right | Next Track (alt) |
| **Swipe Left** | 👈 | Move hand quickly to the left | Previous Track (alt) |

> All mappings are fully remappable from the **Remap** tab in the desktop UI.

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────┐
│                   Tauri Desktop Window                  │
│              React · TypeScript · Vite                  │
│          (Command Center UI — port 1420 internal)       │
└────────────────────┬────────────────────────────────────┘
                     │ WebSocket (ws://localhost:8000/ws)
                     │ REST API  (http://localhost:8000)
┌────────────────────▼────────────────────────────────────┐
│              FastAPI · Uvicorn (Python)                  │
│                   localhost:8000                         │
├─────────────────────────────────────────────────────────┤
│  Vision Engine (OpenCV + MediaPipe HandLandmarker)       │
│    ↓ 21 landmarks per frame                             │
│  Gesture Engine v3.0 (FSM + EMA Smoothing)              │
│    ↓ confirmed gesture event                            │
│  Player Adapter (System / VLC / Spotify / YouTube)      │
│    ↓ pynput media keys · osascript AppleScript          │
│  macOS System Media Controls                            │
└─────────────────────────────────────────────────────────┘
```

**Frontend (Desktop UI):**
- **Tauri v2** — native macOS desktop window, minimal footprint
- **React 19 + TypeScript** via Vite
- **Zustand** for lightweight real-time state management
- Live MJPEG camera preview with hand skeleton overlay
- Gesture chip grid with active-gesture highlighting
- Remappable keymap editor with per-gesture hints
- Gesture activity log with confidence scores

**Backend (Local AI Engine):**
- **FastAPI + Uvicorn** — async REST + WebSocket API on `localhost:8000`
- **OpenCV** — async frame capture from webcam
- **MediaPipe HandLandmarker** — 21 3D landmarks at 30 FPS, CPU-only
- **Gesture Engine v3.0** — geometric classifier + 7-frame confidence FSM
- **EMA-smoothed swipe detection** — eliminates landmark jitter
- **OK Sign hold tracker** — 0.8s sustained pose for seek-back
- **Player Adapters** — System (global media keys), VLC HTTP API, Spotify AppleScript, YouTube browser

---

## 🛠️ Prerequisites

Ensure the following are installed on your Mac before proceeding:

| Dependency | Install |
|:-----------|:--------|
| **Node.js + npm** (LTS) | [nodejs.org](https://nodejs.org/) |
| **Rust + Cargo** (for Tauri) | `curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \| sh` |
| **Python 3.11+** | [python.org](https://www.python.org/) |
| **Webcam** | Built-in or USB |

---

## 🚀 Installation & Setup

**1. Clone the repo**
```bash
git clone https://github.com/suryanshp1/AirControl.git
cd AirControl
```

**2. Install UI dependencies**
```bash
npm install
```

**3. Set up the Python virtual environment**
```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cd ..
```

**4. Launch the app**
```bash
chmod +x run.sh
./run.sh
```

`run.sh` boots both the FastAPI backend (port 8000) and the Tauri desktop window simultaneously. The app opens **only in the native desktop window** — no browser tab is launched.

---

## ⚠️ macOS Permissions (Required)

AirControl needs camera access and the ability to send system media keys. If gestures are detected but produce no action, grant the following in **System Settings → Privacy & Security**:

| Permission | Why Needed |
|:-----------|:-----------|
| **Camera** | Webcam access for hand tracking |
| **Accessibility** | Sending global media key codes via pynput |
| **Automation** | osascript control of System Events (for Spotify/YouTube adapters) |

> Grant permissions to whichever terminal app you use to run `./run.sh` (Terminal, iTerm2, Ghostty, etc.).

---

## 🧰 Gesture Debug Tool

A live debug overlay lets you see raw finger curl angles and gesture classification in real-time — useful for calibrating to your specific camera and lighting:

```bash
cd backend
source venv/bin/activate
python debug_gestures.py
```

The overlay shows:
- Per-finger curl angle in degrees
- Current gesture classification + confidence
- OK Sign hold progress bar
- EMA-smoothed wrist velocity (for swipe tuning)

Press **Q** to quit.

---

## 🎛️ Player Adapters

AirControl supports multiple backends for sending media commands:

| Adapter | Method | Notes |
|:--------|:-------|:------|
| **System** | macOS global media keys (pynput) | Works with any player |
| **Spotify** | AppleScript | Spotify must be running |
| **VLC** | VLC HTTP API | Enable in VLC → Prefs → Web Interface |
| **YouTube** | Browser keystroke injection | Focuses active browser window |

Switch adapters from the **Settings** tab in the UI.

---

## 🐋 Docker (Backend Only)

> [!WARNING]
> Tauri desktop windows and macOS hardware (webcam, AppleScript) cannot run inside Docker on Mac. Docker support is for backend-only testing on Linux hosts.

```bash
cd backend
docker compose up --build
```

---

## 🔧 Customization

| What | Where |
|:-----|:------|
| Gesture thresholds & classifier logic | `backend/engine/gesture.py` |
| Gesture → action default mapping | `backend/engine/keymap.py` |
| User remapping (persisted) | `backend/keymap.json` (auto-created) |
| UI styles & design system | `src/App.css` |
| State management | `src/store.ts` |

---

## 📁 Project Structure

```
AirControl/
├── src/                        # React frontend
│   ├── App.tsx                 # Main UI (camera, chips, log, settings)
│   ├── App.css                 # Design system + component styles
│   └── store.ts                # Zustand state store
├── src-tauri/                  # Tauri (Rust) desktop shell
├── backend/
│   ├── main.py                 # FastAPI app + WebSocket broadcaster
│   ├── engine/
│   │   ├── gesture.py          # Gesture engine v3.0 (FSM + classifier)
│   │   ├── vision.py           # OpenCV + MediaPipe pipeline
│   │   ├── keymap.py           # Gesture → action mapper
│   │   ├── player_adapter.py   # System / VLC / Spotify / YouTube
│   │   └── telemetry.py        # FPS + event counters
│   ├── debug_gestures.py       # Live debug overlay tool
│   └── requirements.txt
├── run.sh                      # One-command launcher
└── vite.config.ts              # Vite (Tauri dev server, no browser auto-open)
```

---

## 📜 License

MIT — free to use, modify, and distribute.

---

**Enjoy controlling your desktop, hands-free.** ✋
