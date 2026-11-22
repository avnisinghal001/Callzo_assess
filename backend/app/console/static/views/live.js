// The whole fleet at a glance. Everything comes from shared tables, so it is the same whichever
// server answers.
import { onOverview } from "../lib/api.js";
import { bars, gauge, spark } from "../lib/charts.js";
import { empty, face, failure, h, icon, skeletons } from "../lib/dom.js";
import { ago, clock, compact, count, plural } from "../lib/format.js";
import { pollOverview } from "../lib/api.js";

const REFUSED = ["invalid_signature", "validation_error", "bad_request", "payload_too_large", "conflict"];
const METRICS = [
  ["accepted", "New messages", "inbox", "indigo", (o) => o.accepted ?? 0],
  ["duplicate", "Copies ignored", "copy", "teal", (o) => o.duplicate ?? 0],
  ["refused", "Refused", "shield", "orange", (o) => REFUSED.reduce((n, k) => n + (o[k] ?? 0), 0)],
  ["retry", "Asked to retry", "refresh", "pink", (o) => o.unavailable ?? 0],
].map(([id, label, iconName, color, of]) => ({ id, label, icon: iconName, color, of }));
const JOBS = { reconcile_check: ["Check every total", "scale"], retention: ["Clear old statistics", "trash"] };

