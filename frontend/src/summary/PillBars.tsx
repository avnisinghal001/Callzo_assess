import { useState } from "react";
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useReducedMotion } from "../hooks/ui.ts";
import type { Bucket, Grain } from "../lib/buckets.ts";
import { METRICS, type MetricKey } from "../lib/metrics.ts";

interface ShapeProps { x?: number; y?: number; width?: number; height?: number; index?: number; payload?: Bucket }

/** Pill bars on a track, after BoardUI's earnings card. Recharts is the only chart dependency. */
export default function PillBars({ buckets, metric, grain, onActive, onPick }: {
  buckets: Bucket[]; metric: MetricKey; grain: Grain;
  onActive: (b: Bucket | null) => void; onPick: (b: Bucket) => void;
}) {
  const [active, setActive] = useState<number | null>(null);
  const reduced = useReducedMotion();
  const m = METRICS[metric];
  const zoomable = grain !== "day";
  // Over many months, label quarters only and show the year in place of January.
  const quarters = grain === "month" && buckets.length > 14;
  const ticks = quarters ? buckets.filter((b) => ["01", "04", "07", "10"].includes(b.from.slice(5, 7))).map((b) => b.from) : undefined;
  const radius = buckets.length > 20 ? 5 : 9;

  const focus = (i: number | null) => {
    setActive(i);
    onActive(i === null ? null : buckets[i] ?? null);
  };
  const indexOf = (s: { activeTooltipIndex?: unknown }) => {
    const i = Number(s.activeTooltipIndex);
    return s.activeTooltipIndex != null && Number.isInteger(i) && buckets[i] ? i : null;
  };

  const shape = (p: ShapeProps) => {
    const { x = 0, y = 0, width = 0, height = 0, index = 0, payload } = p;
    if (height <= 0) return <g />;
    const r = Math.min(radius, width / 2, height / 2);
    const dim = active !== null && active !== index;
    return (
      <rect x={x} y={y} width={width} height={height} rx={r} fill={m.color}
        style={{ opacity: dim ? 0.35 : payload?.partial && active !== index ? 0.45 : 1, transition: "opacity 160ms, fill 260ms" }} />
    );
  };

  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={buckets} margin={{ top: 4, right: 4, bottom: 0, left: 0 }} barCategoryGap={buckets.length > 20 ? "22%" : "26%"}
        onMouseMove={(s) => focus(indexOf(s))} onMouseLeave={() => focus(null)}
        onClick={(s) => { const i = indexOf(s); if (i !== null && zoomable) onPick(buckets[i]); }}
        style={{ cursor: zoomable ? "zoom-in" : "default" }}>
        <YAxis width={40} tickCount={4} tickFormatter={m.short} tickLine={false} axisLine={false}
          tick={{ fontSize: 12, fill: "var(--color-muted)" }} />
        <XAxis dataKey="from" ticks={ticks} interval={ticks ? "preserveEnd" : "preserveStartEnd"}
          tickFormatter={(v: string) => (quarters && v.slice(5, 7) === "01" ? v.slice(0, 4) : buckets.find((b) => b.from === v)?.label ?? "")} tickLine={false} axisLine={false}
          tickMargin={10} minTickGap={18} tick={{ fontSize: 12, fill: "var(--color-muted)" }} />
        <Tooltip cursor={false} isAnimationActive={!reduced} animationDuration={140}
          content={({ active: on, payload }) => {
            const b = payload?.[0]?.payload as Bucket | undefined;
            if (!on || !b) return null;
            return (
              <div className="rounded-2xl bg-ink px-3.5 py-2.5 text-white shadow-float">
                <p className="tnum text-lg font-bold leading-tight">{m.format(b[metric])}</p>
                <p className="text-xs text-white/75">{b.title}{b.partial ? ` · ${b.days} ${b.days === 1 ? "day" : "days"} only` : ""}</p>
                {zoomable && <p className="mt-1 text-xs font-semibold text-white/90">Click to zoom in</p>}
              </div>
            );
          }} />
        <Bar dataKey={metric} shape={shape} maxBarSize={44} background={{ fill: "var(--color-track)", radius }}
          isAnimationActive={!reduced} animationDuration={420} animationEasing="ease-out" />
      </BarChart>
    </ResponsiveContainer>
  );
}
