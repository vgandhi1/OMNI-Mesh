import { Line, LineChart, ResponsiveContainer, Tooltip, YAxis } from "recharts";

import { useCockpitStore } from "../store/cockpitStore";

/** Live 30Hz metric: big readout + a sparkline of the bounded history. */
export function MetricGauge() {
  const history = useCockpitStore((s) => s.history);
  const gaugeLabel = useCockpitStore((s) => s.gaugeLabel);
  const accent = useCockpitStore((s) => s.accent);
  const latest = useCockpitStore((s) => s.latest);

  const data = history.map((point, i) => ({ i, value: point.value }));

  return (
    <div className="panel">
      <div className="panel-label">{gaugeLabel}</div>
      <div className="metric-value" style={{ color: accent }}>
        {latest ? latest.metric_value.toFixed(3) : "—"}
        <span className="metric-samples">
          {latest ? ` · ${latest.sample_count} samples/frame` : ""}
        </span>
      </div>
      <ResponsiveContainer width="100%" height={150}>
        <LineChart data={data} margin={{ top: 8, right: 4, bottom: 0, left: 4 }}>
          <YAxis hide domain={["auto", "auto"]} />
          <Tooltip
            contentStyle={{
              background: "#0b1220",
              border: "1px solid #1e293b",
              borderRadius: 8,
              color: "#e2e8f0",
              fontFamily: "ui-monospace, monospace",
              fontSize: 12,
            }}
            labelFormatter={() => ""}
            formatter={(value: number | string) => [Number(value).toFixed(3), "value"]}
          />
          <Line
            type="monotone"
            dataKey="value"
            stroke={accent}
            strokeWidth={2}
            dot={false}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
