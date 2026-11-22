import type { MouseEvent } from "react";
import type { Account, SortField } from "../api/types.ts";
import { useMediaQuery } from "../hooks/ui.ts";
import { formatCount, formatMoney } from "../lib/format.ts";
import { pageState, type Selection } from "../lib/selection.ts";
import { Avatar } from "../ui/Avatar.tsx";
import { Icon } from "../ui/Icon.tsx";
import { Live, PlanChip, StatusChip } from "../ui/primitives.tsx";

interface Props {
  rows: Account[];
  selection: Selection;
  sort: SortField;
  dir: "asc" | "desc";
  busy: boolean;
  onSort: (field: SortField) => void;
  onToggle: (id: number) => void;
  onTogglePage: () => void;
  onOpen: (id: number) => void;
}

const COLS: { field: SortField; label: string }[] = [
  { field: "company", label: "Business" },
  { field: "current_month_minutes", label: "This month" },
  { field: "cost_cents", label: "Spend" },
  { field: "plan", label: "Plan" },
  { field: "status", label: "Status" },
];

/**
 * The whole row opens the account. The business name is the real button, so keyboard and screen
 * reader users get one clear control; its click simply bubbles to the row. The checkbox area and
 * any text selection are excluded.
 */
function openHandler(id: number, onOpen: (id: number) => void) {
  return (e: MouseEvent) => {
    if ((e.target as HTMLElement).closest("[data-no-open]")) return;
    if (window.getSelection()?.toString()) return;
    onOpen(id);
  };
}

