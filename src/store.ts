import { create } from 'zustand';

export interface GestureLogEntry {
  id: number;
  gesture: string;
  action: string;
  confidence: number;
  timestamp_ms: number;
  adapter: string;
}

export interface KeymapEntry {
  action: string;
  action_label: string;
}

export interface PlayerInfo {
  id: string;
  label: string;
  available: boolean;
}

interface AppState {
  // ── Connection ──
  wsConnected: boolean;
  cameraRunning: boolean;

  // ── Live Gesture State ──
  latestGesture: string;
  latestAction: string;
  confidence: number;
  handInFrame: boolean;
  fps: number;

  // ── History ──
  gestureLog: GestureLogEntry[];
  _logCounter: number;

  // ── Config ──
  sensitivity: number;
  adapterId: string;

  // ── Keymap ──
  keymap: Record<string, KeymapEntry>;
  availableActions: Record<string, string>;

  // ── Players ──
  players: PlayerInfo[];

  // ── UI ──
  activePanel: 'log' | 'keymap' | 'settings';

  // Actions
  setWsConnected: (v: boolean) => void;
  setCameraRunning: (v: boolean) => void;
  pushGestureEvent: (gesture: string, action: string, confidence: number, ts: number, adapter: string) => void;
  setLiveState: (gesture: string, confidence: number, handInFrame: boolean, fps: number, action: string) => void;
  setSensitivity: (v: number) => void;
  setAdapterId: (v: string) => void;
  setKeymap: (km: Record<string, KeymapEntry>, actions: Record<string, string>) => void;
  updateKeymapEntry: (gesture: string, action: string, label: string) => void;
  setPlayers: (p: PlayerInfo[]) => void;
  setActivePanel: (p: 'log' | 'keymap' | 'settings') => void;
}

export const useAppStore = create<AppState>((set) => ({
  wsConnected:   false,
  cameraRunning: false,

  latestGesture: 'NONE',
  latestAction:  'Waiting for camera…',
  confidence:    0,
  handInFrame:   false,
  fps:           0,

  gestureLog:  [],
  _logCounter: 0,

  sensitivity: 1.2,
  adapterId:   'system',

  keymap:           {},
  availableActions: {},
  players:          [],

  activePanel: 'log',

  setWsConnected:   (v) => set({ wsConnected: v }),
  setCameraRunning: (v) => set({ cameraRunning: v }),

  pushGestureEvent: (gesture, action, confidence, ts, adapter) =>
    set((s) => {
      const entry: GestureLogEntry = {
        id:           s._logCounter + 1,
        gesture,
        action,
        confidence,
        timestamp_ms: ts,
        adapter,
      };
      return {
        _logCounter: s._logCounter + 1,
        gestureLog:  [entry, ...s.gestureLog].slice(0, 50),  // keep last 50
        latestGesture: gesture,
        latestAction:  action,
        confidence,
      };
    }),

  setLiveState: (gesture, confidence, handInFrame, fps, action) =>
    set({ latestGesture: gesture, confidence, handInFrame, fps, latestAction: action }),

  setSensitivity: (v) => set({ sensitivity: v }),
  setAdapterId:   (v) => set({ adapterId: v }),

  setKeymap: (km, actions) => set({ keymap: km, availableActions: actions }),
  updateKeymapEntry: (gesture, action, label) =>
    set((s) => ({
      keymap: {
        ...s.keymap,
        [gesture]: { action, action_label: label },
      },
    })),

  setPlayers:     (p) => set({ players: p }),
  setActivePanel: (p) => set({ activePanel: p }),
}));
