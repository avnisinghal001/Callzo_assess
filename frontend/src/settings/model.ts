import type { SavedSettings, StepData } from "../api/types.ts";
import type { IconName } from "../ui/Icon.tsx";

export type StepNo = 1 | 2 | 3 | 4;
export const STEPS: StepNo[] = [1, 2, 3, 4];

export const STEP_TITLES: Record<StepNo, { title: string; short: string; intro: string; icon: IconName }> = {
  1: { title: "About this account", short: "About", intro: "Who should we contact?", icon: "smile" },
  2: { title: "Plan and billing", short: "Plan", intro: "Pick a plan and where it is billed.", icon: "billing" },
  3: { title: "Set usage limits", short: "Limits", intro: "Optional. Leave a limit empty for no cap.", icon: "limits" },
  4: { title: "Where should updates go?", short: "Updates", intro: "Optional. A web address (URL) that receives call updates.", icon: "webhook" },
};

export const FIELDS: Record<StepNo, string[]> = {
  1: ["name", "email"],
  2: ["plan", "billing_country"],
  3: ["minutes_cap", "sms_cap"],
  4: ["webhook_url"],
};

export type Draft = Record<string, string>;

export const PLANS = ["basic", "pro", "enterprise"] as const;
export const BILLING_COUNTRIES = ["US", "IN", "GB", "CA", "AU"];

export const blankDraft = (step: StepNo): Draft => Object.fromEntries(FIELDS[step].map((f) => [f, ""]));

/** Form strings -> the exact body the API expects. Optional empty numbers are left out. */
export function toPayload(step: StepNo, d: Draft): StepData {
  const t = (f: string) => (d[f] ?? "").trim();
  switch (step) {
    case 1: return { name: t("name"), email: t("email") };
    case 2: return { plan: t("plan"), billing_country: t("billing_country") };
    case 3: {
      const out: StepData = {};
      if (t("minutes_cap") !== "") out.minutes_cap = Number(t("minutes_cap"));
      if (t("sms_cap") !== "") out.sms_cap = Number(t("sms_cap"));
      return out;
    }
    case 4: return { webhook_url: t("webhook_url") };
  }
}

/** What the server returned for a step -> form strings. */
export function fromServer(step: StepNo, data: StepData | null | undefined): Draft {
  const d = blankDraft(step);
  if (data) for (const f of FIELDS[step]) if (data[f] !== undefined && data[f] !== null) d[f] = String(data[f]);
  return d;
}

export function samePayload(a: StepData | null, b: StepData | null): boolean {
  if (!a || !b) return a === b;
  const ka = Object.keys(a).sort();
  const kb = Object.keys(b).sort();
  return ka.length === kb.length && ka.every((k, i) => k === kb[i] && String(a[k]) === String(b[k]));
}

/** Server wording, without its internal field names: "billing_country is required" becomes readable. */
export const serverMessage = (m: string) => `The server didn’t accept this: “${m.replaceAll("_", " ")}”`;

const isNum = (v: string) => v !== "" && Number.isFinite(Number(v));

/** Same rules as the API (spec) plus "caps cannot be negative", which the API does not enforce. */
export function validate(step: StepNo, d: Draft): Record<string, string> {
  const e: Record<string, string> = {};
  const t = (f: string) => (d[f] ?? "").trim();
  if (step === 1) {
    if (!t("name")) e.name = "Enter a contact name.";
    if (!/\S@\S/.test(t("email"))) e.email = "Enter a valid email address, like name@company.com.";
  }
  if (step === 2) {
    if (!(PLANS as readonly string[]).includes(t("plan"))) e.plan = "Choose a plan.";
    if (!BILLING_COUNTRIES.includes(t("billing_country"))) e.billing_country = "Choose a billing country.";
  }
  if (step === 3) {
    for (const f of FIELDS[3]) {
      const v = t(f);
      if (v === "") continue;
      if (!isNum(v)) e[f] = "Enter a number, or leave this empty.";
      else if (Number(v) < 0) e[f] = "Enter zero or more.";
    }
  }
  if (step === 4) {
    const v = t("webhook_url");
    if (v && !/^https?:\/\/\S+/.test(v)) e.webhook_url = "The address must start with http:// or https://";
  }
  return e;
}

export const savedFromServer = (s: SavedSettings, step: StepNo): StepData | null => s[String(step) as "1"] ?? null;
