import type { SavedSettings, StepData } from "../api/types.ts";
import { blankDraft, fromServer, samePayload, savedFromServer, STEPS, toPayload, type Draft, type StepNo } from "./model.ts";

/**
 * Per step we keep three separate things, so an unsaved value is never mistaken for a saved one:
 *  saved  - the last payload the SERVER confirmed (null = never saved)
 *  draft  - what is typed in the form right now
 *  status - how the two relate
 */
export type StepStatus = "clean" | "dirty" | "saving" | "invalid" | "failed";

export interface StepState {
  saved: StepData | null;
  draft: Draft;
  status: StepStatus;
  /** Field errors, from local validation or from a 422. */
  errors: Record<string, string>;
  /** Non-field problem, e.g. the server was unreachable. */
  message: string;
}

export interface SettingsState {
  steps: Record<StepNo, StepState>;
  /** Unfinished edits were restored from this browser tab after a refresh. */
  recovered: boolean;
}

export type Action =
  | { type: "loaded"; saved: SavedSettings; defaults: Partial<Record<StepNo, Draft>>; recovered: Partial<Record<StepNo, Draft>> }
  | { type: "edit"; step: StepNo; field: string; value: string }
  | { type: "saving"; step: StepNo }
  | { type: "saved"; step: StepNo; data: StepData }
  | { type: "invalid"; step: StepNo; errors: Record<string, string> }
  | { type: "rejected"; step: StepNo; errors: Record<string, string> }
  | { type: "failed"; step: StepNo; message: string }
  | { type: "revert"; step: StepNo }
  | { type: "dismissRecovered" };

const emptyStep = (step: StepNo): StepState => ({ saved: null, draft: blankDraft(step), status: "clean", errors: {}, message: "" });

export const initialState = (): SettingsState => ({
  steps: { 1: emptyStep(1), 2: emptyStep(2), 3: emptyStep(3), 4: emptyStep(4) },
  recovered: false,
});

/** Is the form different from what the server holds? A never-saved step with typed values counts too. */
export function isDirty(s: StepState, step: StepNo): boolean {
  return s.saved === null ? false : !samePayload(toPayload(step, s.draft), s.saved);
}

/** Needs a PUT: never saved, or changed since. Unchanged saved steps are never re-sent. */
export const needsSave = (s: StepState, step: StepNo) => s.saved === null || isDirty(s, step);

const patch = (st: SettingsState, step: StepNo, p: Partial<StepState>): SettingsState => ({
  ...st, steps: { ...st.steps, [step]: { ...st.steps[step], ...p } },
});

export function reducer(st: SettingsState, a: Action): SettingsState {
  switch (a.type) {
    case "loaded": {
      const steps = { ...st.steps };
      let recovered = false;
      for (const n of STEPS) {
        const saved = savedFromServer(a.saved, n);
        let draft = saved ? fromServer(n, saved) : a.defaults[n] ?? blankDraft(n);
        let status: StepStatus = "clean";
        const r = a.recovered[n];
        if (r && !samePayload(toPayload(n, r), saved ?? toPayload(n, draft))) {
          draft = r; status = "dirty"; recovered = true;
        }
        steps[n] = { saved, draft, status, errors: {}, message: "" };
      }
      return { steps, recovered };
    }
    case "edit": {
      const s = st.steps[a.step];
      const draft = { ...s.draft, [a.field]: a.value };
      const { [a.field]: _gone, ...errors } = s.errors;
      const status: StepStatus = s.status === "saving" ? "saving" : "dirty";
      return patch(st, a.step, { draft, errors, message: "", status });
    }
    case "saving":
      return patch(st, a.step, { status: "saving", errors: {}, message: "" });
    case "saved": {
      // Compare with what is typed NOW: if the user kept typing during the request, stay dirty.
      const s = st.steps[a.step];
      const same = samePayload(toPayload(a.step, s.draft), a.data);
      const next = patch(st, a.step, { saved: a.data, status: same ? "clean" : "dirty", errors: {}, message: "" });
      // Once nothing is outstanding, "we kept your unfinished changes" is no longer true.
      return { ...next, recovered: next.recovered && STEPS.some((n) => next.steps[n].status !== "clean") };
    }
    case "invalid":
      return patch(st, a.step, { status: "invalid", errors: a.errors, message: "" });
    case "rejected":
      // The server said no. `saved` is untouched: we never claim the rejected value was stored.
      return patch(st, a.step, { status: "failed", errors: a.errors, message: "" });
    case "failed":
      return patch(st, a.step, { status: "failed", message: a.message });
    case "revert": {
      const s = st.steps[a.step];
      return patch(st, a.step, { draft: s.saved ? fromServer(a.step, s.saved) : blankDraft(a.step), status: "clean", errors: {}, message: "" });
    }
    case "dismissRecovered":
      return { ...st, recovered: false };
  }
}

/** True once the server holds step 4 but not step 2: the deliberate API quirk made step 2 unsavable. */
export const deadEnd = (st: SettingsState) => st.steps[4].saved !== null && st.steps[2].saved === null;

/** Every step confirmed by the server and nothing waiting to be saved. */
export const readyToSubmit = (st: SettingsState) =>
  STEPS.every((n) => st.steps[n].saved !== null && st.steps[n].status === "clean" && !isDirty(st.steps[n], n));

export const stepsOneToThreeSaved = (st: SettingsState) => ([1, 2, 3] as StepNo[]).every((n) => st.steps[n].saved !== null);
