import type { MeshProfile } from "../types";

export interface ProfileUi {
  panelTitle: string;
  gaugeLabel: string;
  accent: string;
}

/** Mirrors the backend ProfileSpec — UI labels per OMNI_MESH_PROFILE. */
export const PROFILE_UI: Record<MeshProfile, ProfileUi> = {
  ROBOTICS: {
    panelTitle: "Kinematic Visual Handoff Tracker",
    gaugeLabel: "Actuator Peak Torque (Nm)",
    accent: "#38bdf8",
  },
  MANUFACTURING: {
    panelTitle: "Factory Floor PLC Register Analyzer",
    gaugeLabel: "Bus Core Line Mean Voltage (V)",
    accent: "#f59e0b",
  },
  HEALTH_TECH: {
    panelTitle: "HIPAA Biometric Cohort Monitor",
    gaugeLabel: "Mean Heart-Rate Variability (ms)",
    accent: "#34d399",
  },
  COMMERCIAL: {
    panelTitle: "Subscription Revenue & Churn Monitor",
    gaugeLabel: "Mean Monthly Revenue ($)",
    accent: "#a78bfa",
  },
  CLINICAL: {
    panelTitle: "De-identified eCRF Safety Monitor",
    gaugeLabel: "Mean Adverse-Event Rate",
    accent: "#f472b6",
  },
};

export const PROFILES: MeshProfile[] = [
  "ROBOTICS",
  "MANUFACTURING",
  "HEALTH_TECH",
  "COMMERCIAL",
  "CLINICAL",
];
