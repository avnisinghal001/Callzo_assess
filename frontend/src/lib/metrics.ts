import type { IconName } from "../ui/Icon.tsx";
import { formatCompact, formatCount, formatMoney } from "./format.ts";

export type MetricKey = "minutes" | "sms" | "cost_cents" | "signups";
export const METRIC_KEYS: MetricKey[] = ["minutes", "sms", "cost_cents", "signups"];

export const METRICS: Record<MetricKey, { label: string; icon: IconName; color: string; format: (n: number) => string; short: (n: number) => string }> = {
  minutes: { label: "Calling time", icon: "ringing", color: "var(--color-minutes)", format: (n) => `${formatCount(n)} min`, short: formatCompact },
  sms: { label: "Texts", icon: "sms", color: "var(--color-sms)", format: formatCount, short: formatCompact },
  cost_cents: { label: "Spend", icon: "spend", color: "var(--color-cost)", format: formatMoney, short: (n) => formatCompact(n / 100) },
  signups: { label: "New accounts", icon: "signup", color: "var(--color-signups)", format: formatCount, short: formatCompact },
};
