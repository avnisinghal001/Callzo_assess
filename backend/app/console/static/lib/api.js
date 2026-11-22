// The session cookie is set by the server when this page is opened; there is nothing to sign in to.
// The custom header is what stops another site from using that cookie (see console_session.py).

const RELOADED = "console.reloaded";

export async function api(path, { method = "GET", body } = {}) {
  let response;
  try {
    response = await fetch(path, {
      method,
      headers: { "X-Console": "1", ...(body ? { "Content-Type": "application/json" } : {}) },
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new Error("The server can’t be reached right now.");
  }
  if (response.status === 401) {
    // The session expired: opening the page again renews it. Once only, never in a loop.
    if (!sessionStorage.getItem(RELOADED)) {
      sessionStorage.setItem(RELOADED, "1");
      location.reload();
      return new Promise(() => {});
    }
    throw new Error("This console is locked on this server.");
  }
  sessionStorage.removeItem(RELOADED);
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const fields = (data?.error?.fields ?? []).map((f) => f.field.replace(/^body\./, "")).join(", ");
    throw new Error(`${data?.error?.message ?? `Server answered ${response.status}`}${fields ? `: ${fields}` : ""}`);
  }
  return data;
}

export const enc = encodeURIComponent;

/** Every live account (the console is for tens of accounts; pages are followed up to 400). */
export async function allAccounts(deleted = false) {
  const items = [];
  let cursor = "";
  do {
    const page = await api(`/admin/v1/accounts?limit=200&deleted=${deleted}${cursor ? `&cursor=${enc(cursor)}` : ""}`);
    items.push(...page.items);
    cursor = page.next_cursor;
  } while (cursor && items.length < 400);
  return items;
}

// ---- fleet overview: one poll shared by the header and the Live page ----
const listeners = new Set();
let latest = null;
export function onOverview(fn) { listeners.add(fn); if (latest) fn(latest, null); return () => listeners.delete(fn); }
export async function pollOverview() {
  try {
    latest = await api("/admin/v1/overview");
    listeners.forEach((fn) => fn(latest, null));
  } catch (error) {
    listeners.forEach((fn) => fn(null, error));
  }
}
