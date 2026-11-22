import { useEffect, useRef, useState } from "react";
import { api } from "../api/client.ts";
import type { Account, SortField } from "../api/types.ts";
import { useDebounced, useResource } from "../hooks/useResource.ts";
import type { UrlPatch } from "../hooks/useUrlState.ts";
import { COUNTRIES, countryName, flag, formatCount, formatTime, PLAN_LABEL, STATUS_LABEL } from "../lib/format.ts";
import { mergeRefresh } from "../lib/mergeRefresh.ts";
import { accountsParams, hasActiveFilters, PAGE_SIZE, type ListQuery } from "../lib/query.ts";
import { countOffPage, toggle, togglePage, type Selection } from "../lib/selection.ts";
import { Icon } from "../ui/Icon.tsx";
import { Banner, Button, PillSelect, Skeleton } from "../ui/primitives.tsx";
import { AccountsTable } from "./AccountsTable.tsx";
import { DetailsDrawer } from "./DetailsDrawer.tsx";
import { Pagination } from "./Pagination.tsx";

interface Shown { key: string; rows: Account[]; total: number }

/** Everything the API can sort by, in words. Column headings cover the common ones. */
const SORTS: [SortField, string, string][] = [
  ["id", "Oldest ID first", "Newest ID first"],
  ["company", "Business A–Z", "Business Z–A"],
  ["name", "Contact A–Z", "Contact Z–A"],
  ["current_month_minutes", "Least calling", "Most calling"],
  ["current_month_sms", "Fewest texts", "Most texts"],
  ["cost_cents", "Lowest spend", "Highest spend"],
  ["signup_date", "Joined first", "Joined last"],
  ["last_active", "Quiet the longest", "Recently active"],
  ["plan", "Plan A–Z", "Plan Z–A"],
  ["status", "Status A–Z", "Status Z–A"],
  ["country", "Country A–Z", "Country Z–A"],
];

