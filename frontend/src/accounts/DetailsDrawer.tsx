import { useEffect, useRef, type ReactNode } from "react";
import { api } from "../api/client.ts";
import type { Account } from "../api/types.ts";
import { useResource } from "../hooks/useResource.ts";
import { countryName, flag, formatCount, formatDate, formatMoney } from "../lib/format.ts";
import { METRICS, type MetricKey } from "../lib/metrics.ts";
import { Avatar } from "../ui/Avatar.tsx";
import { Icon, type IconName } from "../ui/Icon.tsx";
import { Banner, Button, IconButton, PlanChip, Skeleton, StatusChip } from "../ui/primitives.tsx";

const HEAD = { active: "from-[#c9f2c0] to-[#e9fbd9]", trial: "from-[#ffe39a] to-[#fff4d6]", suspended: "from-[#ffcaca] to-[#ffeaea]" } as const;

/** Side drawer on desktop, full screen on phones. Arrow buttons step through the accounts on the page. */
export function DetailsDrawer({ id, rows, onClose, onOpen, onSettings }: {
  id: number; rows: Account[]; onClose: () => void; onOpen: (id: number) => void; onSettings: () => void;
}) {
  const key = String(id);
  const res = useResource(key, (s) => api.account(id, s), { pollMs: 15_000 });
  const at = rows.findIndex((r) => r.id === id);
  const fresh = res.dataKey === key ? res.data : undefined;
  const a = fresh ?? (at >= 0 ? rows[at] : undefined);
  const failed = res.status === "error";
  const missing = failed && res.error?.status === 404;

  const dialog = useRef<HTMLDialogElement>(null);
  const opened = useRef(id);
  opened.current = id;
  useEffect(() => {
    const d = dialog.current!;
    if (!d.open) d.showModal();
    d.querySelector<HTMLElement>("#details-title")?.focus();
    return () => {
      // Back to the row of the account last shown, not just the one first clicked.
      requestAnimationFrame(() => document.querySelector<HTMLElement>(`[data-open-account="${opened.current}"]`)?.focus({ preventScroll: true }));
    };
  }, []);

  return (
    <dialog ref={dialog} className="drawer" aria-labelledby="details-title"
      onCancel={(e) => { e.preventDefault(); onClose(); }} onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="flex h-full flex-col overflow-hidden bg-tile sm:m-3 sm:h-[calc(100%-1.5rem)] sm:rounded-3xl sm:shadow-float">
        <div className={`shrink-0 p-4 transition-colors ${a && !missing ? `bg-gradient-to-br ${HEAD[a.status]}` : "bg-card"}`}>
          <div className="flex items-center justify-between">
            <div className="flex">
              <IconButton icon="up" label="Previous account" disabled={at <= 0} onClick={() => onOpen(rows[at - 1].id)} />
              <IconButton icon="down" label="Next account" disabled={at < 0 || at >= rows.length - 1} onClick={() => onOpen(rows[at + 1].id)} />
            </div>
            <IconButton icon="close" label="Close" onClick={onClose} />
          </div>
          {a && !missing ? (
            <div key={id} className="rise flex items-center gap-4 px-1 pb-2 pt-1">
              <span className="group pop"><Avatar id={a.id} status={a.status} size={76} /></span>
              <div className="min-w-0">
                <h2 id="details-title" tabIndex={-1} className="text-2xl font-bold leading-tight tracking-tight">{a.company}</h2>
                <p className="truncate text-sm text-ink/75">{a.name}</p>
                <div className="mt-2 flex flex-wrap gap-1.5 [&>span]:bg-white/85"><StatusChip status={a.status} /><PlanChip plan={a.plan} /></div>
              </div>
            </div>
          ) : (
            <h2 id="details-title" tabIndex={-1} className="px-1 pb-2 text-xl font-bold">
              {missing ? "We couldn’t find this account" : failed ? "We couldn’t load this account" : "Opening account…"}
            </h2>
          )}
        </div>

        <div className="flex-1 overflow-y-auto p-4">
          {missing ? (
            <p className="text-sm text-muted">It may have been removed, or the link may be wrong.</p>
          ) : !a ? (
            failed ? <Button variant="primary" icon="refresh" onClick={res.refetch}>Try again</Button>
              : <div className="grid gap-3" aria-busy="true"><Skeleton className="h-24" /><Skeleton className="h-24" /></div>
          ) : (
            <div className="grid gap-4">
              {failed && (
                <Banner tone="warning" role="status" actions={<Button variant="ghost" onClick={res.refetch}>Try again</Button>}>
                  Couldn’t refresh. These are the last details we have.
                </Banner>
              )}
              <section aria-label="This month">
                <h3 className="mb-2 text-sm font-semibold text-muted">This month</h3>
                <div className="grid grid-cols-2 gap-2">
                  <Stat metric="minutes" value={`${formatCount(a.current_month_minutes)} min`} wide />
                  <Stat metric="sms" value={formatCount(a.current_month_sms)} />
                  <Stat metric="cost_cents" value={formatMoney(a.cost_cents)} />
                </div>
              </section>
              <dl className="grid gap-1 rounded-3xl bg-card p-2">
                <Fact icon="mail" label="Email">{a.email}</Fact>
                <Fact icon="globe" label="Country">{flag(a.country)} {countryName(a.country)}</Fact>
                <Fact icon="signup" label="Joined">{formatDate(a.signup_date)}</Fact>
                <Fact icon="clock" label="Last active">{formatDate(a.last_active)}</Fact>
                <Fact icon="info" label="Account ID">{a.id}</Fact>
              </dl>
            </div>
          )}
        </div>

        <div className="shrink-0 border-t border-line p-4">
          {missing || !a ? <Button className="w-full" icon="back" onClick={onClose}>Back to accounts</Button>
            : <Button variant="primary" icon="settings" className="min-h-12 w-full" onClick={onSettings}>Edit settings</Button>}
        </div>
      </div>
    </dialog>
  );
}

function Stat({ metric, value, wide }: { metric: MetricKey; value: string; wide?: boolean }) {
  const m = METRICS[metric];
  return (
    <div className={`rounded-3xl p-4 ${wide ? "col-span-2" : ""}`} style={{ background: `color-mix(in srgb, ${m.color} 15%, white)` }}>
      <p className="flex items-center gap-2 text-sm font-semibold">
        <span className="grid size-7 place-items-center rounded-lg text-white" style={{ background: m.color }}><Icon name={m.icon} size={16} /></span>{m.label}
      </p>
      <p className={`tnum mt-2 font-bold tracking-tight ${wide ? "text-3xl" : "text-xl"}`}>{value}</p>
    </div>
  );
}

function Fact({ icon, label, children }: { icon: IconName; label: string; children: ReactNode }) {
  return (
    <div className="flex items-center gap-3 rounded-2xl px-2 py-2 text-sm">
      <Icon name={icon} size={18} className="text-muted" />
      <dt className="text-muted">{label}</dt>
      <dd className="ml-auto min-w-0 break-words text-right font-semibold [overflow-wrap:anywhere]">{children}</dd>
    </div>
  );
}
