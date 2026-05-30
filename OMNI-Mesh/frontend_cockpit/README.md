# OMNI-Mesh Operator Cockpit

Adaptive React 18 + Zustand + Canvas frontend for the OMNI-Mesh streaming gateway
(Phase 4). The UI is **polymorphic**: panel titles, gauge labels, and accent colour
re-sync from the live `profile` field on each incoming telemetry frame.

## Architecture

- **`store/cockpitStore.ts`** — Zustand store. Low-speed dashboard state (profile,
  titles, status) drives normal React re-renders; the bounded 30Hz metric `history`
  feeds the chart.
- **`hooks/useTelemetry.ts`** — WebSocket client (auto-reconnect) → `ingestFrame`.
- **`components/CameraFeed.tsx`** — Canvas animated via `requestAnimationFrame` off a
  **ref** (not React state), with a dashed predictive bounding box extrapolated forward
  by the injected network latency. This is the dual-speed decoupling.
- **`components/MetricGauge.tsx`** — Recharts sparkline + big readout of the live metric.

## Run

```bash
cd frontend_cockpit
npm install
npm run dev          # http://localhost:5173

# In another terminal, start the gateway for the profile you want to watch:
#   cd .. && OMNI_MESH_PROFILE=ROBOTICS OMNI_MESH_MASKING_SALT=... omni-mesh gateway
```

Point the cockpit at a different gateway with `VITE_GATEWAY_WS`:

```bash
VITE_GATEWAY_WS=ws://127.0.0.1:8000/ws/telemetry npm run dev
```

`npm run build` type-checks (`tsc -b`) and produces a production bundle in `dist/`.
