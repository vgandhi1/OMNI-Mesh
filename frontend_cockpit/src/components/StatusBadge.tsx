import { useCockpitStore } from "../store/cockpitStore";
import type { HardwareStatus } from "../types";

const STATUS_COLOR: Record<HardwareStatus, string> = {
  AUTONOMOUS: "#34d399",
  ALERT_PENDING: "#f59e0b",
  TELEOPERATION: "#38bdf8",
  SAFE_STOP: "#f87171",
};

const CYCLE: HardwareStatus[] = [
  "AUTONOMOUS",
  "TELEOPERATION",
  "ALERT_PENDING",
  "SAFE_STOP",
];

export function StatusBadge() {
  const hardwareStatus = useCockpitStore((s) => s.hardwareStatus);
  const connected = useCockpitStore((s) => s.connected);
  const setHardwareStatus = useCockpitStore((s) => s.setHardwareStatus);

  const cycle = () => {
    const next = CYCLE[(CYCLE.indexOf(hardwareStatus) + 1) % CYCLE.length];
    setHardwareStatus(next);
  };

  return (
    <div className="status-row">
      <span
        className="conn-dot"
        style={{ background: connected ? "#34d399" : "#64748b" }}
        title={connected ? "gateway connected" : "disconnected"}
      />
      <span className="conn-label">{connected ? "LIVE 30Hz" : "OFFLINE"}</span>
      <button
        className="status-badge"
        style={{ borderColor: STATUS_COLOR[hardwareStatus], color: STATUS_COLOR[hardwareStatus] }}
        onClick={cycle}
        title="Click to cycle operator mode"
      >
        {hardwareStatus.replace("_", " ")}
      </button>
    </div>
  );
}
