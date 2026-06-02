export type MeshProfile =
  | "ROBOTICS"
  | "MANUFACTURING"
  | "HEALTH_TECH"
  | "COMMERCIAL"
  | "CLINICAL";

export type HardwareStatus =
  | "AUTONOMOUS"
  | "ALERT_PENDING"
  | "TELEOPERATION"
  | "SAFE_STOP";

/** One downsampled frame emitted by the gateway at 30Hz. */
export interface TelemetryFrame {
  profile: MeshProfile;
  label: string;
  metric_value: number;
  sample_count: number;
  status: "idle" | "streaming";
}