export function live(root, { signal }) {
  let metric = METRICS[0], data = null, drawn = "";
  const tiles = h("div", { class: "metrics", role: "group", "aria-label": "Choose what the chart shows" });
  const chart = h("section", { class: "card", "aria-label": "Traffic" });
  const share = h("aside", { class: "card", "aria-label": "Outcomes" });
  const lower = h("div", { class: "cols3" });
  const updated = h("p", { class: "row small muted" });
  root.replaceChildren(h("div", { class: "head" }, h("div", {}, h("h1", {}, "Live"), h("p", {}, "What every server has been doing in the last half hour.")), updated), tiles, h("div", { class: "cols" }, chart, share), lower);
  chart.replaceChildren(skeletons(4));

  const minutesOf = () => {
    const known = new Map(data.traffic.map((t) => [Math.floor(Date.parse(t.minute) / 60000), t.outcomes]));
    const now = Math.floor(Date.parse(data.server_time) / 60000);
    return Array.from({ length: data.traffic_minutes }, (_, i) => { const m = now - data.traffic_minutes + 1 + i; return { at: new Date(m * 60000), outcomes: known.get(m) ?? {} }; });
  };

  function paint() {
    const series = minutesOf();
    const totals = METRICS.map((m) => series.reduce((n, x) => n + m.of(x.outcomes), 0));
    const focused = document.activeElement?.dataset?.metric;
    tiles.replaceChildren(...METRICS.map((m, i) => h("button", { type: "button", class: `metric c-${m.color}`, "data-metric": m.id, "aria-pressed": String(m === metric), onclick: () => { metric = m; paint(); tiles.querySelector(`[data-metric=${m.id}]`).focus(); } },
      spark(series.map((x) => m.of(x.outcomes))), h("span", { class: "badge" }, icon(m.icon, 21)), h("span", { class: "l" }, m.label), h("b", { class: "num" }, compact(totals[i])))));
    if (focused) tiles.querySelector(`[data-metric=${focused}]`)?.focus();

    const index = METRICS.indexOf(metric);
    chart.replaceChildren(h("h3", {}, metric.label), h("p", { class: "num", style: { "font-size": "1.9rem", "font-weight": "750", "letter-spacing": "-.03em", "line-height": "1.2" } }, count(totals[index])), h("p", { class: "small muted" }, "per minute, last 30 minutes"),
      bars(series.map((x, i) => ({ value: metric.of(x.outcomes), title: clock(x.at), label: i % 6 === 0 || i === series.length - 1 ? clock(x.at) : "" })), { color: `var(--${metric.color})`, format: count, label: metric.label }));

    const all = totals.reduce((a, b) => a + b, 0);
    share.replaceChildren(h("h3", {}, "What happened to them?"), all
      ? gauge(METRICS.map((m, i) => ({ value: totals[i], color: `var(--${m.color})` })), compact(all), "messages")
      : empty("asleep", "Quiet right now", "Nothing in the last half hour.", h("a", { class: "btn sm", href: "#/simulator" }, icon("play", 16), "Send some")),
      all ? h("ul", { class: "list" }, METRICS.map((m, i) => h("li", { class: "item" }, h("span", { class: "swatch", style: { background: `color-mix(in srgb, var(--${m.color}) 15%, white)`, color: `var(--${m.color})` } }, icon(m.icon, 17)), h("span", { class: "grow" }, m.label), h("span", { class: "num" }, count(totals[i]))))) : "");
  }

  function paintLower() {
    const { inbox, instances, jobs, pool_max_size: max } = data;
    const row = (href, tone, iconName, label, hint, value) => h(href ? "a" : "div", { class: "item", href }, h("span", { class: `swatch ${tone}` }, icon(iconName, 17)), h("span", { class: "grow" }, label, h("small", {}, hint)), h("span", { class: "num" }, value), href && icon("right", 16));
    const workers = instances.filter((i) => i.role === "worker"), servers = instances.filter((i) => i.role === "api");
    const person = (i) => {
      const detail = !i.alive ? `silent for ${Math.round(i.silent_seconds)} s` : i.role === "worker" ? `${plural(i.metadata.events_handled ?? 0, "event")} handled` : `${i.metadata.pool_size ?? 0} of ${max} connections, ${i.metadata.requests_waiting ?? 0} waiting`;
      return h("li", { class: "item" }, face(i.instance, i.alive ? "happy" : "asleep", 34), h("span", { class: "grow" }, i.role === "api" ? "API server" : "Worker", h("small", {}, detail)), h("span", { class: `chip ${i.alive ? "ok" : "bad"}` }, i.alive ? "Awake" : "Silent"));
    };
    lower.replaceChildren(
      h("section", { class: "card" }, h("h3", {}, "The queue"), h("div", { class: "list" },
        row("#/events/pending", inbox.pending ? "wait" : "ok", "inbox", "Waiting to be counted", inbox.pending ? "workers are on it" : "all caught up", count(inbox.pending)),
        row("#/events/dead", inbox.dead ? "bad" : "ok", "alert", "Gave up", inbox.dead ? "needs a person" : "none, as it should be", count(inbox.dead)),
        row(null, inbox.oldest_due_seconds > 30 ? "bad" : "ok", "clock", "Longest wait", "how far behind workers are", `${inbox.oldest_due_seconds.toFixed(1)} s`))),
      h("section", { class: "card" }, h("h3", {}, `The team: ${plural(servers.filter((i) => i.alive).length, "server")}, ${plural(workers.filter((i) => i.alive).length, "worker")} awake`),
        instances.length ? h("ul", { class: "list" }, [...servers, ...workers].slice(0, 12).map(person)) : empty("asleep", "Nobody is awake", "Start a worker and it will show up here.")),
      h("section", { class: "card" }, h("h3", {}, "Housekeeping"), h("div", { class: "list" }, jobs.map((j) => {
        const [label, iconName] = JOBS[j.name] ?? [j.name, "clock"];
        const r = j.last_result, drifted = r.accounts_drifted?.length ?? 0;
        const hint = !j.last_run_at ? `first run ${clock(j.next_run_at)}` : r.ok === false ? `failed ${ago(j.last_run_at)}` : j.name === "reconcile_check" ? `${plural(r.accounts_checked ?? 0, "account")}, ${drifted ? `${drifted} differ` : "all match"}, ${ago(j.last_run_at)}` : `done ${ago(j.last_run_at)}`;
        return row(null, r.ok === false || drifted ? "bad" : "ok", iconName, label, hint, "");
      }), row("#/history", "info", "history", "History of changes", "who did what, and when", ""))));
  }

  const off = onOverview((next, error) => {
    if (error) {
      updated.replaceChildren(h("span", { class: "dot bad" }), data ? `Reconnecting. Showing ${clock(data.server_time)}` : "Reconnecting");
      if (!data) chart.replaceChildren(failure(error, pollOverview));
      return;
    }
    data = next;
    updated.replaceChildren(h("span", { class: "dot ok" }), `Live, ${clock(data.server_time)}`);
    const key = JSON.stringify([data.traffic, Math.floor(Date.parse(data.server_time) / 60000)]);
    if (key !== drawn && !root.querySelector(".bar:hover")) { drawn = key; paint(); } // never redraw under the pointer
    paintLower();
  });
  signal.addEventListener("abort", off);
}
