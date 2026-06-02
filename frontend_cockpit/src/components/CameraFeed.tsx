import { useEffect, useRef } from "react";

import { useCockpitStore } from "../store/cockpitStore";

/**
 * Lag-compensating Canvas feed. The bounding box is animated via requestAnimationFrame
 * off a ref (NOT React state) so the high-speed render loop never triggers component
 * re-renders — the "dual-speed" decoupling. A dashed predictive box is extrapolated
 * forward using the estimated network latency.
 */
export function CameraFeed() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const latencyMs = useCockpitStore((s) => s.latencyMs);
  const accent = useCockpitStore((s) => s.accent);
  const metricRef = useRef(0);

  // Imperative subscription keeps the latest metric in a ref (no re-render).
  useEffect(
    () =>
      useCockpitStore.subscribe((state) => {
        metricRef.current = state.latest?.metric_value ?? 0;
      }),
    [],
  );

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let raf = 0;
    let x = 40;

    const render = () => {
      const metric = metricRef.current;
      const speed = 0.6 + Math.abs(metric % 5);
      x += speed;
      if (x > canvas.width - 130) x = 40;
      const box = { x, y: 150, w: 92, h: 72 };

      // Background + grid.
      ctx.fillStyle = "#0b1220";
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.strokeStyle = "rgba(148,163,184,0.12)";
      ctx.lineWidth = 1;
      for (let gx = 0; gx < canvas.width; gx += 32) {
        ctx.beginPath();
        ctx.moveTo(gx, 0);
        ctx.lineTo(gx, canvas.height);
        ctx.stroke();
      }

      // Raw detected object boundary.
      ctx.strokeStyle = "rgba(255,255,255,0.45)";
      ctx.lineWidth = 2;
      ctx.setLineDash([]);
      ctx.strokeRect(box.x, box.y, box.w, box.h);

      // Predictive overlay: extrapolate forward using latency * velocity.
      const predictedX = box.x + latencyMs * 0.45 * (speed / 2);
      ctx.strokeStyle = accent;
      ctx.setLineDash([6, 4]);
      ctx.strokeRect(predictedX, box.y, box.w, box.h);
      ctx.setLineDash([]);
      ctx.fillStyle = accent;
      ctx.font = "10px ui-monospace, monospace";
      ctx.fillText(`PREDICTED POS (+${latencyMs}ms)`, predictedX + 2, box.y - 8);

      raf = requestAnimationFrame(render);
    };

    raf = requestAnimationFrame(render);
    return () => cancelAnimationFrame(raf);
  }, [latencyMs, accent]);

  return <canvas ref={canvasRef} width={640} height={360} className="camera-canvas" />;
}