export function AccountsPage({ query, update, selection, setSelection, openId, active, onSettings }: {
  query: ListQuery;
  update: (p: UrlPatch, o?: { replace?: boolean }) => void;
  selection: Selection;
  setSelection: (fn: (s: Selection) => Selection) => void;
  openId: number | null;
  active: boolean;
  onSettings: (id: number) => void;
}) {
  const params = accountsParams(query);
  const key = JSON.stringify(params);
  const res = useResource(key, (s) => api.accounts(params, s), { pollMs: active ? 15_000 : undefined });

  // ---- what is on screen: stable between polls, replaced on any user-driven change ----
  const [shown, setShown] = useState<Shown | null>(null);
  const shownRef = useRef<Shown | null>(null);
  const [orderChanged, setOrderChanged] = useState(false);
  const show = (next: Shown) => { shownRef.current = next; setShown(next); };
  useEffect(() => {
    const d = res.data;
    if (!d || !res.dataKey) return;
    const prev = shownRef.current;
    if (!prev || prev.key !== res.dataKey) {
      setOrderChanged(false);
      show({ key: res.dataKey, rows: d.data, total: d.total });
    } else {
      const m = mergeRefresh(prev.rows, d.data);
      setOrderChanged(m.orderChanged);
      show({ ...prev, rows: m.rows, total: d.total });
    }
  }, [res.data, res.dataKey]);
  const applyFresh = () => {
    if (res.data && res.dataKey) show({ key: res.dataKey, rows: res.data.data, total: res.data.total });
    setOrderChanged(false);
  };

  // ---- search: type freely, push to the URL after a pause ----
  const [text, setText] = useState(query.q);
  const pushed = useRef(query.q);
  const debounced = useDebounced(text, 300);
  useEffect(() => {
    if (debounced !== pushed.current) { pushed.current = debounced; update({ q: debounced, page: undefined }, { replace: true }); }
  }, [debounced, update]);
  useEffect(() => { if (query.q !== pushed.current) { pushed.current = query.q; setText(query.q); } }, [query.q]);

  const filter = (k: string, v: string) => update({ [k]: v, page: undefined });
  const clearFilters = () => {
    pushed.current = "";
    setText("");
    update({ q: undefined, plan: undefined, status: undefined, country: undefined, page: undefined });
  };
  const sortBy = (f: SortField, dir: "asc" | "desc") => update({ sort: f === "id" ? undefined : f, dir: dir === "desc" ? "desc" : undefined, page: undefined });
  const open = (id: number) => update({ account: id }, { replace: openId !== null });
  const close = () => update({ account: undefined });

  const top = useRef<HTMLElement>(null);
  const goToPage = (p: number) => {
    update({ page: p === 1 ? undefined : p });
    top.current?.scrollIntoView({ block: "start" });
  };

  const rows = shown?.rows ?? [];
  const pageIds = rows.map((r) => r.id);
  const off = countOffPage(selection, pageIds);
  const failed = res.status === "error";
  const switching = Boolean(shown) && shown!.key !== key;
  const filtered = hasActiveFilters(query);

  return (
    <section ref={top} aria-labelledby="accounts-title" className="scroll-mt-3 rounded-3xl border border-line bg-tile">
      <div className="grid gap-4 p-4 sm:p-6 sm:pb-4">
        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
          <h2 id="accounts-title" className="text-xl font-bold tracking-tight">
            <span className="tnum">{shown ? formatCount(shown.total) : "…"}</span> {shown?.total === 1 ? "account" : "accounts"}
          </h2>
          <p className="flex items-center gap-2 text-sm text-muted">
            <span className={`size-2 rounded-full ${failed ? "bg-trial" : "live-dot bg-active"}`} aria-hidden="true" />
            {failed ? "Reconnecting" : "Live"}{res.updatedAt ? ` · ${formatTime(res.updatedAt)}` : ""}
          </p>
        </div>

        <form role="search" onSubmit={(e) => e.preventDefault()} className="grid grid-cols-2 gap-2 lg:grid-cols-[minmax(0,1fr)_repeat(3,auto)]">
          <label className="relative col-span-2 block lg:col-span-1">
            <span className="sr-only">Search by name, email or business</span>
            <Icon name="search" className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-muted" />
            <input type="search" value={text} onChange={(e) => setText(e.target.value)} placeholder="Find a business, person or email"
              className="min-h-11 w-full rounded-xl bg-card pl-10 pr-3 text-base font-medium placeholder:text-muted sm:text-sm" />
          </label>
          <PillSelect label="Plan" icon="sparkles" active={Boolean(query.plan)} value={query.plan} onChange={(e) => filter("plan", e.target.value)}>
            <option value="">Any plan</option>
            {Object.entries(PLAN_LABEL).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </PillSelect>
          <PillSelect label="Country" icon="globe" active={Boolean(query.country)} value={query.country} onChange={(e) => filter("country", e.target.value)}>
            <option value="">Any country</option>
            {COUNTRIES.map((c) => <option key={c} value={c}>{flag(c)} {countryName(c)}</option>)}
          </PillSelect>
          <PillSelect label="Sort by" icon="sort" className="col-span-2 lg:col-span-1" value={`${query.sort}:${query.dir}`}
            onChange={(e) => { const [f, d] = e.target.value.split(":"); sortBy(f as SortField, d as "asc" | "desc"); }}>
            {SORTS.map(([f, asc, desc]) => [
              <option key={`${f}a`} value={`${f}:asc`}>{asc}</option>,
              <option key={`${f}d`} value={`${f}:desc`}>{desc}</option>,
            ])}
          </PillSelect>
        </form>

        {filtered && (
          <div className="flex flex-wrap gap-2">
            {query.q.trim() && <Tag label={`“${query.q.trim()}”`} onRemove={() => { pushed.current = ""; setText(""); update({ q: undefined, page: undefined }); }} />}
            {query.status && <Tag label={STATUS_LABEL[query.status as keyof typeof STATUS_LABEL]} onRemove={() => filter("status", "")} />}
            {query.plan && <Tag label={PLAN_LABEL[query.plan as keyof typeof PLAN_LABEL]} onRemove={() => filter("plan", "")} />}
            {query.country && <Tag label={countryName(query.country)} onRemove={() => filter("country", "")} />}
          </div>
        )}

        {failed && shown && (
          <Banner tone="warning" role="status" actions={<Button variant="ghost" icon="refresh" onClick={res.refetch}>Try again</Button>}>
            {switching ? "We couldn’t load those results. Still showing the previous ones." : `Couldn’t refresh. Showing data from ${res.updatedAt ? formatTime(res.updatedAt) : "earlier"}.`}
          </Banner>
        )}
      </div>

      {!shown && !failed ? (
        <div className="grid gap-2 px-4 pb-6 sm:px-6" aria-busy="true"><span className="sr-only">Loading accounts</span>
          {Array.from({ length: 8 }, (_, i) => <Skeleton key={i} className="h-14" />)}
        </div>
      ) : !shown ? (
        <Empty icon="moon" title="We couldn’t load accounts right now" text="Nothing has been lost. Give it another go." role="alert">
          <Button variant="primary" icon="refresh" onClick={res.refetch}>Try again</Button>
        </Empty>
      ) : rows.length === 0 && !switching ? (
        <Empty icon="search" title="No accounts found"
          text={shown.total > 0 ? "This page is past the last result." : filtered ? "Nothing matches these filters in this period." : "No businesses joined in this period."}>
          {shown.total > 0 && <Button variant="primary" onClick={() => goToPage(1)}>Go to the first page</Button>}
          {filtered && <Button variant="primary" onClick={clearFilters}>Clear filters</Button>}
          {(query.from || query.to) && <Button onClick={() => update({ from: undefined, to: undefined, page: undefined })}>Show all time</Button>}
        </Empty>
      ) : (
        <>
          <AccountsTable rows={rows} selection={selection} sort={query.sort} dir={query.dir} busy={switching && !failed}
            onSort={(f) => sortBy(f, query.sort === f && query.dir === "asc" ? "desc" : "asc")}
            onToggle={(id) => setSelection((s) => toggle(s, id))} onTogglePage={() => setSelection((s) => togglePage(s, pageIds))} onOpen={open} />
          <Pagination page={query.page} pageSize={PAGE_SIZE} total={shown.total} onPage={goToPage} />
        </>
      )}

      {/* Floating dock: appears only when it has something to say, and never moves the rows. */}
      <div role="status" className="pointer-events-none fixed inset-x-0 bottom-4 z-20 flex flex-col items-center justify-center gap-2 px-4 sm:flex-row">
        {active && orderChanged && !switching && (
          <div className="rise pointer-events-auto flex items-center gap-2 rounded-2xl bg-tile py-1.5 pl-4 pr-1.5 text-sm shadow-float ring-1 ring-line">
            <Icon name="sort" size={17} className="text-primary" /><span className="font-medium">The order has changed</span>
            <Button variant="ghost" className="min-h-9 text-primary" onClick={applyFresh}>Update</Button>
          </div>
        )}
        {active && selection.size > 0 && (
          <div className="rise pointer-events-auto flex items-center gap-2 rounded-2xl bg-ink py-1.5 pl-2 pr-1.5 text-sm text-white shadow-float">
            <span key={selection.size} className="tnum pop grid h-8 min-w-8 place-items-center rounded-xl bg-primary px-2 font-bold">{selection.size}</span>
            <span className="font-medium">selected{off > 0 ? `, ${off} not on this page` : ""}</span>
            <Button variant="ghost" className="min-h-9 text-white hover:bg-white/15 hover:text-white" onClick={() => setSelection(() => new Set())}>Clear</Button>
          </div>
        )}
      </div>

      {openId !== null && <DetailsDrawer id={openId} rows={rows} onClose={close} onOpen={open} onSettings={() => onSettings(openId)} />}
    </section>
  );
}

function Tag({ label, onRemove }: { label: string; onRemove: () => void }) {
  return (
    <button type="button" onClick={onRemove} aria-label={`Remove filter ${label}`}
      className="pop inline-flex min-h-9 max-w-full items-center gap-1.5 rounded-xl bg-primary-soft px-3 text-sm font-semibold text-primary-strong transition-colors hover:bg-primary hover:text-white">
      <span className="truncate">{label}</span><Icon name="close" size={14} strokeWidth={2.4} />
    </button>
  );
}

function Empty({ icon, title, text, children, role }: { icon: "moon" | "search"; title: string; text: string; children: React.ReactNode; role?: "alert" }) {
  return (
    <div role={role} className="grid justify-items-center gap-2 px-6 py-16 text-center">
      <span className="pop grid size-16 place-items-center rounded-3xl bg-primary-soft text-primary"><Icon name={icon} size={30} /></span>
      <p className="mt-2 text-lg font-bold">{title}</p>
      <p className="max-w-sm text-muted">{text}</p>
      <div className="mt-2 flex flex-wrap justify-center gap-2">{children}</div>
    </div>
  );
}
