import { create } from "zustand";

import { PROFILE_UI } from "../config/profiles";
import type { HardwareStatus, MeshProfile, TelemetryFrame } from "../types";

const MAX_HISTORY = 120;

export interface MetricPoint {
  t: number;
  value: number;
}

interface CockpitState {
  // --- Low-speed state: drives normal React dashboard re-renders ---
  currentProfile: MeshProfile;
  panelTitle: string;
  gaugeLabel: string;
  accent: string;
  hardwareStatus: HardwareStatus;
  connected: boolean;
  latencyMs: number;

  // --- Telemetry (updated at 30Hz; bounded so React stays cheap) ---
  latest: TelemetryFrame | null;
  history: MetricPoint[];

  initializeUI: (profile: MeshProfile) => void;
  setHardwareStatus: (status: HardwareStatus) => void;
  setConnected: (connected: boolean) => void;
  setLatency: (ms: number) => void;
  ingestFrame: (frame: TelemetryFrame) => void;
}

export const useCockpitStore = create<CockpitState>((set) => ({
  currentProfile: "ROBOTICS",
  panelTitle: PROFILE_UI.ROBOTICS.panelTitle,
  gaugeLabel: PROFILE_UI.ROBOTICS.gaugeLabel,
  accent: PROFILE_UI.ROBOTICS.accent,
  hardwareStatus: "AUTONOMOUS",
  connected: false,
  latencyMs: 60,
  latest: null,
  history: [],

  initializeUI: (profile) =>
    set({
      currentProfile: profile,
      panelTitle: PROFILE_UI[profile].panelTitle,
      gaugeLabel: PROFILE_UI[profile].gaugeLabel,
      accent: PROFILE_UI[profile].accent,
    }),

  setHardwareStatus: (status) => set({ hardwareStatus: status }),
  setConnected: (connected) => set({ connected }),
  setLatency: (ms) => set({ latencyMs: ms }),

  ingestFrame: (frame) =>
    set((state) => {
      const ui = PROFILE_UI[frame.profile];
      const history = [
        ...state.history,
        { t: Date.now(), value: frame.metric_value },
      ].slice(-MAX_HISTORY);
      return {
        latest: frame,
        history,
        currentProfile: frame.profile,
        panelTitle: ui.panelTitle,
        gaugeLabel: ui.gaugeLabel,
        accent: ui.accent,
        hardwareStatus:
          frame.status === "idle" ? "ALERT_PENDING" : state.hardwareStatus,
      };
    }),
}));
