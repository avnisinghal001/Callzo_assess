const number = new Intl.NumberFormat("en");
export const count = (n) => number.format(n);
export const compact = (n) => new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 }).format(n);
// No currency symbol: the event contract says "cents" without naming a currency.
export const money = (cents) => new Intl.NumberFormat("en", { minimumFractionDigits: 2 }).format(cents / 100);
export const minutes = (seconds) => (seconds && seconds < 600 ? `${Math.floor(seconds / 60)}m ${seconds % 60}s` : `${count(Math.floor(seconds / 60))} min`);
export const clock = (iso) => new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
export const stamp = (iso) => (iso ? new Date(iso).toLocaleString([], { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "Not yet");
export const day = (iso) => new Date(iso).toLocaleDateString([], { weekday: "long", day: "numeric", month: "long" });
export const monthName = (ym) => new Date(`${ym}-01T00:00:00Z`).toLocaleDateString("en", { month: "long", year: "numeric", timeZone: "UTC" });
export const isoDay = (daysAgo = 0) => new Date(Date.now() - daysAgo * 86400000).toISOString().slice(0, 10);
export const plural = (n, one, many = `${one}s`) => `${count(n)} ${n === 1 ? one : many}`;
export function ago(iso) {
  const s = Math.max(0, (Date.now() - new Date(iso)) / 1000);
  if (s < 10) return "just now";
  if (s < 60) return `${Math.floor(s)} s ago`;
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return `${Math.floor(s / 86400)} d ago`;
}
export const CAP = {
  ok: ["Comfortable", "ok", "happy"], warning: ["Nearly full", "wait", "curious"],
  reached: ["Cap reached", "bad", "asleep"], exceeded: ["Over the cap", "bad", "asleep"],
};
export const EVENT = { "call.started": ["Call started", "phone", "info"], "call.ended": ["Call ended", "ended", "ok"], "call.failed": ["Call failed", "failed", "bad"] };
export const STATE = { pending: ["Waiting", "wait"], processed: ["Counted", "ok"], dead: ["Gave up", "bad"], voided: ["Set aside", ""] };
