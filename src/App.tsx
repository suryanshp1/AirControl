import { useEffect, useRef, useCallback, useState } from 'react';
import './App.css';
import { useAppStore, GestureLogEntry } from './store';

const API  = 'http://localhost:8000';
const WS   = 'ws://localhost:8000/ws';
const STREAM = `${API}/stream`;

// ── Gesture metadata: emoji, chip label, and how-to hint ────────────────────
const GESTURE_META: Record<string, { emoji: string; label: string; hint: string }> = {
  OPEN_PALM:     { emoji: '✋', label: 'Open Palm',   hint: 'All 5 fingers extended, palm facing camera' },
  FIST:          { emoji: '✊', label: 'Fist',         hint: 'Close all fingers into a fist' },
  POINTING_UP:   { emoji: '☝️', label: 'Point Up',    hint: 'Extend only your index finger' },
  PEACE_SIGN:    { emoji: '✌️', label: 'Peace Sign',  hint: 'Extend index + middle, curl others' },
  THUMB_UP:      { emoji: '👍', label: 'Thumb Up',    hint: 'Thumb pointing up, fingers loosely closed' },
  THUMB_DOWN:    { emoji: '👎', label: 'Thumb Down',  hint: 'Thumb pointing down, fingers loosely closed' },
  THREE_FINGERS: { emoji: '🖖', label: '3 Fingers',   hint: 'Extend index, middle & ring fingers' },
  OK_SIGN:       { emoji: '👌', label: 'OK Sign',     hint: 'Pinch thumb + index, hold for 0.8s' },
  SWIPE_LEFT:    { emoji: '👈', label: 'Swipe Left',  hint: 'Quickly move your whole hand left' },
  SWIPE_RIGHT:   { emoji: '👉', label: 'Swipe Right', hint: 'Quickly move your whole hand right' },
};

const ALL_GESTURES = Object.keys(GESTURE_META);

// ── Toast System ─────────────────────────────────────────────────────────────
interface Toast { id: number; message: string; type: 'info' | 'success' | 'error'; }

let _toastId = 0;

function ToastContainer({ toasts }: { toasts: Toast[] }) {
  return (
    <div className="toast-container">
      {toasts.map(t => (
        <div key={t.id} className={`toast ${t.type}`}>{t.message}</div>
      ))}
    </div>
  );
}

// ── Camera Pane ───────────────────────────────────────────────────────────────
function CameraPane({
  running,
  onStart,
  onStop,
  fps,
}: {
  running: boolean;
  onStart: () => void;
  onStop: () => void;
  fps: number;
}) {
  return (
    <aside className="pane-camera">
      <div className="pane-header">
        <div className={`dot-status ${running ? 'active pulse' : 'inactive'}`} />
        <span className="pane-header-label">Camera Feed</span>
      </div>

      <div className="camera-viewport">
        {running ? (
          <>
            <img
              className="camera-feed"
              src={STREAM}
              alt="Live camera feed with hand skeleton overlay"
            />
            <div className="camera-scanlines" />
            <div className="camera-border-overlay" />
            <div className="corner-bracket tl" />
            <div className="corner-bracket tr" />
            <div className="corner-bracket bl" />
            <div className="corner-bracket br" />
          </>
        ) : (
          <div className="camera-placeholder">
            <svg className="camera-placeholder-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M23 7l-7 5 7 5V7z"/>
              <rect x="1" y="5" width="15" height="14" rx="2" ry="2"/>
            </svg>
            <span className="camera-placeholder-text">Camera offline</span>
          </div>
        )}
      </div>

      <div className="camera-info-bar">
        <span className="fps-counter">
          {running ? <><span>{fps.toFixed(0)}</span> fps</> : '— fps'}
        </span>
        <button
          id="camera-toggle-btn"
          className={`btn-camera ${running ? 'stop' : 'start'}`}
          onClick={running ? onStop : onStart}
        >
          {running ? (
            <>
              <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
                <rect x="4" y="4" width="16" height="16" rx="2"/>
              </svg>
              Stop
            </>
          ) : (
            <>
              <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
                <polygon points="5,3 19,12 5,21"/>
              </svg>
              Start
            </>
          )}
        </button>
      </div>
    </aside>
  );
}

