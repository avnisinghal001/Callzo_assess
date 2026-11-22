import { COUNTRIES } from "./format.ts";
import { SORT_FIELDS, type SortField } from "../api/types.ts";

export const PAGE_SIZE = 25;

/** Everything the account list needs, as parsed from the URL. */
export interface ListQuery {
  q: string;
  plan: string;
  status: string;
  country: string;
  from: string;
  to: string;
  sort: SortField;
  dir: "asc" | "desc";
  page: number;
}

/** A real calendar date, not just the right shape: the API rejects 2026-13-45. */
export const isDate = (v: string | null): v is string =>
  !!v && /^\d{4}-\d{2}-\d{2}$/.test(v) && new Date(`${v}T00:00:00Z`).toJSON()?.slice(0, 10) === v;

const oneOf = (v: string | null, allowed: readonly string[]) => (v && allowed.includes(v) ? v : "");

export function parseListQuery(p: URLSearchParams): ListQuery {
  const page = Number.parseInt(p.get("page") ?? "1", 10);
  const sort = p.get("sort");
  let from = isDate(p.get("from")) ? p.get("from")! : "";
  let to = isDate(p.get("to")) ? p.get("to")! : "";
  if (from && to && from > to) [from, to] = [to, from];
  return {
    q: p.get("q") ?? "",
    plan: oneOf(p.get("plan"), ["basic", "pro", "enterprise"]),
    status: oneOf(p.get("status"), ["active", "trial", "suspended"]),
    country: oneOf(p.get("country"), COUNTRIES),
    from,
    to,
    sort: SORT_FIELDS.includes(sort as SortField) ? (sort as SortField) : "id",
    dir: p.get("dir") === "desc" ? "desc" : "asc",
    page: Number.isFinite(page) && page > 0 ? page : 1,
  };
}

/** Query string for GET /accounts. Also used as the cache key of the list resource. */
export function accountsParams(q: ListQuery) {
  return {
    page: q.page,
    page_size: PAGE_SIZE,
    search: q.q.trim() || undefined,
    plan: q.plan || undefined,
    status: q.status || undefined,
    country: q.country || undefined,
    date_from: q.from || undefined,
    date_to: q.to || undefined,
    sort_by: q.sort,
    sort_dir: q.dir,
  };
}

export const hasActiveFilters = (q: ListQuery) => Boolean(q.q.trim() || q.plan || q.status || q.country);
