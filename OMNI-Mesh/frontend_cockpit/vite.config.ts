import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The cockpit talks to the OMNI-Mesh streaming gateway (Phase 4).
// Override the target with VITE_GATEWAY_WS at build/dev time if needed.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173 },
});
