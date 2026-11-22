import { useCallback, useSyncExternalStore } from "react";

// The URL is the source of truth for page, search, filters, sort, dates, open account and
// form step. A tiny History API wrapper is all that is needed; no router.
const EVENT = "callzo:urlchange";

function subscribe(cb: () => void) {
  window.addEventListener("popstate", cb);
  window.addEventListener(EVENT, cb);
  return () => {
    window.removeEventListener("popstate", cb);
    window.removeEventListener(EVENT, cb);
  };
}

const getSnapshot = () => window.location.search;

/** `patch` values of "" or undefined remove the key. `replace` avoids a history entry (typing). */
export type UrlPatch = Record<string, string | number | undefined>;

export function useUrlState() {
  const search = useSyncExternalStore(subscribe, getSnapshot);
  const params = new URLSearchParams(search);

  const update = useCallback((patch: UrlPatch, opts: { replace?: boolean } = {}) => {
    const next = new URLSearchParams(window.location.search);
    for (const [k, v] of Object.entries(patch)) {
      if (v === undefined || v === "") next.delete(k);
      else next.set(k, String(v));
    }
    const qs = next.toString();
    const url = window.location.pathname + (qs ? `?${qs}` : "");
    if (url === window.location.pathname + window.location.search) return;
    window.history[opts.replace ? "replaceState" : "pushState"](null, "", url);
    window.dispatchEvent(new Event(EVENT));
  }, []);

  return { search, params, update };
}
