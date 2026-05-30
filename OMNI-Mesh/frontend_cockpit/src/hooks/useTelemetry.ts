import { useEffect } from "react";

import { useCockpitStore } from "../store/cockpitStore";
import type { TelemetryFrame } from "../types";

/** Connect to the OMNI-Mesh gateway WebSocket and stream frames into the store. */
export function useTelemetry(url: string): void {
  const ingestFrame = useCockpitStore((s) => s.ingestFrame);
  const setConnected = useCockpitStore((s) => s.setConnected);

  useEffect(() => {
    let active = true;
    let socket: WebSocket | null = null;
    let retry: ReturnType<typeof setTimeout> | undefined;

    const connect = () => {
      socket = new WebSocket(url);
      socket.onopen = () => {
        if (active) setConnected(true);
      };
      socket.onmessage = (event) => {
        try {
          ingestFrame(JSON.parse(event.data) as TelemetryFrame);
        } catch {
          /* ignore malformed frames */
        }
      };
      socket.onclose = () => {
        if (!active) return;
        setConnected(false);
        retry = setTimeout(connect, 1500); // auto-reconnect
      };
      socket.onerror = () => socket?.close();
    };

    connect();
    return () => {
      active = false;
      if (retry) clearTimeout(retry);
      socket?.close();
    };
  }, [url, ingestFrame, setConnected]);
}
