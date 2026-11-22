import type { Account } from "../api/types.ts";

export interface Merged {
  rows: Account[];
  /** True when the server now orders or includes different rows than the ones on screen. */
  orderChanged: boolean;
}

/**
 * Background refreshes drift values (and can reorder rows when sorted by a drifting column).
 * Update values in place and keep the displayed order, so rows never jump under the cursor.
 * If the fresh order or membership differs, report it; the UI offers an explicit "Update".
 */
export function mergeRefresh(shown: readonly Account[], incoming: readonly Account[]): Merged {
  const fresh = new Map(incoming.map((a) => [a.id, a]));
  const rows = shown.map((a) => fresh.get(a.id) ?? a);
  const sameOrder = shown.length === incoming.length && shown.every((a, i) => a.id === incoming[i]?.id);
  return { rows, orderChanged: !sameOrder };
}