// ── Hand Presence Orb ────────────────────────────────────────────────────────
function HandOrb({
  running,
  gesture,
  handInFrame,
  confidence,
}: {
  running: boolean;
  gesture: string;
  handInFrame: boolean;
  confidence: number;
}) {
  const hasGesture = gesture !== 'NONE' && gesture !== '';
  const orbClass   = !running ? 'idle' : handInFrame ? (hasGesture ? 'gesture-active' : 'detected') : 'idle';

  return (
    <div className="orb-section">
      <div className="orb-container">
        <div className={`orb-ring ring-outer ${handInFrame ? 'hand-detected' : ''}`} />
        <div className={`orb-ring ring-mid  ${handInFrame ? 'hand-detected' : ''}`} />
        <div className={`orb-core ${orbClass}`}>
          {/* Hand SVG icon */}
          <svg
            className={`orb-icon ${!running || !handInFrame ? 'inactive' : ''}`}
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M18 11V6a2 2 0 0 0-2-2v0a2 2 0 0 0-2 2v0"/>
            <path d="M14 10V4a2 2 0 0 0-2-2v0a2 2 0 0 0-2 2v2"/>
            <path d="M10 10.5V6a2 2 0 0 0-2-2v0a2 2 0 0 0-2 2v8"/>
            <path d="M18 8a2 2 0 1 1 4 0v6a8 8 0 0 1-8 8h-2c-2.8 0-4.5-.86-5.99-2.34l-3.6-3.6a2 2 0 0 1 2.83-2.82L7 15"/>
          </svg>
        </div>
      </div>

      {/* Gesture name + action */}
      <div className="gesture-display">
        <div
          id="gesture-name-display"
          className={`gesture-name ${hasGesture && running ? 'active' : 'none'}`}
        >
          {hasGesture && running
            ? gesture.replace(/_/g, ' ')
            : running ? '— waiting —' : '— offline —'}
        </div>
      </div>

      {/* Confidence bar */}
      {running && (
        <div className="confidence-section">
          <div className="confidence-header">
            <span className="confidence-label">Detection Confidence</span>
            <span className="confidence-value">{(confidence * 100).toFixed(0)}%</span>
          </div>
          <div className="confidence-track">
            <div
              className="confidence-fill"
              style={{ width: `${Math.max(0, Math.min(100, confidence * 100))}%` }}
            />
          </div>
        </div>
      )}
    </div>
  );
}

// ── Gesture Chip Grid ────────────────────────────────────────────────────────
function GestureChipGrid({
  activeGesture,
  keymap,
}: {
  activeGesture: string;
  keymap: Record<string, { action: string; action_label: string }>;
}) {
  return (
    <div className="gesture-grid">
      {ALL_GESTURES.map((name) => {
        const meta     = GESTURE_META[name];
        const isActive = name === activeGesture;
        const action   = keymap[name]?.action_label ?? '—';
        return (
          <div
            key={name}
            className={`gesture-chip ${isActive ? 'active-chip' : ''}`}
            title={meta.hint}
          >
            <span className="gesture-chip-emoji">{meta.emoji}</span>
            <span className="gesture-chip-name">{meta.label}</span>
            <span className="gesture-chip-action">{action}</span>
          </div>
        );
      })}
    </div>
  );
}

