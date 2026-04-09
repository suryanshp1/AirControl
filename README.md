# AirControl: Universal Gesture Media Controller ✋🎵

AirControl is an AI-powered desktop application allowing users to control system-wide media playback (play, pause, next, previous, volume) using hand gestures detected via webcam.

Built with performance, privacy, and desktop natively in mind, it utilizes a decentralized architecture: a localized **Python inference engine** (combining OpenCV & MediaPipe) for vision processing, hooked to a sleek native **Tauri** desktop window built in pure React.

---

## 🎯 Features & Gesture Mapping

The app translates real-time hand movements into OS-level commands (macOS native Media keys) avoiding dependencies on specific apps like Spotify, VLC, or browser tabs.

| Gesture | Action Triggered | Description |
| :--- | :--- | :--- |
| **Open Palm** ✋ | **Play / Pause** | All outer 4 fingers extended |
| **Fist** ✊ | **Play / Pause** | All fingers folded tightly |
| **Swipe Right** ➡️ | **Next Track** | Hand moves horizontally to the right across the frame |
| **Swipe Left** ⬅️ | **Previous Track** | Hand moves horizontally to the left across the frame |
| **Pinch Up** 🤏⬆ | **Volume Up (+) 5%**| Thumb and Index tips together, moving upwards vertically |
| **Pinch Down** 🤏⬇ | **Volume Down (-) 5%**| Thumb and Index tips together, moving downwards vertically |

*Note: Gestures are processed with an adjustable 1.5s global debounce delay to prevent rapid-fire accidental triggering.*

---

## 🏗️ Architecture Stack

**Frontend (Client sidecar):**
- **Tauri** (Minimal footprint UI container leveraging macOS native WebViews)
- **Vite + React.js + TypeScript**
- **TailwindCSS (v4)** for modern "Tech Noir" dynamic aesthetics
- **Zustand** for non-blocking local state management

**Backend (Local AI Engine):**
- **Python 3.11+**
- **FastAPI + Uvicorn** (Running as an internal local API `localhost:8000`)
- **OpenCV (`cv2`)** for asynchronous Webcam frame extraction
- **MediaPipe Hands** for blazing fast, CPU-efficient spatial hand tracking
- **osascript (AppleScript)** for native macOS system-level media manipulations

---

## 🛠️ Prerequisites

Before you can build or run AirControl, ensure you have the following installed on your Mac:

1. **[Node.js](https://nodejs.org/) & NPM** (latest LTS)
2. **Setup Tauri dependencies (Rust & Cargo)**:
   ```bash
   curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
   ```
3. **Python 3.11+**
4. A functioning internal or external webcam.

---

## 🚀 Installation & First Run

Clone or locate this directory and navigate your terminal into it.

```bash
cd /path/to/AirControl
```

### 1. Install UI Dependencies
```bash
npm install
```

### 2. Setup the Python Engine Virtual Environment
```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cd ..
```

### 3. Run the Development Server
We provide a convenient shell script to boot both the FastAPI backend and the Tauri frontend simultaneously:

```bash
chmod +x run.sh
./run.sh
```

---

## ⚠️ CRITICAL: macOS Permissions

Because AirControl intercepts system-wide hardware (Webcam) and controls global input media key-codes, macOS security policies require explicit manual permissions for the host process running it. 

If gestures are printing out locally but nothing is happening, verify the following:

Open **System Settings -> Privacy & Security**:
1. **Camera**: Grant permission to your `Terminal` app, `iTerm2`, `VSCode`, or whatever container launched `run.sh`.
2. **Accessibility**: Grant permissions to `Terminal` / `iTerm2` (necessary for `osascript` to broadcast key code 100/101).
3. **Automation**: Ensure your Terminal is allowed to control "System Events".

---

## 🐋 Docker (Backend Dev Testing Only)

> [!WARNING]
> Running native UI windows (Tauri) and accessing native hardware (macOS Webcam + AppleScript Sandbox) from inside a Docker Desktop container on Mac is effectively broken due to Apple Virtualization Framework mapping limitations.

For isolated testing of the FastAPI engine on Linux hosts, the provided Docker stack runs the backend only:

```bash
cd backend
docker compose up --build
```

---

## 🧪 Customization

To modify the confidence thresholds, edit `backend/engine/gesture.py`. 
To alter the UI aesthetic or default settings, modify `src/store.ts` and `src/App.css`. 

**Enjoy controlling your desktop hands-free!**
