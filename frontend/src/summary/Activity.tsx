import { lazy, Suspense, useMemo, useState, type ReactNode } from "react";
import { api } from "../api/client.ts";
import { useCountUp } from "../hooks/ui.ts";
import { useResource } from "../hooks/useResource.ts";
import { bucketize, type Bucket } from "../lib/buckets.ts";
import { formatDate, formatTime } from "../lib/format.ts";
import { METRICS, METRIC_KEYS, type MetricKey } from "../lib/metrics.ts";
import { Icon } from "../ui/Icon.tsx";
import { Button, Card, Skeleton } from "../ui/primitives.tsx";

const PillBars = lazy(() => import("./PillBars.tsx"));

/** The summary endpoint fails about 1 call in 5 on purpose: try once more quietly, then ask the person. */
async function fetchSummary(from: string, to: string, signal: AbortSignal) {
  const p = { date_from: from || undefined, date_to: to || undefined };
  try {
    return await api.summary(p, signal);
  } catch (e) {
    if (signal.aborted) throw e;
    return api.summary(p, signal);
  }
}

/** Four tiles and one chart from a single request. `side` sits beside the chart and has its own data. */
export function Activity({ from, to, metric, onMetric, onZoom, active, side }: {
  from: string; to: string; metric: MetricKey; onMetric: (m: MetricKey) => void;
  onZoom: (from: string, to: string) => void; active: boolean; side: ReactNode;
}) {
  const key = `${from}|${to}`;
  const res = useResource(key, (s) => fetchSummary(from, to, s), { pollMs: active ? 60_000 : undefined });
  const series = res.data?.series;
  const { grain, buckets } = useMemo(() => bucketize(series ?? []), [series]);
  const [hover, setHover] = useState<Bucket | null>(null);

  const total = useMemo(() => buckets.reduce((n, b) => n + b[metric], 0), [buckets, metric]);
  const m = METRICS[metric];
  const failed = res.status === "error";
  const switching = res.dataKey !== undefined && res.dataKey !== key;
  const rolling = useCountUp(total);
  // Exact at once while hovering, so it never disagrees with the tooltip.
  const shown = hover ? hover[metric] : rolling;
  const span = buckets.length ? `${formatDate(buckets[0].from)} – ${formatDate(buckets[buckets.length - 1].to)}` : "";

  return (
    <>
      <div role="group" aria-label="Choose what the chart shows" className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {METRIC_KEYS.map((k) => (
          <MetricTile key={k} metric={k} on={k === metric} buckets={buckets} loading={!series && !failed} unavailable={!series && failed} onClick={() => onMetric(k)} />
        ))}
      </div>

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-[minmax(0,1fr)_340px]">
        <Card className="flex min-w-0 flex-col p-4 sm:p-6" aria-labelledby="chart-title">
          <div className="flex min-h-[68px] flex-wrap items-start justify-between gap-2">
            <div>
              <h2 id="chart-title" className="flex items-center gap-2 text-sm font-semibold text-muted">
                <span className="size-2.5 rounded-full transition-colors" style={{ background: m.color }} aria-hidden="true" />{m.label}
              </h2>
              {series && buckets.length > 0 && (
                <>
                  <p className="tnum text-3xl font-bold tracking-tight">{m.format(Math.round(shown))}</p>
                  <p className="text-sm text-muted">{hover ? hover.title : span}</p>
                </>
              )}
            </div>
            {series && grain !== "day" && buckets.length > 0 && (
              <p className="hidden items-center gap-1.5 text-xs font-medium text-muted sm:flex"><Icon name="zoom" size={15} />Click a bar to zoom in</p>
            )}
          </div>

          <div className="mt-4 h-[260px] sm:h-[280px]" aria-busy={res.status === "loading" || switching}>
            {failed && !series ? (
              <div role="alert" className="grid h-full place-content-center justify-items-center gap-2 rounded-2xl bg-tile px-4 text-center">
                <span className="grid size-12 place-items-center rounded-2xl bg-trial-soft text-trial-ink"><Icon name="moon" size={24} /></span>
                <p className="font-semibold">We couldn’t load activity right now</p>
                <p className="text-sm text-muted">Your accounts below are still available.</p>
                <Button variant="primary" icon="refresh" className="mt-1" onClick={res.refetch}>Try again</Button>
              </div>
            ) : !series ? (
              <Skeleton className="h-full w-full" />
            ) : buckets.length === 0 ? (
              <div className="grid h-full place-content-center justify-items-center gap-2 rounded-2xl bg-tile text-center">
                <Icon name="moon" size={26} className="text-faint" />
                <p className="text-sm text-muted">No activity in this period.</p>
              </div>
            ) : (
              <div className={`h-full transition-opacity ${switching && !failed ? "opacity-50" : ""}`}>
                <Suspense fallback={<Skeleton className="h-full w-full" />}>
                  <PillBars buckets={buckets} metric={metric} grain={grain} onActive={setHover}
                    onPick={(b) => { setHover(null); onZoom(b.from, b.to); }} />
                </Suspense>
                <table className="sr-only">
                  <caption>{m.label} per {grain}, {span}</caption>
                  <thead><tr><th scope="col">Period</th><th scope="col">{m.label}</th></tr></thead>
                  <tbody>{buckets.map((b) => <tr key={b.from}><th scope="row">{b.title}</th><td>{m.format(b[metric])}</td></tr>)}</tbody>
                </table>
              </div>
            )}
          </div>

          {failed && series && (
            <div role="status" className="rise mt-3 flex flex-wrap items-center justify-between gap-2 rounded-2xl bg-trial-soft px-3 py-1.5 text-sm text-trial-ink">
              <span className="flex items-center gap-2"><Icon name="warning" size={17} />
                {switching ? "We couldn’t load that period. Still showing the previous one." : `Couldn’t refresh. Showing data from ${res.updatedAt ? formatTime(res.updatedAt) : "earlier"}.`}
              </span>
              <Button variant="ghost" icon="refresh" className="text-trial-ink" onClick={res.refetch}>Try again</Button>
            </div>
          )}
        </Card>
        {side}
      </div>
    </>
  );
}

