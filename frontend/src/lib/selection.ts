/** Selection is a set of account ids, owned above the table, so paging and refresh cannot disturb it. */
export type Selection = ReadonlySet<number>;

export function toggle(sel: Selection, id: number): Selection {
  const next = new Set(sel);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  return next;
}

export type PageState = "none" | "some" | "all";

export function pageState(sel: Selection, pageIds: readonly number[]): PageState {
  if (pageIds.length === 0) return "none";
  const n = pageIds.filter((id) => sel.has(id)).length;
  return n === 0 ? "none" : n === pageIds.length ? "all" : "some";
}

/** Header checkbox: selects or clears this page only. */
export function togglePage(sel: Selection, pageIds: readonly number[]): Selection {
  const next = new Set(sel);
  if (pageState(sel, pageIds) === "all") pageIds.forEach((id) => next.delete(id));
  else pageIds.forEach((id) => next.add(id));
  return next;
}

export const countOffPage = (sel: Selection, pageIds: readonly number[]) =>
  [...sel].filter((id) => !pageIds.includes(id)).length;

// Kept for the tab, so a reload does not throw away a selection built across pages.
const KEY = "callzo:selection";
export function loadSelection(): Selection {
  try {
    const v: unknown = JSON.parse(sessionStorage.getItem(KEY) ?? "[]");
    return new Set(Array.isArray(v) ? v.filter((n): n is number => Number.isInteger(n)) : []);
  } catch { return new Set(); }
}
export function storeSelection(sel: Selection): void {
  try { sessionStorage.setItem(KEY, JSON.stringify([...sel])); } catch { /* storage blocked: selection still works in memory */ }
}
