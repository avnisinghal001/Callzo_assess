export type Plan = "basic" | "pro" | "enterprise";
export type Status = "active" | "trial" | "suspended";

export interface Account {
  id: number;
  name: string;
  email: string;
  company: string;
  country: string;
  plan: Plan;
  status: Status;
  signup_date: string;
  current_month_minutes: number;
  current_month_sms: number;
  cost_cents: number;
  last_active: string;
}

export interface AccountsPage {
  data: Account[];
  total: number;
  page: number;
  page_size: number;
}

export interface SeriesPoint {
  date: string;
  minutes: number;
  sms: number;
  cost_cents: number;
  signups: number;
}

export interface Summary {
  series: SeriesPoint[];
  total_accounts: number;
}

/** What the API stores per step, keyed by step number as a string. */
export type StepData = Record<string, string | number>;
export type SavedSettings = Partial<Record<"1" | "2" | "3" | "4", StepData>>;

export const SORT_FIELDS = [
  "id", "name", "company", "country", "plan", "status", "signup_date",
  "current_month_minutes", "current_month_sms", "cost_cents", "last_active",
] as const;
export type SortField = (typeof SORT_FIELDS)[number];
