import { useEffect, useId, useRef, useState } from "react";
import { formatDate, formatDay } from "../lib/format.ts";
import { Icon } from "../ui/Icon.tsx";
import { Button } from "../ui/primitives.tsx";

const iso = (d: Date) => d.toISOString().slice(0, 10);

function presets() {
  const now = new Date();
  const back = (n: number) => iso(new Date(now.getTime() - (n - 1) * 86_400_000));
  const y = now.getUTCFullYear();
  return [
    { label: "All time", from: "", to: "" },
    { label: String(y), from: `${y}-01-01`, to: `${y}-12-31` },
    { label: String(y - 1), from: `${y - 1}-01-01`, to: `${y - 1}-12-31` },
    { label: "90 days", from: back(90), to: iso(now) },
    { label: "30 days", from: back(30), to: iso(now) },
  ];
}

/** One range for the whole page. Custom dates apply only once both make sense together. */
export function PeriodPicker({ from, to, onChange }: { from: string; to: string; onChange: (from: string, to: string) => void }) {
  const list = presets();
  const custom = !list.some((p) => p.from === from && p.to === to);
  const [open, setOpen] = useState(false);
  const [a, setA] = useState(from);
  const [b, setB] = useState(to);
  const box = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const errId = useId();
  const bad = Boolean(a && b && a > b);

  const toggle = () => { setA(from); setB(to); setOpen((o) => !o); };
  useEffect(() => {
    if (!open) return;
    const away = (e: PointerEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") { setOpen(false); trigger.current?.focus(); } };
    document.addEventListener("pointerdown", away);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("pointerdown", away); document.removeEventListener("keydown", esc); };
  }, [open]);

  const pill = (on: boolean) =>
    `min-h-10 shrink-0 whitespace-nowrap rounded-xl px-3 text-sm font-semibold transition-colors ${on ? "bg-tile text-ink shadow-tile" : "text-muted hover:text-ink"}`;
  const inputCls = `min-h-11 w-full rounded-xl border bg-tile px-3 text-base sm:text-sm ${bad ? "border-suspended" : "border-line-strong"}`;

  return (
    <div ref={box} className="relative w-full sm:w-auto">
      <div role="group" aria-label="Period" className="grid grid-cols-3 gap-0.5 rounded-2xl bg-card p-1 sm:flex">
        {list.map((p) => {
          const on = p.from === from && p.to === to;
          return <button key={p.label} type="button" aria-pressed={on} className={pill(on)} onClick={() => { setOpen(false); onChange(p.from, p.to); }}>{p.label}</button>;
        })}
        <button ref={trigger} type="button" aria-expanded={open} className={`${pill(custom)} inline-flex min-w-0 items-center justify-center gap-1.5 max-sm:whitespace-normal max-sm:leading-tight`} onClick={toggle}>
          <Icon name="calendar" size={16} />
          {custom ? (from && to ? (from === to ? formatDate(from) : `${formatDay(from)} – ${formatDate(to)}`) : from ? `From ${formatDate(from)}` : `Until ${formatDate(to)}`) : "Custom"}
        </button>
      </div>

      {open && (
        <form className="rise absolute right-0 top-full z-20 mt-2 grid w-[min(340px,calc(100vw-2rem))] gap-3 rounded-3xl border border-line bg-tile p-4 shadow-float max-sm:left-0 max-sm:right-auto"
          onSubmit={(e) => { e.preventDefault(); if (bad) return; onChange(a, b); setOpen(false); trigger.current?.focus(); }}>
          <div className="grid grid-cols-2 gap-3">
            <label className="grid min-w-0 gap-1 text-xs font-semibold text-muted">From
              <input autoFocus type="date" className={inputCls} value={a} onChange={(e) => setA(e.target.value)} aria-invalid={bad} aria-describedby={bad ? errId : undefined} /></label>
            <label className="grid min-w-0 gap-1 text-xs font-semibold text-muted">To
              <input type="date" className={inputCls} value={b} onChange={(e) => setB(e.target.value)} aria-invalid={bad} aria-describedby={bad ? errId : undefined} /></label>
          </div>
          {bad && <p id={errId} role="alert" className="text-sm text-suspended-ink">The start date must come before the end date.</p>}
          <p className="text-xs leading-relaxed text-muted">
            <strong className="text-ink">Activity</strong> shows what happened in this period. <strong className="text-ink">Accounts</strong> shows businesses that joined in this period.
          </p>
          <Button variant="primary" type="submit" disabled={bad}>Show this period</Button>
        </form>
      )}
    </div>
  );
}
