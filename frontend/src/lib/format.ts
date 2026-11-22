// The spec does not say which currency cost_cents is in, so amounts are shown as plain
// numbers (cents / 100) with no symbol. See README, assumptions.
const money = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const whole = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const short = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });
const regions = new Intl.DisplayNames("en", { type: "region" });

export const formatMoney = (cents: number) => money.format(cents / 100);
export const formatCount = (n: number) => whole.format(n);
export const formatCompact = (n: number) => short.format(n);

/** "2025-03-14" to "14 Mar 2025", in UTC so the viewer's time zone cannot shift the day. */
export const formatDate = (iso: string, o: Intl.DateTimeFormatOptions = { day: "numeric", month: "short", year: "numeric" }) => {
  const d = new Date(`${iso}T00:00:00Z`);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString("en-GB", { ...o, timeZone: "UTC" });
};
export const formatDay = (iso: string) => formatDate(iso, { day: "numeric", month: "short" });
export const formatMonth = (iso: string) => formatDate(iso, { month: "short", year: "numeric" });

export const formatTime = (ms: number) =>
  new Date(ms).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });

export const PLAN_LABEL = { basic: "Basic", pro: "Pro", enterprise: "Enterprise" } as const;
export const STATUS_LABEL = { active: "Active", trial: "Trial", suspended: "Suspended" } as const;

/** Countries present in the account data (found by inspection; the API has no endpoint that lists them). */
export const COUNTRIES = ["AU", "BR", "CA", "DE", "FR", "GB", "IN", "NG", "PK", "US"];
export const countryName = (c: string) => { try { return regions.of(c) ?? c; } catch { return c; } };
export const flag = (c: string) => String.fromCodePoint(...[...c].map((x) => 127397 + x.charCodeAt(0)));