// ── Gesture Log ──────────────────────────────────────────────────────────────
function GestureLog({ entries }: { entries: GestureLogEntry[] }) {
  if (entries.length === 0) {
    return (
      <div className="log-empty">
        <span style={{ fontSize: 32 }}>🤫</span>
        <span>No gestures detected yet.<br />Start the camera and wave your hand.</span>
      </div>
    );
  }

  return (
    <div className="gesture-log">
      {entries.map((e) => {
        const meta = GESTURE_META[e.gesture] ?? { emoji: '👋', label: e.gesture };
        const ts   = new Date(e.timestamp_ms);
        const timeStr = `${String(ts.getHours()).padStart(2,'0')}:${String(ts.getMinutes()).padStart(2,'0')}:${String(ts.getSeconds()).padStart(2,'0')}`;
        return (
          <div key={e.id} className="log-entry">
            <span className="log-entry-icon">{meta.emoji}</span>
            <div className="log-entry-body">
              <div className="log-entry-gesture">{e.gesture.replace(/_/g, ' ')}</div>
              <div className="log-entry-action">{e.action || '—'}</div>
            </div>
            <div className="log-entry-meta">
              <span className="log-entry-conf">{(e.confidence * 100).toFixed(0)}%</span>
              <span className="log-entry-time">{timeStr}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ── Keymap Editor ─────────────────────────────────────────────────────────────
function KeymapEditor({
  keymap,
  availableActions,
  onUpdate,
  onReset,
}: {
  keymap: Record<string, { action: string; action_label: string }>;
  availableActions: Record<string, string>;
  onUpdate: (gesture: string, action: string) => void;
  onReset: () => void;
}) {
  return (
    <>
      <div className="keymap-editor">
        {ALL_GESTURES.map((name) => {
          const meta    = GESTURE_META[name];
          const current = keymap[name]?.action ?? 'NONE';
          return (
            <div key={name} className="keymap-row">
              <span className="keymap-gesture-icon">{meta.emoji}</span>
              <div className="keymap-gesture-info">
                <span className="keymap-gesture-name">{meta.label}</span>
                <span className="keymap-gesture-hint">{meta.hint}</span>
              </div>
              <span className="keymap-arrow">→</span>
              <select
                id={`keymap-select-${name}`}
                className="keymap-select"
                value={current}
                onChange={(e) => onUpdate(name, e.target.value)}
              >
                {Object.entries(availableActions).map(([k, v]) => (
                  <option key={k} value={k}>{v}</option>
                ))}
              </select>
            </div>
          );
        })}
      </div>
      <button className="keymap-reset-btn" onClick={onReset}>
        Reset to Defaults
      </button>
    </>
  );
}

// ── Settings Panel ────────────────────────────────────────────────────────────
function SettingsPanel({
  sensitivity,
  adapterId,
  players,
  onSensitivity,
  onAdapterSelect,
}: {
  sensitivity: number;
  adapterId: string;
  players: { id: string; label: string; available: boolean }[];
  onSensitivity: (v: number) => void;
  onAdapterSelect: (id: string) => void;
}) {
  return (
    <div className="settings-panel">
      <div className="settings-group">
        <div className="settings-group-label">Gesture Detection</div>
        <div className="settings-row">
          <span className="settings-label">Debounce Time</span>
          <span className="settings-value">{sensitivity}s</span>
        </div>
        <input
          id="sensitivity-slider"
          type="range"
          className="range-slider"
          min={0.3}
          max={3.0}
          step={0.1}
          value={sensitivity}
          onChange={(e) => onSensitivity(parseFloat(e.target.value))}
        />
        <div className="settings-row">
          <span className="settings-label" style={{ fontSize: 11, opacity: 0.6 }}>
            Low = fast triggers · High = more deliberate
          </span>
        </div>
      </div>

      <div className="settings-group">
        <div className="settings-group-label">Target Player</div>
        {players.length === 0 && (
          <div style={{ color: 'var(--text-muted)', fontSize: 12, padding: '8px 0' }}>
            Loading players…
          </div>
        )}
        {players.map((p) => (
          <div
            key={p.id}
            id={`player-${p.id}`}
            className={`player-card ${adapterId === p.id ? 'selected-player' : ''}`}
            onClick={() => onAdapterSelect(p.id)}
          >
            <div className={`player-dot ${p.available ? 'avail' : 'unavail'}`} />
            <span className="player-name">{p.label}</span>
            {adapterId === p.id && (
              <span className="player-selected-badge">active</span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Status Bar ────────────────────────────────────────────────────────────────
function StatusBar({
  wsConnected,
  cameraRunning,
  fps,
  adapter,
  latestAction,
}: {
  wsConnected: boolean;
  cameraRunning: boolean;
  fps: number;
  adapter: string;
  latestAction: string;
}) {
  return (
    <div className="status-bar">
      <div className={`status-item ${wsConnected ? 'connected' : 'disconnected'}`}>
        WS: <span>{wsConnected ? 'Connected' : 'Disconnected'}</span>
      </div>
      <div className="status-divider" />
      <div className="status-item">
        Engine: <span>{cameraRunning ? 'Running' : 'Stopped'}</span>
      </div>
      <div className="status-divider" />
      <div className="status-item">
        FPS: <span>{cameraRunning ? fps.toFixed(0) : '—'}</span>
      </div>
      <div className="status-divider" />
      <div className="status-item">
        Player: <span style={{ textTransform: 'capitalize' }}>{adapter}</span>
      </div>
      <div className="status-bar-right">
        <div className="status-item" style={{ color: 'var(--text-muted)', maxWidth: 320, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {latestAction}
        </div>
      </div>
    </div>
  );
}


// ═══════════════════════════════════════════════════════════════════════════════
// ROOT APP
// ═══════════════════════════════════════════════════════════════════════════════
export default function App() {
  const store = useAppStore();
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [toasts, setToasts] = useState<Toast[]>([]);

  // ── Toast helper ──────────────────────────────────────────────────────────
  const showToast = useCallback((message: string, type: Toast['type'] = 'info') => {
    const id = ++_toastId;
    setToasts((t) => [...t, { id, message, type }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 3500);
  }, []);

  // ── Load initial data (keymap + players) ──────────────────────────────────
  const loadMeta = useCallback(async () => {
    try {
      const [kmRes, plRes] = await Promise.all([
        fetch(`${API}/keymap`),
        fetch(`${API}/players`),
      ]);
      if (kmRes.ok) {
        const km = await kmRes.json();
        store.setKeymap(km.keymap, km.actions);
      }
      if (plRes.ok) {
        const pl = await plRes.json();
        store.setPlayers(pl.players);
      }
    } catch {
      // backend not yet running — will retry via WS connected event
    }
  }, []);

  // ── WebSocket management ──────────────────────────────────────────────────
  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const ws = new WebSocket(WS);
    wsRef.current = ws;

    ws.onopen = () => {
      store.setWsConnected(true);
      loadMeta();
    };

    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data as string);

        if (msg.type === 'connected') {
          const s = msg.status;
          store.setCameraRunning(s.is_running ?? false);
          store.setAdapterId(s.adapter ?? 'system');
          loadMeta();
        }

        if (msg.type === 'gesture_event') {
          const { gesture, confidence, hand_in_frame, timestamp_ms, fps, action, adapter } = msg;
          store.setLiveState(gesture, confidence, hand_in_frame, fps, action ?? '');

          if (gesture && gesture !== 'NONE' && action) {
            store.pushGestureEvent(gesture, action, confidence, timestamp_ms, adapter ?? 'system');
          }
        }

        if (msg.type === 'heartbeat') {
          store.setLiveState(
            store.latestGesture,
            store.confidence,
            store.handInFrame,
            msg.fps ?? store.fps,
            store.latestAction,
          );
        }
      } catch {}
    };

    ws.onclose = () => {
      store.setWsConnected(false);
      // Auto-reconnect with exponential backoff (max ~10s)
      reconnectTimer.current = setTimeout(connect, Math.min(10000, 1500 + Math.random() * 1000));
    };

    ws.onerror = () => { ws.close(); };
  }, [store, loadMeta]);

  useEffect(() => {
    connect();
    return () => {
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  }, []);

  // ── Camera actions ───────────────────────────────────────────────────────
  const handleStart = async () => {
    try {
      const res = await fetch(`${API}/start`, { method: 'POST' });
      if (res.ok) {
        store.setCameraRunning(true);
        showToast('Camera started — gesture away!', 'success');
      } else {
        showToast('Failed to start camera', 'error');
      }
    } catch {
      showToast('Backend unreachable', 'error');
    }
  };

  const handleStop = async () => {
    try {
      const res = await fetch(`${API}/stop`, { method: 'POST' });
      if (res.ok) {
        store.setCameraRunning(false);
        showToast('Camera stopped', 'info');
      }
    } catch {}
  };

  // ── Config sync ──────────────────────────────────────────────────────────
  const syncConfig = useCallback(async (debounce: number, adapter: string) => {
    try {
      await fetch(`${API}/config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ debounce_time: debounce, adapter_id: adapter }),
      });
    } catch {}
  }, []);

  const handleSensitivity = (v: number) => {
    store.setSensitivity(v);
    syncConfig(v, store.adapterId);
  };

  const handleAdapterSelect = (id: string) => {
    store.setAdapterId(id);
    syncConfig(store.sensitivity, id);
    showToast(`Player switched to ${id}`, 'success');
  };

  // ── Keymap actions ───────────────────────────────────────────────────────
  const handleKeymapUpdate = async (gesture: string, action: string) => {
    const label = store.availableActions[action] ?? action;
    store.updateKeymapEntry(gesture, action, label);
    try {
      await fetch(`${API}/keymap`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ gesture_name: gesture, action }),
      });
      showToast(`${gesture.replace(/_/g,' ')} → ${label}`, 'success');
    } catch {
      showToast('Failed to update keymap', 'error');
    }
  };

  const handleKeymapReset = async () => {
    try {
      const res = await fetch(`${API}/keymap/reset`, { method: 'POST' });
      if (res.ok) {
        const data = await res.json();
        store.setKeymap(data.keymap, store.availableActions);
        showToast('Keymap reset to defaults', 'info');
      }
    } catch {}
  };

  return (
    <>
      <ToastContainer toasts={toasts} />

      <div className="app-shell">
        {/* ── LEFT: Camera ── */}
        <CameraPane
          running={store.cameraRunning}
          onStart={handleStart}
          onStop={handleStop}
          fps={store.fps}
        />

        {/* ── CENTER: Command Center ── */}
        <main className="pane-center">
          {/* Brand */}
          <div className="brand">
            <div className="brand-logo">
              <svg className="brand-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 2L2 7l10 5 10-5-10-5z"/>
                <path d="M2 17l10 5 10-5"/>
                <path d="M2 12l10 5 10-5"/>
              </svg>
              <span className="brand-name">AirControl</span>
            </div>
            <span className="brand-tagline">Neural Gesture Command Center</span>
          </div>

          {/* Orb */}
          <HandOrb
            running={store.cameraRunning}
            gesture={store.latestGesture}
            handInFrame={store.handInFrame}
            confidence={store.confidence}
          />

          {/* Action Badge (below orb) */}
          <div className={`action-badge ${store.latestGesture !== 'NONE' && store.cameraRunning ? 'active-action' : ''}`}>
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <polygon points="5 3 19 12 5 21 5 3"/>
            </svg>
            {store.latestAction}
          </div>

          {/* Gesture chips */}
          <GestureChipGrid
            activeGesture={store.cameraRunning ? store.latestGesture : ''}
            keymap={store.keymap}
          />
        </main>

        {/* ── RIGHT: Controls ── */}
        <aside className="pane-right">
          {/* Tab nav */}
          <div className="tab-nav" role="tablist">
            {(['log', 'keymap', 'settings'] as const).map((tab) => (
              <button
                key={tab}
                id={`tab-${tab}`}
                role="tab"
                aria-selected={store.activePanel === tab}
                className={`tab-btn ${store.activePanel === tab ? 'active' : ''}`}
                onClick={() => store.setActivePanel(tab)}
              >
                {tab === 'log' ? 'Log' : tab === 'keymap' ? 'Remap' : 'Settings'}
              </button>
            ))}
          </div>

          <div className="tab-content">
            {store.activePanel === 'log' && (
              <GestureLog entries={store.gestureLog} />
            )}
            {store.activePanel === 'keymap' && (
              <KeymapEditor
                keymap={store.keymap}
                availableActions={store.availableActions}
                onUpdate={handleKeymapUpdate}
                onReset={handleKeymapReset}
              />
            )}
            {store.activePanel === 'settings' && (
              <SettingsPanel
                sensitivity={store.sensitivity}
                adapterId={store.adapterId}
                players={store.players}
                onSensitivity={handleSensitivity}
                onAdapterSelect={handleAdapterSelect}
              />
            )}
          </div>
        </aside>
      </div>

      {/* Bottom status bar */}
      <StatusBar
        wsConnected={store.wsConnected}
        cameraRunning={store.cameraRunning}
        fps={store.fps}
        adapter={store.adapterId}
        latestAction={store.latestAction}
      />
    </>
  );
}
