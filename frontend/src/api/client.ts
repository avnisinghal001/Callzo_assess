import type { Account, AccountsPage, SavedSettings, StepData, Summary } from "./types.ts";

const BASE = "/api";

export class ApiError extends Error {
  /** "network": never reached the server. "http": server answered with an error status. */
  readonly kind: "network" | "http";
  readonly status: number;
  readonly body: unknown;
  constructor(kind: "network" | "http", status: number, body: unknown) {
    super(kind === "network" ? "network error" : `http ${status}`);
    this.kind = kind;
    this.status = status;
    this.body = body;
  }
  /** Field errors from a 422 `{detail: {step, errors}}` response. */
  get fieldErrors(): Record<string, string> | null {
    const d = (this.body as { detail?: { errors?: Record<string, string> } } | null)?.detail;
    return this.status === 422 && d && typeof d === "object" && d.errors ? d.errors : null;
  }
  /** Step numbers from a 400 `{detail: {missing_steps}}` response. */
  get missingSteps(): number[] | null {
    const d = (this.body as { detail?: { missing_steps?: number[] } } | null)?.detail;
    return this.status === 400 && d && Array.isArray(d.missing_steps) ? d.missing_steps : null;
  }
}

export const isAbort = (e: unknown) => e instanceof DOMException && e.name === "AbortError";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(BASE + path, init);
  } catch (e) {
    if (isAbort(e)) throw e;
    throw new ApiError("network", 0, null);
  }
  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    /* an empty or non-JSON body is fine; the status still tells the story */
  }
  if (!res.ok) throw new ApiError("http", res.status, body);
  return body as T;
}

function qs(params: Record<string, string | number | undefined>): string {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== "") u.set(k, String(v));
  const s = u.toString();
  return s ? `?${s}` : "";
}

export const api = {
  accounts: (p: Record<string, string | number | undefined>, signal?: AbortSignal) =>
    request<AccountsPage>(`/accounts${qs(p)}`, { signal }),
  account: (id: number, signal?: AbortSignal) => request<Account>(`/accounts/${id}`, { signal }),
  summary: (p: { date_from?: string; date_to?: string }, signal?: AbortSignal) =>
    request<Summary>(`/accounts/summary${qs(p)}`, { signal }),
  settings: (id: number, signal?: AbortSignal) => request<SavedSettings>(`/accounts/${id}/settings`, { signal }),
  saveStep: (id: number, step: number, data: StepData, signal?: AbortSignal) =>
    request<{ step: number; saved: boolean; data: StepData }>(`/accounts/${id}/settings/step/${step}`, {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ data }),
      signal,
    }),
  submit: (id: number) => request<{ submitted: boolean }>(`/accounts/${id}/settings/submit`, { method: "POST" }),
};
