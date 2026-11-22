import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { api, ApiError } from "../api/client.ts";
import { countryName, flag, formatCount, PLAN_LABEL } from "../lib/format.ts";
import { Avatar } from "../ui/Avatar.tsx";
import { ChoiceField, TextField } from "../ui/Field.tsx";
import { Icon, type IconName } from "../ui/Icon.tsx";
import { Banner, Button, Skeleton } from "../ui/primitives.tsx";
import { BILLING_COUNTRIES, PLANS, STEP_TITLES, STEPS, type StepNo } from "./model.ts";
import { deadEnd, needsSave, stepsOneToThreeSaved, type StepState } from "./reducer.ts";
import { useSettings } from "./useSettings.ts";

function saveLabel(s: StepState): { text: string; icon: IconName; cls: string } {
  if (s.status === "saving") return { text: "Saving changes…", icon: "spinner", cls: "bg-primary-soft text-primary-strong" };
  if (s.status === "failed") return { text: "Not saved", icon: "error", cls: "bg-suspended-soft text-suspended-ink" };
  if (s.status === "invalid") return { text: "Needs a fix", icon: "warning", cls: "bg-trial-soft text-trial-ink" };
  if (s.status === "dirty") return { text: "Not saved yet", icon: "clock", cls: "bg-trial-soft text-trial-ink" };
  if (s.saved) return { text: "All changes saved", icon: "success", cls: "bg-active-soft text-active-ink" };
  return { text: "Not saved yet", icon: "clock", cls: "bg-card text-muted" };
}

type Submit =
  | { kind: "idle" | "busy" | "done" }
  | { kind: "missing" | "blocked"; steps: StepNo[] }
  | { kind: "error"; message: string };