function MetricTile({ metric, on, buckets, loading, unavailable, onClick }: {
  metric: MetricKey; on: boolean; buckets: Bucket[]; loading: boolean; unavailable: boolean; onClick: () => void;
}) {
  const m = METRICS[metric];
  const total = useCountUp(buckets.reduce((n, b) => n + b[metric], 0));
  return (
    <button type="button" aria-pressed={on} onClick={onClick}
      className={`group relative isolate min-w-0 overflow-hidden rounded-3xl p-4 text-left transition-[background,color,transform,box-shadow] duration-300 ease-spring hover:-translate-y-1 active:scale-[0.98] sm:p-5 ${on ? "text-white shadow-float" : "text-ink"}`}
      style={{ background: on ? `color-mix(in srgb, ${m.color} 88%, black)` : `color-mix(in srgb, ${m.color} 15%, white)` }}>
      <Spark buckets={buckets} metric={metric} color={on ? "#ffffff" : m.color} />
      <span className="face grid size-10 place-items-center rounded-2xl text-white"
        style={{ background: on ? "rgb(255 255 255 / 0.22)" : m.color }}>
        <Icon name={m.icon} size={21} />
      </span>
      <span className="mt-3 block text-sm font-semibold">{m.label}</span>
      <span className="tnum block text-2xl font-bold tracking-tight sm:text-3xl">
        {loading ? <Skeleton className="mt-1 h-8 w-24" /> : unavailable ? <span aria-label="Not available">–</span> : <>{m.short(Math.round(total))}{metric === "minutes" && <span className="ml-1 text-base font-semibold">min</span>}</>}
      </span>
    </button>
  );
}

/** Background silhouette of the latest dozen whole buckets. Decorative; the chart carries the values. */
function Spark({ buckets, metric, color }: { buckets: Bucket[]; metric: MetricKey; color: string }) {
  const whole = buckets.filter((b) => !b.partial).slice(-12).map((b) => b[metric]);
  if (whole.length < 3) return null;
  const min = Math.min(...whole), max = Math.max(...whole);
  const pts = whole.map((v, i) => [(i / (whole.length - 1)) * 100, 36 - ((v - min) / (max - min || 1)) * 28]);
  // Horizontal control points: a soft wave that never overshoots the values.
  const line = pts.map(([x, y], i) => {
    if (!i) return `M${x} ${y}`;
    const mid = (pts[i - 1][0] + x) / 2;
    return `C${mid} ${pts[i - 1][1]} ${mid} ${y} ${x} ${y}`;
  }).join("");
  return (
    <svg viewBox="0 0 100 40" preserveAspectRatio="none" aria-hidden="true" className="absolute bottom-0 right-0 -z-10 h-3/5 w-3/5 opacity-40 [mask-image:linear-gradient(to_right,transparent,black_45%)]">
      <path d={`${line}L100 40L0 40Z`} fill={color} opacity="0.5" />
      <path d={line} fill="none" stroke={color} strokeWidth="1.5" vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
    </svg>
  );
}
