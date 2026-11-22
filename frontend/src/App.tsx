import { useCallback, useEffect, useRef, useState } from "react";
import { AccountsPage } from "./accounts/AccountsPage.tsx";
import { PeriodPicker } from "./accounts/PeriodPicker.tsx";
import { useUrlState } from "./hooks/useUrlState.ts";
import { METRIC_KEYS, type MetricKey } from "./lib/metrics.ts";
import { parseListQuery } from "./lib/query.ts";
import { loadSelection, storeSelection, type Selection } from "./lib/selection.ts";
import type { StepNo } from "./settings/model.ts";
import { SettingsPage } from "./settings/SettingsPage.tsx";
import { Activity } from "./summary/Activity.tsx";
import { StatusGauge } from "./summary/StatusGauge.tsx";
import { Icon } from "./ui/Icon.tsx";

const positiveInt = (v: string | null) => (v && /^\d+$/.test(v) && Number(v) > 0 ? Number(v) : null);

export function App() {
  const { params, update } = useUrlState();
  const query = parseListQuery(params);
  const [selection, setSelectionState] = useState<Selection>(loadSelection);
  const setSelection = useCallback((fn: (s: Selection) => Selection) => setSelectionState(fn), []);
  useEffect(() => storeSelection(selection), [selection]);

  const openId = positiveInt(params.get("account"));
  const settingsId = positiveInt(params.get("settings"));
  const stepRaw = Number(params.get("step"));
  const step = ([1, 2, 3, 4].includes(stepRaw) ? stepRaw : 1) as StepNo;
  const metricRaw = params.get("metric") as MetricKey;
  const metric = METRIC_KEYS.includes(metricRaw) ? metricRaw : "minutes";
  const onDashboard = settingsId === null;

  // The dashboard stays mounted (hidden) while settings are open, so filters and scroll survive.
  const scroll = useRef(0);
  const openSettings = (id: number) => {
    scroll.current = window.scrollY;
    update({ settings: id, step: 1, account: undefined });
  };
  useEffect(() => { window.scrollTo(0, onDashboard ? scroll.current : 0); }, [onDashboard]);

  return (
    <div className="min-h-dvh">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50 focus:rounded-xl focus:bg-ink focus:px-4 focus:py-2 focus:text-white">Skip to content</a>
      <header className="mx-auto flex max-w-[1320px] items-center gap-2.5 px-4 pt-4 sm:px-6">
        <span className="grid size-10 place-items-center rounded-2xl bg-[#086f87] text-white"><Icon name="call" size={21} strokeWidth={2} /></span>
        <span className="text-xl font-bold tracking-tight">Callzo</span>
        <span className="ml-1 rounded-lg bg-card px-2 py-1 text-xs font-semibold text-muted">Admin</span>
      </header>

      <main id="main" className="mx-auto max-w-[1320px] px-4 pb-28 pt-5 sm:px-6">
        {settingsId !== null && (
          <SettingsPage key={settingsId} id={settingsId} step={step}
            onStep={(s) => update({ step: s })} onExit={() => update({ settings: undefined, step: undefined })} />
        )}
        <div hidden={!onDashboard}>
          <div className="grid grid-cols-1 gap-3">
            <div className="mb-1 flex flex-wrap items-center justify-between gap-3">
              <h1 className="text-3xl font-bold tracking-tight sm:text-4xl">Usage &amp; accounts</h1>
              <PeriodPicker from={query.from} to={query.to} onChange={(from, to) => update({ from, to, page: undefined })} />
            </div>
            <Activity from={query.from} to={query.to} metric={metric} active={onDashboard}
              onMetric={(m) => update({ metric: m === "minutes" ? undefined : m }, { replace: true })}
              onZoom={(from, to) => update({ from, to, page: undefined })}
              side={<StatusGauge query={query} active={onDashboard} onPick={(s) => update({ status: s, page: undefined })} />} />
            <AccountsPage query={query} update={update} selection={selection} setSelection={setSelection}
              openId={onDashboard ? openId : null} active={onDashboard} onSettings={openSettings} />
          </div>
        </div>
      </main>
    </div>
  );
}
