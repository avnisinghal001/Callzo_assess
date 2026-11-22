import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api/client.ts";
import type { Account } from "../api/types.ts";
import { samePayload, serverMessage, STEPS, toPayload, validate, type Draft, type StepNo } from "./model.ts";
import { initialState, needsSave, readyToSubmit, reducer, type Action, type SettingsState } from "./reducer.ts";

const AUTOSAVE_MS = 800;
const storeKey = (id: number) => `callzo:settings-draft:${id}`;

function readStored(id: number): Partial<Record<StepNo, Draft>> {
  try { return JSON.parse(sessionStorage.getItem(storeKey(id)) ?? "{}"); } catch { return {}; }
}
function writeStored(id: number, v: Partial<Record<StepNo, Draft>>) {
  try {
    if (Object.keys(v).length) sessionStorage.setItem(storeKey(id), JSON.stringify(v));
    else sessionStorage.removeItem(storeKey(id));
  } catch { /* private mode etc.: recovery is a nicety, not a requirement */ }
}

export type LoadState = "loading" | "ready" | "notfound" | "error";

/**
 * Owns the form state and the save pipeline for one account.
 * - State lives in a ref + useState so async code always reads the latest value.
 * - One PUT per step at a time; edits made meanwhile coalesce into ONE follow-up PUT, so an
 *   older response can never overwrite newer text.
 * - A step the server already holds, and that hasn't changed, is never sent again.
 */
