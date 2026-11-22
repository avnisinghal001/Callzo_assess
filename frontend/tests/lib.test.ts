import assert from "node:assert/strict";
import { test } from "node:test";
import type { Account, SeriesPoint } from "../src/api/types.ts";
import { pageList } from "../src/lib/pages.ts";
import { bucketize } from "../src/lib/buckets.ts";
import { mergeRefresh } from "../src/lib/mergeRefresh.ts";
import { accountsParams, isDate, parseListQuery } from "../src/lib/query.ts";
import { countOffPage, pageState, toggle, togglePage } from "../src/lib/selection.ts";

const acc = (id: number, minutes = 0) => ({ id, current_month_minutes: minutes }) as Account;
const days = (from: string, n: number): SeriesPoint[] => Array.from({ length: n }, (_, i) => ({
  date: new Date(Date.parse(from) + i * 86_400_000).toISOString().slice(0, 10), minutes: 1, sms: 2, cost_cents: 3, signups: 4,
}));

test("refresh updates values in place and keeps the displayed order", () => {
  const m = mergeRefresh([acc(1, 5), acc(2, 4)], [acc(2, 9), acc(1, 5)]);
  assert.deepEqual(m.rows.map((r) => [r.id, r.current_month_minutes]), [[1, 5], [2, 9]]);
  assert.equal(m.orderChanged, true);
  assert.equal(mergeRefresh([acc(1), acc(2)], [acc(1, 3), acc(2)]).orderChanged, false);
});

test("refresh keeps a row that left the page, and reports it", () => {
  const m = mergeRefresh([acc(1), acc(2)], [acc(1), acc(3)]);
  assert.deepEqual(m.rows.map((r) => r.id), [1, 2]);
  assert.equal(m.orderChanged, true);
});

test("selection is by id and the page checkbox leaves other pages alone", () => {
  let s = toggle(new Set<number>(), 99);
  s = togglePage(s, [1, 2]);
  assert.deepEqual([...s].sort((a, b) => a - b), [1, 2, 99]);
  assert.equal(pageState(s, [1, 2]), "all");
  assert.equal(pageState(s, [2, 3]), "some");
  assert.equal(countOffPage(s, [1, 2]), 1);
  assert.deepEqual([...togglePage(s, [1, 2])], [99]);
});

test("url parsing rejects junk and puts reversed dates the right way round", () => {
  const q = parseListQuery(new URLSearchParams("page=-3&sort=drop&dir=up&plan=gold&country=PK&from=2026-03-01&to=2026-01-01"));
  assert.deepEqual([q.page, q.sort, q.dir, q.plan, q.country, q.from, q.to], [1, "id", "asc", "", "PK", "2026-01-01", "2026-03-01"]);
  assert.equal(isDate("2026-13-45"), false);
  assert.equal(isDate("2026-02-30"), false);
  assert.equal(accountsParams(q).date_from, "2026-01-01");
  assert.equal(accountsParams({ ...q, q: "   " }).search, undefined);
});

test("buckets: days, then weeks, then months, and totals are preserved", () => {
  assert.equal(bucketize(days("2026-01-01", 31)).grain, "day");
  const w = bucketize(days("2026-01-01", 90));
  assert.equal(w.grain, "week");
  assert.equal(w.buckets.at(-1)!.days, 7);
  assert.deepEqual([w.buckets[0].days, w.buckets[0].partial], [6, true]);
  const m = bucketize(days("2024-01-01", 1036));
  assert.equal(m.grain, "month");
  assert.equal(m.buckets.length, 35);
  assert.deepEqual([m.buckets.at(-1)!.days, m.buckets.at(-1)!.partial], [1, true]);
  assert.equal(m.buckets[1].partial, false); // February of a leap year
  assert.equal(m.buckets.reduce((n, b) => n + b.sms, 0), 2072);
  assert.deepEqual(bucketize([]).buckets, []);
});

test("page list", () => {
  assert.deepEqual(pageList(1, 420), [1, 2, 0, 420]);
  assert.deepEqual(pageList(10, 420), [1, 0, 9, 10, 11, 0, 420]);
  assert.deepEqual(pageList(2, 2), [1, 2]);
});
