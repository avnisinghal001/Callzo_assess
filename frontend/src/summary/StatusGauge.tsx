import { api } from "../api/client.ts";
import type { Status } from "../api/types.ts";
import { useCountUp } from "../hooks/ui.ts";
import { useResource } from "../hooks/useResource.ts";
import { formatCount, STATUS_LABEL } from "../lib/format.ts";
import { accountsParams, type ListQuery } from "../lib/query.ts";
import { Icon } from "../ui/Icon.tsx";
import { Button, Card, Skeleton, STATUS_ICON } from "../ui/primitives.tsx";

const STATUSES: Status[] = ["active", "trial", "suspended"];
const R = 84;
const ARC = Math.PI * R;
const GAP = 24; // round caps add the stroke width, so leave room for them
const FULL_PATH = `M${110 - R} 104A${R} ${R} 0 0 1 ${110 + R} 104`;

/**
 * How many accounts are in each status, and a one-click filter for the table below.
 * The API has no counts endpoint, so this reads `total` from three one-row requests that use the
 * same search, plan, country and dates as the table. The two always agree.
 */
export function StatusGauge({ query, active, onPick }: { query: ListQuery; active: boolean; onPick: (s: Status | "") => void }) {
  const base = { ...accountsParams({ ...query, page: 1, sort: "id", dir: "asc", status: "" }), page_size: 1 };
  const key = JSON.stringify(base);
  const res = useResource(key, async (s) => {
    const pages = await Promise.all(STATUSES.map((status) => api.accounts({ ...base, status }, s)));
    return pages.map((p) => p.total);
  }, { pollMs: active ? 60_000 : undefined });

  const counts = res.data;
  const total = counts?.reduce((a, b) => a + b, 0) ?? 0;
  const picked = STATUSES.indexOf(query.status as Status);
  const shown = useCountUp(counts ? (picked >= 0 ? counts[picked] : total) : 0);
  const failed = res.status === "error";
  const switching = res.dataKey !== undefined && res.dataKey !== key;
  const toggle = (s: Status) => onPick(query.status === s ? "" : s);

  // Each non-empty status gets a visible minimum so a small slice can still be clicked.
  const present = counts?.filter((c) => c > 0).length ?? 0;
  const usable = ARC - Math.max(0, present - 1) * GAP;
  let at = 0;
  const arcs = STATUSES.map((s, i) => {
    const n = counts?.[i] ?? 0;
    if (!n) return null;
    const len = Math.max(3, (n / total) * usable);
    const start = at;
    at += len + GAP;
    return { s, len, start };
  });

  return (
    <Card className="flex flex-col p-4 sm:p-6" aria-labelledby="status-title">
      <h2 id="status-title" className="text-sm font-semibold text-muted">How are accounts doing?</h2>

      {failed && !counts ? (
        <div role="alert" className="grid flex-1 place-content-center justify-items-center gap-2 py-8 text-center">
          <p className="font-semibold">We couldn’t count accounts</p>
          <Button icon="refresh" onClick={res.refetch}>Try again</Button>
        </div>
      ) : !counts ? (
        <div className="grid flex-1 gap-3 pt-4" aria-busy="true"><Skeleton className="h-32" /><Skeleton className="h-12" /><Skeleton className="h-12" /></div>
      ) : (
        <div className={`flex flex-1 flex-col transition-opacity ${switching && !failed ? "opacity-50" : ""}`}>
          <div className="relative mx-auto my-auto w-full max-w-[250px]">
            <svg viewBox="0 0 220 120" className="block w-full" aria-hidden="true">
              <path d={FULL_PATH} fill="none" stroke="var(--color-track)" strokeWidth="22" strokeLinecap="round" />
              {arcs.map((a) => a && (
                <path key={a.s} d={FULL_PATH} fill="none" stroke={`var(--color-${a.s})`} strokeWidth={query.status === a.s ? 27 : 22} strokeLinecap="round"
                  strokeDasharray={`${a.len} ${ARC * 2}`} strokeDashoffset={-a.start} onClick={() => toggle(a.s)} className="cursor-pointer"
                  style={{ opacity: query.status && query.status !== a.s ? 0.25 : 1, transition: "stroke-dasharray 500ms var(--ease-smooth), stroke-dashoffset 500ms var(--ease-smooth), stroke-width 250ms var(--ease-spring), opacity 200ms" }} />
              ))}
            </svg>
            <div className="pointer-events-none absolute inset-x-0 bottom-1 text-center">
              <p className="tnum text-3xl font-bold tracking-tight">{formatCount(Math.round(shown))}</p>
              <p className="text-xs font-medium text-muted">{picked >= 0 ? STATUS_LABEL[STATUSES[picked]].toLowerCase() : "accounts"}</p>
            </div>
          </div>

          <div role="group" aria-label="Filter accounts by status" className="mt-4 grid gap-2">
            {STATUSES.map((s, i) => {
              const on = query.status === s;
              return (
                <button key={s} type="button" aria-pressed={on} onClick={() => toggle(s)}
                  className={`group flex min-h-11 items-center gap-2.5 rounded-2xl px-3 text-sm font-semibold transition-[background,transform,box-shadow] duration-200 hover:translate-x-1 ${on ? "text-ink shadow-tile" : "bg-tile"}`}
                  style={on ? { background: `var(--color-${s}-soft)` } : undefined}>
                  <span className="face grid size-7 place-items-center rounded-lg" style={{ background: `var(--color-${s}-soft)`, color: `var(--color-${s}-ink)` }}>
                    <Icon name={STATUS_ICON[s]} size={17} strokeWidth={2.2} />
                  </span>
                  {STATUS_LABEL[s]}
                  <span className="tnum ml-auto">{formatCount(counts[i])}</span>
                  <Icon name={on ? "close" : "chevRight"} size={15} className={on ? "text-ink" : "text-faint"} />
                </button>
              );
            })}
          </div>
          {failed && <button type="button" onClick={res.refetch} className="mt-2 min-h-9 rounded-lg text-xs font-semibold text-trial-ink underline">Counts may be out of date. Try again</button>}
        </div>
      )}
    </Card>
  );
}