export function SettingsPage({ id, step, onStep, onExit }: { id: number; step: StepNo; onStep: (s: StepNo) => void; onExit: () => void }) {
  const S = useSettings(id);
  const { state, account } = S;
  const [submitted, setSubmitted] = useState<Submit>({ kind: "idle" });
  const heading = useRef<HTMLHeadingElement>(null);
  const form = useRef<HTMLFormElement>(null);
  const done = submitted.kind === "done";

  const step4Open = stepsOneToThreeSaved(state);
  // A link straight to step 4 must not skip the steps it depends on.
  const blockedLink = S.load === "ready" && step === 4 && !step4Open && state.steps[4].saved === null;
  const firstOpen = STEPS.find((n) => state.steps[n].saved === null) ?? 1;
  useEffect(() => { if (blockedLink) onStep(firstOpen); }, [blockedLink, firstOpen, onStep]);

  useEffect(() => { heading.current?.focus(); }, [step, S.load, done]);

  // Runs after React has rendered the errors, so there is always something to focus.
  const [errorTick, setErrorTick] = useState(0);
  const focusError = () => setErrorTick((t) => t + 1);
  useLayoutEffect(() => {
    if (!errorTick) return;
    const bad = form.current?.querySelector<HTMLElement>("[aria-invalid='true']");
    (bad?.matches("input") ? bad : bad?.querySelector<HTMLElement>("input"))?.focus();
  }, [errorTick]);

  const goTo = (n: StepNo) => { S.flush(step); setSubmitted({ kind: "idle" }); onStep(n); };

  const next = async () => {
    // Optional steps are sent once even when empty, because submitting needs all four saved.
    const s = state.steps[step];
    if ((needsSave(s, step) || s.status !== "clean") && !(await S.save(step))) { focusError(); return; }
    if (step < 4) onStep((step + 1) as StepNo);
  };

  const submit = async () => {
    setSubmitted({ kind: "busy" });
    const refused = await S.saveAll();
    if (refused) {
      setSubmitted({ kind: "blocked", steps: [refused] });
      if (refused === step) focusError();
      return;
    }
    try {
      await api.submit(id);
      setSubmitted({ kind: "done" });
    } catch (e) {
      if (e instanceof ApiError && e.missingSteps) setSubmitted({ kind: "missing", steps: e.missingSteps as StepNo[] });
      else setSubmitted({ kind: "error", message: e instanceof ApiError && e.status === 404 ? "We couldn’t find this account." : "We couldn’t reach the server. Your saved settings are safe." });
    }
  };

  if (S.load !== "ready") {
    return (
      <Shell onExit={onExit}>
        <div className="mx-auto w-full max-w-2xl rounded-3xl bg-card p-6 sm:p-10">
          {S.load === "loading" ? (
            <div className="grid gap-4" aria-busy="true"><h1 ref={heading} tabIndex={-1} className="sr-only">Loading settings</h1>
              <Skeleton className="h-8 w-1/2" /><Skeleton className="h-12" /><Skeleton className="h-12" /></div>
          ) : (
            <div role="alert" className="grid justify-items-center gap-2 text-center">
              <span className="pop grid size-16 place-items-center rounded-3xl bg-primary-soft text-primary"><Icon name="moon" size={30} /></span>
              <h1 ref={heading} tabIndex={-1} className="mt-2 text-xl font-bold outline-none">{S.load === "notfound" ? "We couldn’t find this account" : "We couldn’t load these settings"}</h1>
              <p className="text-muted">{S.load === "notfound" ? "It may have been removed, or the link may be wrong." : "Nothing has changed. Give it another go."}</p>
              {S.load === "notfound" ? <Button variant="primary" className="mt-2" onClick={onExit}>Back to accounts</Button>
                : <Button variant="primary" icon="refresh" className="mt-2" onClick={S.retryLoad}>Try again</Button>}
            </div>
          )}
        </div>
      </Shell>
    );
  }

  const title = account?.company ?? `Account ${id}`;

  if (done) {
    return (
      <Shell onExit={onExit}>
        <div role="status" className="relative mx-auto grid w-full max-w-2xl justify-items-center gap-3 overflow-hidden rounded-3xl bg-gradient-to-br from-[#c9f2c0] to-[#e9fbd9] px-6 py-16 text-center">
          <Confetti />
          <span className="pop relative">{account ? <Avatar id={id} status="active" size={96} /> : <Icon name="party" size={72} />}</span>
          <h1 ref={heading} tabIndex={-1} className="relative text-3xl font-bold tracking-tight">Settings updated</h1>
          <p className="text-ink/75">Everything is saved for {title}.</p>
          <div className="mt-2 flex flex-wrap justify-center gap-2">
            <Button variant="primary" onClick={onExit}>Back to accounts</Button>
            <Button onClick={() => { setSubmitted({ kind: "idle" }); onStep(1); }}>Review settings</Button>
          </div>
        </div>
      </Shell>
    );
  }

  const cur = state.steps[step];
  const t = STEP_TITLES[step];
  const label = saveLabel(cur);
  const put = (f: string) => (v: string) => { setSubmitted((s) => (s.kind === "idle" ? s : { kind: "idle" })); S.edit(step, f, v); };
  const savedCount = STEPS.filter((n) => state.steps[n].saved).length;
  const refused = cur.status === "failed";
  const billing = state.steps[2].saved?.billing_country;

  return (
    <Shell onExit={onExit}>
      <div className="grid gap-4 lg:grid-cols-[300px_minmax(0,1fr)] lg:items-start">
        <aside className="grid gap-4 rounded-3xl bg-card p-4 sm:p-5 lg:sticky lg:top-4">
          <div className="flex items-center gap-3">
            {account && <span className="group pop"><Avatar id={id} status={account.status} size={56} /></span>}
            <div className="min-w-0"><p className="truncate text-lg font-bold tracking-tight">{title}</p><p className="tnum text-sm text-muted">{savedCount} of 4 saved</p></div>
            <Ring n={savedCount} />
          </div>
          <nav aria-label="Settings steps">
            <ol className="grid grid-cols-4 gap-2 lg:grid-cols-1">
              {STEPS.map((n) => {
                const s = state.steps[n];
                const locked = n === 4 && !step4Open && s.saved === null;
                const bad = s.status === "failed" || s.status === "invalid";
                const ok = s.saved !== null && s.status === "clean";
                const on = n === step;
                return (
                  <li key={n} className="min-w-0">
                    <button type="button" disabled={locked} aria-current={on ? "step" : undefined} onClick={() => goTo(n)}
                      className={`group flex min-h-16 w-full flex-col items-center justify-center gap-1 rounded-2xl p-2 text-xs font-semibold transition-[background,box-shadow] disabled:opacity-45 lg:min-h-14 lg:flex-row lg:justify-start lg:gap-3 lg:text-left lg:text-sm ${on ? "bg-tile shadow-tile" : "hover:bg-ink/5"}`}>
                      <span className={`face grid size-9 shrink-0 place-items-center rounded-xl transition-colors ${bad ? "bg-suspended text-white" : ok ? "bg-active-soft text-active-ink" : on ? "bg-primary text-white" : "bg-track text-muted"}`}>
                        <Icon key={bad ? "b" : ok ? "o" : "i"} name={bad ? "warning" : ok ? "check" : STEP_TITLES[n].icon} size={19} strokeWidth={ok ? 2.6 : 1.8} className="pop" />
                      </span>
                      <span className="min-w-0 truncate lg:flex-1">{STEP_TITLES[n].short}</span>
                      <span className="sr-only">. {locked ? "Opens after steps 1 to 3 are saved" : saveLabel(s).text}</span>
                    </button>
                  </li>
                );
              })}
            </ol>
          </nav>
        </aside>

        <div className="grid min-w-0 gap-3">
          {state.recovered && (
            <Banner role="status" title="We kept your unfinished changes" actions={<>
              <Button variant="ghost" onClick={S.discardAllUnsaved}>Discard</Button><Button onClick={S.dismissRecovered}>Keep editing</Button></>}>
              They aren’t saved yet.
            </Banner>
          )}
          {deadEnd(state) && (
            <Banner tone="warning" title="Billing can’t be saved for this account">
              The last step was saved before this one, and the server no longer accepts billing details. What you enter is kept here, but these settings can’t be submitted.
            </Banner>
          )}
          {(submitted.kind === "missing" || submitted.kind === "blocked") && (
            <Banner tone="warning" role="alert" title={submitted.kind === "missing" ? "Some steps still need saving" : "Not submitted yet. A change couldn’t be saved."}
              actions={submitted.steps.filter((n) => n !== step).map((n) => <Button key={n} icon={STEP_TITLES[n].icon} onClick={() => goTo(n)}>Go to {STEP_TITLES[n].short}</Button>)} />
          )}
          {submitted.kind === "error" && <Banner tone="danger" role="alert" actions={<Button icon="refresh" onClick={submit}>Try again</Button>}>{submitted.message}</Banner>}

          <section className="rounded-3xl border border-line bg-tile p-5 sm:p-8">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <p className="text-sm font-semibold text-muted">Step {step} of 4</p>
                <h1 ref={heading} tabIndex={-1} className="text-2xl font-bold tracking-tight outline-none sm:text-3xl">{t.title}</h1>
                <p className="mt-1 text-muted">{t.intro}</p>
              </div>
              <p role="status" className={`inline-flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-sm font-semibold transition-colors ${label.cls}`}><Icon key={label.icon} name={label.icon} size={17} className="pop" />{label.text}</p>
            </div>

            {refused && (
              <div className="mt-5">
                <Banner tone="danger" role="alert" title={cur.message || "This change couldn’t be saved"} actions={<>
                  <Button icon="refresh" onClick={() => void S.save(step)}>Try again</Button>
                  {cur.saved && <Button icon="undo" onClick={() => S.revert(step)}>Restore saved value</Button>}</>}>
                  {step === 2 && billing ? <>Your saved settings are safe. Billing is still {flag(String(billing))} <strong>{countryName(String(billing))}</strong>.</> : "Your saved settings are safe."}
                </Banner>
              </div>
            )}

            <form key={step} ref={form} noValidate className="rise mt-6 grid gap-6" onSubmit={(e) => { e.preventDefault(); void (step === 4 ? submit() : next()); }}>
              {step === 1 && <>
                <TextField label="Contact name" icon="smile" value={cur.draft.name} onValue={put("name")} error={cur.errors.name} />
                <TextField label="Email" icon="mail" type="email" value={cur.draft.email} onValue={put("email")} error={cur.errors.email} />
              </>}
              {step === 2 && <>
                <ChoiceField label="Plan" className="sm:grid-cols-3" value={cur.draft.plan} onValue={put("plan")} error={cur.errors.plan}
                  options={PLANS.map((p) => ({ value: p, label: PLAN_LABEL[p], icon: p }))} />
                <ChoiceField label="Billing country" className="grid-cols-2 xl:grid-cols-3" value={cur.draft.billing_country} onValue={put("billing_country")} error={cur.errors.billing_country}
                  options={BILLING_COUNTRIES.map((c) => ({ value: c, label: countryName(c), emoji: flag(c) }))} />
              </>}
              {step === 3 && <>
                <CapField label="Calling minutes a month" icon="ringing" presets={[500, 1000, 5000]} value={cur.draft.minutes_cap} onValue={put("minutes_cap")} error={cur.errors.minutes_cap} />
                <CapField label="Texts a month" icon="sms" presets={[100, 500, 1000]} value={cur.draft.sms_cap} onValue={put("sms_cap")} error={cur.errors.sms_cap} />
              </>}
              {step === 4 && <TextField label="Web address" icon="webhook" type="url" inputMode="url" placeholder="https://example.com/calls" value={cur.draft.webhook_url} onValue={put("webhook_url")} error={cur.errors.webhook_url} />}

              <div className="flex items-center justify-between gap-3">
                <Button icon="back" disabled={step === 1} onClick={() => goTo((step - 1) as StepNo)}>Back</Button>
                {step < 4
                  ? <Button variant="primary" type="submit" busy={cur.status === "saving"} className="min-w-32">Continue<Icon name="next" size={18} /></Button>
                  : <Button variant="primary" type="submit" icon="party" busy={submitted.kind === "busy"} disabled={deadEnd(state)}>Finish</Button>}
              </div>
            </form>
          </section>
          <p className="flex items-center justify-center gap-1.5 text-sm text-muted"><Icon name="shield" size={16} />Changes save by themselves as you go.</p>
        </div>
      </div>
    </Shell>
  );
}