export function useSettings(id: number) {
  const [account, setAccount] = useState<Account>();
  const [state, setState] = useState<SettingsState>(initialState);
  const ref = useRef(state);
  const [load, setLoad] = useState<LoadState>("loading");

  const dispatch = useCallback((a: Action) => {
    ref.current = reducer(ref.current, a);
    setState(ref.current);
  }, []);

  // ---- load what the server has, then lay unfinished local edits over it ----
  const [loadTick, setLoadTick] = useState(0);
  useEffect(() => {
    const ctrl = new AbortController();
    setLoad("loading");
    // The account only supplies the title and starting values, so its failure must not block the form.
    Promise.all([api.settings(id, ctrl.signal), api.account(id, ctrl.signal).catch(() => undefined)]).then(
      ([saved, a]) => {
        if (ctrl.signal.aborted) return;
        setAccount(a);
        dispatch({
          type: "loaded", saved, recovered: readStored(id),
          defaults: a ? { 1: { name: a.name, email: a.email }, 2: { plan: a.plan, billing_country: "" } } : {},
        });
        setLoad("ready");
      },
      (e) => {
        if (ctrl.signal.aborted) return;
        setLoad(e instanceof ApiError && e.status === 404 ? "notfound" : "error");
      },
    );
    return () => ctrl.abort();
  }, [id, dispatch, loadTick]);

  // ---- keep unfinished edits (never "saved" data) in sessionStorage ----
  useEffect(() => {
    if (load !== "ready") return;
    const out: Partial<Record<StepNo, Draft>> = {};
    for (const n of STEPS) {
      const s = state.steps[n];
      if (s.status !== "clean") out[n] = s.draft;
    }
    writeStored(id, out);
  }, [state, load, id]);

  // ---- save pipeline ----
  const inflight = useRef<Partial<Record<StepNo, Promise<boolean>>>>({});
  const queued = useRef<Partial<Record<StepNo, boolean>>>({});

  /** One attempt. Resolves true when the server holds exactly what the form shows. */
  const once = useCallback(async (step: StepNo): Promise<boolean> => {
    const s = ref.current.steps[step];
    const errors = validate(step, s.draft);
    if (Object.keys(errors).length) { dispatch({ type: "invalid", step, errors }); return false; }
    const data = toPayload(step, s.draft);
    if (s.saved && samePayload(data, s.saved)) {
      dispatch({ type: "saved", step, data: s.saved }); // typed back to the saved value: nothing to send
      return true;
    }
    dispatch({ type: "saving", step });
    try {
      const r = await api.saveStep(id, step, data);
      dispatch({ type: "saved", step, data: r.data });
      return true;
    } catch (e) {
      if (e instanceof ApiError && e.fieldErrors) {
        dispatch({ type: "rejected", step, errors: Object.fromEntries(Object.entries(e.fieldErrors).map(([f, m]) => [f, serverMessage(m)])) });
      }
      else if (e instanceof ApiError && e.status === 404) dispatch({ type: "failed", step, message: "We couldn’t find this account." });
      else dispatch({ type: "failed", step, message: "We couldn’t reach the server. Your changes are kept on this page." });
      return false;
    }
  }, [id, dispatch]);

  /**
   * Save a step now. If one is already running, queue exactly one follow-up and share its result.
   *
   * Step 4 waits for steps 1 to 3. Once the server holds step 4 it refuses step 2 for good, so
   * letting step 4 overtake an unsaved step 2 would leave the account impossible to finish.
   */
  const save = useCallback((step: StepNo): Promise<boolean> => {
    const running = inflight.current[step];
    if (running) { queued.current[step] = true; return running; }
    const p = (async () => {
      try {
        if (step === 4 && ref.current.steps[4].saved === null) {
          for (const n of [1, 2, 3] as StepNo[]) {
            const s = ref.current.steps[n];
            if ((needsSave(s, n) || s.status !== "clean") && !(await save(n))) return false;
          }
        }
        let ok = await once(step);
        while (ok && queued.current[step]) { queued.current[step] = false; ok = await once(step); }
        queued.current[step] = false;
        return ok;
      } finally { delete inflight.current[step]; }
    })();
    inflight.current[step] = p;
    return p;
  }, [once]);

  /** Save everything outstanding, in order, stopping at the first refusal. Null means all saved. */
  const saveAll = useCallback(async (): Promise<StepNo | null> => {
    for (const n of STEPS) {
      const s = ref.current.steps[n];
      if ((needsSave(s, n) || s.status !== "clean") && !(await save(n))) return n;
    }
    return readyToSubmit(ref.current) ? null : STEPS.find((n) => ref.current.steps[n].status !== "clean") ?? 1;
  }, [save]);

  // ---- autosave: after a pause, for edited steps whose values pass local checks ----
  const timers = useRef<Partial<Record<StepNo, ReturnType<typeof setTimeout>>>>({});
  const edit = useCallback((step: StepNo, field: string, value: string) => {
    dispatch({ type: "edit", step, field, value });
    clearTimeout(timers.current[step]);
    timers.current[step] = setTimeout(() => {
      const s = ref.current.steps[step];
      if (Object.keys(validate(step, s.draft)).length === 0) void save(step);
    }, AUTOSAVE_MS);
  }, [dispatch, save]);

  /** Leaving a step or the page: send pending edits now instead of waiting for the pause. */
  const flush = useCallback((step: StepNo) => {
    clearTimeout(timers.current[step]);
    const s = ref.current.steps[step];
    if (s.status === "dirty" && Object.keys(validate(step, s.draft)).length === 0) void save(step);
  }, [save]);

  useEffect(() => () => {
    Object.values(timers.current).forEach(clearTimeout);
    for (const n of STEPS) {
      const s = ref.current.steps[n];
      if (s.status === "dirty" && Object.keys(validate(n, s.draft)).length === 0) void save(n);
    }
  }, [save]);

  // warn before closing the tab while something is unsaved
  useEffect(() => {
    const h = (e: BeforeUnloadEvent) => {
      if (STEPS.some((n) => ["dirty", "saving", "failed", "invalid"].includes(ref.current.steps[n].status))) e.preventDefault();
    };
    window.addEventListener("beforeunload", h);
    return () => window.removeEventListener("beforeunload", h);
  }, []);

  const revert = useCallback((step: StepNo) => { clearTimeout(timers.current[step]); dispatch({ type: "revert", step }); }, [dispatch]);
  const dismissRecovered = useCallback(() => dispatch({ type: "dismissRecovered" }), [dispatch]);
  const discardAllUnsaved = useCallback(() => {
    for (const n of STEPS) if (ref.current.steps[n].status !== "clean") revert(n);
    dispatch({ type: "dismissRecovered" });
  }, [revert, dispatch]);
  const retryLoad = useCallback(() => setLoadTick((t) => t + 1), []);

  return { state, load, account, edit, save, saveAll, flush, revert, dismissRecovered, discardAllUnsaved, retryLoad };
}
