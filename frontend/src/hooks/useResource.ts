import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, isAbort } from "../api/client.ts";

export type ResourceStatus = "loading" | "ready" | "refreshing" | "error";

export interface Resource<T> {
  /** Last good data. Kept while a newer request is in flight or after it fails. */
  data: T | undefined;
  /** The key `data` was fetched for. Differs from the current key while switching. */
  dataKey: string | undefined;
  error: ApiError | undefined;
  status: ResourceStatus;
  /** Epoch ms of the last success. */
  updatedAt: number | undefined;
  refetch: () => void;
}

interface Options {
  /** Re-fetch this often while the tab is visible. Failures back off. */
  pollMs?: number;
  /** When false nothing is fetched. */
  enabled?: boolean;
}

/**
 * Fetch `fetcher` whenever `key` changes.
 * - A newer request aborts the older one and only the newest result is ever applied.
 * - Previous data stays on screen while the next loads (no flash of empty).
 * - Polling never overlaps (next tick is scheduled after the last one ends), pauses in hidden tabs.
 */
export function useResource<T>(
  key: string,
  fetcher: (signal: AbortSignal) => Promise<T>,
  { pollMs, enabled = true }: Options = {},
): Resource<T> {
  const [state, setState] = useState<{
    data?: T; dataKey?: string; error?: ApiError; updatedAt?: number; busy: boolean;
  }>({ busy: enabled });
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  const run = useRef<(() => void) | null>(null);

  useEffect(() => {
    if (!enabled) return;
    let alive = true;
    let ctrl: AbortController | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let failures = 0;

    const schedule = () => {
      if (!pollMs || !alive) return;
      clearTimeout(timer);
      timer = setTimeout(tick, Math.min(pollMs * 2 ** failures, 60_000));
    };

    const load = async () => {
      ctrl?.abort();
      const mine = (ctrl = new AbortController());
      setState((s) => ({ ...s, busy: true }));
      try {
        const data = await fetcherRef.current(mine.signal);
        if (!alive || mine.signal.aborted) return;
        failures = 0;
        setState({ data, dataKey: key, error: undefined, updatedAt: Date.now(), busy: false });
      } catch (e) {
        if (!alive || mine.signal.aborted || isAbort(e)) return;
        failures += 1;
        const error = e instanceof ApiError ? e : new ApiError("network", 0, null);
        setState((s) => ({ ...s, error, busy: false }));
      }
      schedule();
    };

    const tick = () => {
      if (document.hidden) schedule(); // stay quiet in the background
      else void load();
    };
    const onVisible = () => {
      if (!document.hidden && pollMs) void load();
    };

    run.current = () => {
      failures = 0;
      void load();
    };
    void load();
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      alive = false;
      ctrl?.abort();
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [key, pollMs, enabled]);

  const refetch = useCallback(() => run.current?.(), []);
  const status: ResourceStatus = state.busy
    ? state.data === undefined ? "loading" : "refreshing"
    : state.error ? "error" : state.data === undefined ? "loading" : "ready";
  return { data: state.data, dataKey: state.dataKey, error: state.error, status, updatedAt: state.updatedAt, refetch };
}

export function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}