function CapField({ label, icon, presets, value, onValue, error }: { label: string; icon: IconName; presets: number[]; value: string; onValue: (v: string) => void; error?: string }) {
  const chip = (text: ReactNode, v: string) => (
    <button key={v || "none"} type="button" aria-pressed={value.trim() === v} onClick={() => onValue(v)}
      className={`tnum inline-flex min-h-11 items-center gap-1.5 rounded-xl px-3.5 text-sm font-semibold transition-[background,color,transform] active:scale-95 ${value.trim() === v ? "bg-primary text-white" : "bg-card hover:bg-track"}`}>{text}</button>
  );
  return (
    <div className="grid gap-2">
      <TextField label={label} icon={icon} inputMode="numeric" placeholder="No cap" value={value} onValue={onValue} error={error} />
      <div role="group" aria-label={`${label}, quick choices`} className="flex flex-wrap gap-2">
        {chip(<><Icon name="infinity" size={17} />No cap</>, "")}
        {presets.map((n) => chip(formatCount(n), String(n)))}
      </div>
    </div>
  );
}

function Ring({ n }: { n: number }) {
  const c = 2 * Math.PI * 15;
  return (
    <svg viewBox="0 0 40 40" className="ml-auto size-11 shrink-0 -rotate-90" aria-hidden="true">
      <circle cx="20" cy="20" r="15" fill="none" stroke="var(--color-track)" strokeWidth="6" />
      {n > 0 && <circle cx="20" cy="20" r="15" fill="none" stroke="var(--color-active)" strokeWidth="6" strokeLinecap="round" strokeDasharray={`${(c * n) / 4} ${c}`} style={{ transition: "stroke-dasharray 500ms var(--ease-spring)" }} />}
    </svg>
  );
}

const CONFETTI = ["#4f46e5", "#0284a8", "#d9480f", "#e0318c", "#f5a50b", "#16a34a"];
function Confetti() {
  return (
    <div aria-hidden="true" className="pointer-events-none absolute left-1/2 top-28">
      {Array.from({ length: 36 }, (_, i) => {
        const angle = (i / 36) * Math.PI * 2;
        const far = 130 + ((i * 53) % 130);
        return <span key={i} className="confetti absolute block h-3.5 w-2 rounded-sm" style={{
          background: CONFETTI[i % CONFETTI.length], animationDelay: `${(i % 6) * 30}ms`,
          "--dx": `${Math.cos(angle) * far}px`, "--dy": `${Math.sin(angle) * far + 70}px`, "--rot": `${(i * 97) % 540}deg`,
        } as CSSProperties} />;
      })}
    </div>
  );
}

function Shell({ onExit, children }: { onExit: () => void; children: ReactNode }) {
  return (
    <div className="mx-auto w-full max-w-5xl">
      <Button variant="ghost" icon="back" className="-ml-3 mb-3" onClick={onExit}>Back to accounts</Button>
      {children}
    </div>
  );
}
