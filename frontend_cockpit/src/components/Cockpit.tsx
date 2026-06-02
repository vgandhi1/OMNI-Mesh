import { useCockpitStore } from "../store/cockpitStore";
import { CameraFeed } from "./CameraFeed";
import { MetricGauge } from "./MetricGauge";
import { ProfileSwitcher } from "./ProfileSwitcher";
import { StatusBadge } from "./StatusBadge";

export function Cockpit() {
  const panelTitle = useCockpitStore((s) => s.panelTitle);
  const currentProfile = useCockpitStore((s) => s.currentProfile);
  const accent = useCockpitStore((s) => s.accent);
  const latencyMs = useCockpitStore((s) => s.latencyMs);
  const setLatency = useCockpitStore((s) => s.setLatency);

  return (
    <div className="cockpit">
      <header className="cockpit-header">
        <div>
          <div className="brand">
            OMNI<span style={{ color: accent }}>·</span>MESH
          </div>
          <div className="brand-sub">Universal Operator Cockpit</div>
        </div>
        <StatusBadge />
      </header>

      <ProfileSwitcher />

      <div className="panel-title" style={{ borderColor: accent }}>
        <span className="profile-tag" style={{ color: accent }}>
          {currentProfile}
        </span>
        {panelTitle}
      </div>

      <main className="cockpit-grid">
        <section className="panel camera-panel">
          <div className="panel-label">Visual Handoff · Predictive Tracking</div>
          <CameraFeed />
          <label className="latency-control">
            Injected latency: <strong>{latencyMs}ms</strong>
            <input
              type="range"
              min={0}
              max={250}
              value={latencyMs}
              onChange={(e) => setLatency(Number(e.target.value))}
            />
          </label>
        </section>

        <MetricGauge />
      </main>

      <footer className="cockpit-footer">
        Streaming from the OMNI-Mesh gateway · 500Hz hardware throttled to a 30Hz render loop
      </footer>
    </div>
  );
}
