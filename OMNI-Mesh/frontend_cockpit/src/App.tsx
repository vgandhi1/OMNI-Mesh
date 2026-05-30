import { Cockpit } from "./components/Cockpit";
import { useTelemetry } from "./hooks/useTelemetry";

const GATEWAY_WS =
  import.meta.env.VITE_GATEWAY_WS ?? "ws://127.0.0.1:8000/ws/telemetry";

export default function App() {
  useTelemetry(GATEWAY_WS);
  return <Cockpit />;
}