export function AccountsTable(p: Props) {
  const wide = useMediaQuery("(min-width: 768px)");
  const state = pageState(p.selection, p.rows.map((r) => r.id));
  const max = Math.max(1, ...p.rows.map((r) => r.current_month_minutes));
  const pageBox = (
    <input type="checkbox" className="check" checked={state === "all"} onChange={p.onTogglePage}
      ref={(el) => { if (el) el.indeterminate = state === "some"; }} aria-label="Select everyone on this page" />
  );
  const rowBox = (a: Account) => (
    <input type="checkbox" className="check" checked={p.selection.has(a.id)} onChange={() => p.onToggle(a.id)} aria-label={`Select ${a.company}, ${a.name}`} />
  );
  const name = (a: Account) => (
    <button type="button" data-open-account={a.id} aria-label={`Open ${a.company}, ${a.name}`} aria-haspopup="dialog"
      className="max-w-full truncate rounded-md text-left text-[15px] font-semibold">{a.company}</button>
  );

  if (!wide) {
    return (
      <div className={`px-3 pb-3 transition-opacity ${p.busy ? "opacity-50" : ""}`} aria-busy={p.busy}>
        <label className="flex min-h-11 w-fit items-center gap-3 px-3 text-sm font-medium text-muted">{pageBox} Select this page</label>
        <ul className="grid gap-2">
          {p.rows.map((a) => (
            <li key={a.id} onClick={openHandler(a.id, p.onOpen)}
              className={`group cursor-pointer rounded-2xl p-3 transition-[background,transform] active:scale-[0.98] ${p.selection.has(a.id) ? "bg-primary-soft" : "bg-card"}`}>
              <div className="flex items-center gap-3">
                <label data-no-open className="-m-2 grid size-11 place-items-center">{rowBox(a)}</label>
                <Avatar id={a.id} status={a.status} size={42} />
                <div className="min-w-0 flex-1">{name(a)}<p className="truncate text-sm text-muted">{a.name}</p></div>
                <StatusChip status={a.status} />
              </div>
              <div className="mt-3 flex items-center gap-3 pl-10">
                <MiniBar a={a} max={max} />
                <span className="tnum text-sm font-semibold"><Live value={a.cost_cents}>{formatMoney(a.cost_cents)}</Live></span>
                <Icon name="chevRight" size={18} className="text-faint" />
              </div>
            </li>
          ))}
        </ul>
      </div>
    );
  }

  return (
    <div className={`overflow-x-auto px-2 transition-opacity ${p.busy ? "opacity-50" : ""}`} aria-busy={p.busy}>
      <table className="w-full border-separate border-spacing-y-0.5">
        <caption className="sr-only">Accounts. Use the column headings to sort, and a business name to open it.</caption>
        <thead>
          <tr className="text-left text-sm text-muted">
            <th scope="col" className="w-14 p-0"><label className="grid h-11 place-items-center">{pageBox}</label></th>
            {COLS.map((c) => {
              const on = p.sort === c.field;
              return (
                <th key={c.field} scope="col" aria-sort={on ? (p.dir === "asc" ? "ascending" : "descending") : "none"} className="px-2 font-semibold">
                  <button type="button" onClick={() => p.onSort(c.field)}
                    className={`group/sort -ml-2 inline-flex min-h-10 items-center gap-1 rounded-lg px-2 transition-colors hover:bg-card hover:text-ink ${on ? "text-primary" : ""}`}>
                    {c.label}
                    <Icon name={on ? (p.dir === "asc" ? "up" : "down") : "sort"} size={15} strokeWidth={2.2}
                      className={on ? "pop" : "opacity-40 transition-opacity group-hover/sort:opacity-100"} />
                  </button>
                </th>
              );
            })}
            <th className="w-14"><span className="sr-only">Opens details</span></th>
          </tr>
        </thead>
        <tbody>
          {p.rows.map((a) => {
            const sel = p.selection.has(a.id);
            return (
              <tr key={a.id} onClick={openHandler(a.id, p.onOpen)}
                className={`group cursor-pointer [&>td]:transition-colors ${sel ? "[&>td]:bg-primary-soft" : "hover:[&>td]:bg-card has-[[data-open-account]:focus-visible]:[&>td]:bg-card"} [&>td:first-child]:rounded-l-2xl [&>td:last-child]:rounded-r-2xl`}>
                <td data-no-open className="p-0"><label className="grid h-16 cursor-pointer place-items-center">{rowBox(a)}</label></td>
                <td className="max-w-[280px] px-2">
                  <div className="flex items-center gap-3">
                    <Avatar id={a.id} status={a.status} />
                    <div className="min-w-0">{name(a)}<p className="truncate text-sm text-muted">{a.name}</p></div>
                  </div>
                </td>
                <td className="w-[26%] px-2"><MiniBar a={a} max={max} /></td>
                <td className="tnum px-2 font-semibold"><Live value={a.cost_cents}>{formatMoney(a.cost_cents)}</Live></td>
                <td className="px-2"><PlanChip plan={a.plan} /></td>
                <td className="px-2"><StatusChip status={a.status} /></td>
                <td className="px-2">
                  <span className="grid size-9 -translate-x-1 scale-90 place-items-center rounded-xl text-faint transition-all duration-200 ease-spring group-has-[[data-open-account]:focus-visible]:translate-x-0 group-has-[[data-open-account]:focus-visible]:scale-100 group-has-[[data-open-account]:focus-visible]:bg-primary group-has-[[data-open-account]:focus-visible]:text-white group-hover:translate-x-0 group-hover:scale-100 group-hover:bg-primary group-hover:text-white" aria-hidden="true">
                    <Icon name="chevRight" size={18} strokeWidth={2.4} />
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/** Minutes as a length (relative to the busiest account on this page), with the exact number beside it. */
function MiniBar({ a, max }: { a: Account; max: number }) {
  return (
    <div className="flex min-w-0 flex-1 items-center gap-2.5">
      <span className="h-2.5 min-w-8 flex-1 overflow-hidden rounded-full bg-track" aria-hidden="true">
        <span className="block h-full rounded-full bg-minutes transition-[width] duration-500 ease-smooth" style={{ width: `${Math.max(3, (a.current_month_minutes / max) * 100)}%` }} />
      </span>
      <span className="tnum w-[4.6rem] shrink-0 text-sm font-medium"><Live value={a.current_month_minutes}>{formatCount(a.current_month_minutes)} min</Live></span>
    </div>
  );
}
