import type { SeriesPoint } from "../api/types.ts";
import { formatDate, formatDay, formatMonth } from "./format.ts";

export interface Bucket extends Omit<SeriesPoint, "date"> {
  from: string;
  to: string;
  /** Axis label. */
  label: string;
  /** Full name, for the headline and the screen-reader table. */
  title: string;
  days: number;
  /** Covers less than the whole week or month, so it looks small only because it is short. */
  partial: boolean;
}

export type Grain = "day" | "week" | "month";

/** Few, readable bars: up to a month by day, up to six months by week, otherwise by month. */
export const grainFor = (n: number): Grain => (n <= 31 ? "day" : n <= 184 ? "week" : "month");

const daysInMonth = (iso: string) => new Date(Date.UTC(+iso.slice(0, 4), +iso.slice(5, 7), 0)).getUTCDate();

export function bucketize(series: readonly SeriesPoint[]): { grain: Grain; buckets: Bucket[] } {
  const grain = grainFor(series.length);
  const groups = new Map<string, SeriesPoint[]>();
  series.forEach((p, i) => {
    // Weeks are counted back from the last day, so the most recent one is whole.
    const key = grain === "day" ? p.date : grain === "month" ? p.date.slice(0, 7) : `w${Math.floor((series.length - 1 - i) / 7)}`;
    const g = groups.get(key);
    if (g) g.push(p);
    else groups.set(key, [p]);
  });
  const sum = (g: SeriesPoint[], k: "minutes" | "sms" | "cost_cents" | "signups") => g.reduce((n, p) => n + p[k], 0);
  const buckets = [...groups.values()].map((g): Bucket => {
    const from = g[0].date;
    const to = g[g.length - 1].date;
    return {
      from, to, days: g.length,
      label: grain === "month" ? formatDate(from, { month: "short" }) + (from.slice(5, 7) === "01" ? ` ’${from.slice(2, 4)}` : "") : formatDay(from),
      title: grain === "month" ? formatMonth(from) : grain === "day" ? formatDate(from) : `${formatDay(from)} – ${formatDate(to)}`,
      partial: grain === "month" ? g.length < daysInMonth(from) : grain === "week" ? g.length < 7 : false,
      minutes: sum(g, "minutes"), sms: sum(g, "sms"), cost_cents: sum(g, "cost_cents"), signups: sum(g, "signups"),
    };
  });
  return { grain, buckets };
}
