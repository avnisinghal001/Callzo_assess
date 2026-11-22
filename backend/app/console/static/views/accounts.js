import { allAccounts, api, enc } from "../lib/api.js";
import { bars } from "../lib/charts.js";
import { $, act, closeDrawer, confirmButton, empty, face, failure, h, icon, openDrawer, segmented, skeletons } from "../lib/dom.js";
import { ago, CAP, count, isoDay, minutes, money, plural, stamp } from "../lib/format.js";

export async function accounts(root, { signal, arg }) {
  let all = [], shelf = "live", text = "";
  const list = h("ul", { class: "rows" });
  const title = h("h2", {}, "Accounts");
  const form = newAccount(async (id) => { await load(); location.hash = `#/accounts/${enc(id)}`; });
  const search = h("input", { class: "input", type: "search", placeholder: "Find an account", "aria-label": "Find an account", oninput: (e) => { text = e.target.value.trim().toLowerCase(); paint(); } });
  root.replaceChildren(
    h("div", { class: "head" }, h("div", {}, h("h1", {}, "Accounts"), h("p", {}, "Monthly caps, what has been used, and who may still place calls.")),
      h("button", { type: "button", class: "btn primary", onclick: () => { form.hidden = !form.hidden; if (!form.hidden) form.querySelector("input").focus(); } }, icon("plus", 18), "New account")),
    form,
    h("section", { class: "sheet" }, h("header", {}, title, h("div", { class: "row", style: { flex: "1", "justify-content": "flex-end" } }, h("label", { class: "search" }, icon("search", 18), search), segmented("Show", [["live", "Active"], ["deleted", "Removed"]], shelf, (v) => { shelf = v; load(); }))), list));
  list.replaceChildren(h("li", {}, skeletons(6)));

  function paint() {
    const shown = all.filter((a) => a.external_id.toLowerCase().includes(text));
    title.textContent = plural(shown.length, "account");
    list.replaceChildren(...(shown.length ? shown.map(row) : [h("li", {}, empty("curious", text ? "No account by that name" : shelf === "live" ? "No accounts yet" : "Nothing removed", text ? "Try a shorter search." : shelf === "live" ? "Create the first one." : "Removed accounts land here and can be brought back."))]));
  }
  function row(a) {
    const [label, tone, mood] = a.deleted_at ? ["Removed", "", "asleep"] : CAP[a.month.status];
    const share = Math.min(100, (a.month.used_seconds / Math.max(1, a.monthly_cap_minutes * 60)) * 100);
    return h("li", {}, h("a", { class: "line", href: `#/accounts/${enc(a.external_id)}`, "data-account": a.external_id, "aria-label": `Open ${a.external_id}, ${label}` },
      h("div", { class: "who" }, face(a.external_id, mood), h("div", {}, h("strong", {}, a.metadata.name ?? a.external_id), h("small", {}, a.metadata.name ? a.external_id : a.deleted_at ? `removed ${ago(a.deleted_at)}` : `cap ${count(a.monthly_cap_minutes)} min`))),
      h("div", { class: `meter ${a.month.status}` }, h("span", { class: "rail" }, h("i", { style: { width: `${share}%` } })), h("span", { class: "num" }, minutes(a.month.used_seconds))),
      h("span", {}, h("span", { class: `chip ${tone}` }, label)), icon("right", 18)));
  }
  async function load() {
    try { all = await allAccounts(shelf === "deleted"); if (!signal.aborted) paint(); } catch (error) { list.replaceChildren(h("li", {}, failure(error, load))); }
  }
  await load();
  if (arg && !signal.aborted) await detail(arg, signal, load);
}

function newAccount(done) {
  const id = h("input", { class: "input", id: "new-id", required: true, maxlength: 128, pattern: "[A-Za-z0-9_.:\\-]+", placeholder: "acct_011", autocomplete: "off" });
  const cap = h("input", { class: "input", id: "new-cap", type: "number", min: 0, max: 44640, value: 200, required: true });
  return h("form", { class: "card rise", hidden: true, onsubmit: (e) => { e.preventDefault(); act(e.submitter, async () => { const a = await api("/admin/v1/accounts", { method: "POST", body: { external_id: id.value.trim(), monthly_cap_minutes: Number(cap.value) } }); id.value = ""; e.target.hidden = true; await done(a.external_id); return a; }, (a) => `${a.external_id} is ready`); } },
    h("div", { class: "row", style: { "align-items": "end" } }, h("label", { class: "field", style: { flex: "1 1 220px" } }, "Account id", id), h("label", { class: "field", style: { flex: "0 1 180px" } }, "Monthly cap (minutes)", cap), h("button", { class: "btn primary", type: "submit" }, "Create")));
}

async function detail(id, signal, refresh) {
  const path = `/admin/v1/accounts/${enc(id)}`, read = `/v1/accounts/${enc(id)}/usage`;
  const leave = () => { if (location.hash.startsWith("#/accounts/")) { history.replaceState(null, "", "#/accounts"); } document.querySelector(`[data-account="${CSS.escape(id)}"]`)?.focus(); };
  signal.addEventListener("abort", closeDrawer);
  openDrawer("grey", h("h2", { id: "drawer-title" }, id), skeletons(5), leave);
  let a, u, series, calls;
  try {
    a = await api(path);
    if (!a.deleted_at) [u, series, calls] = await Promise.all([api(read), api(`${read}/series?from=${isoDay(29)}&to=${isoDay()}`), api(`${read}/calls?limit=15`)]);
  } catch (error) {
    if (!signal.aborted) openDrawer("grey", h("h2", { id: "drawer-title" }, id), failure(error, () => detail(id, signal, refresh)), leave);
    return;
  }
  if (signal.aborted || !$("#drawer").open) return;
  const again = async () => { await refresh(); if (!signal.aborted) await detail(id, signal, refresh); };
  if (a.deleted_at) {
    openDrawer("grey", h("div", { class: "who" }, face(id, "asleep", 72), h("div", {}, h("h2", { id: "drawer-title" }, id), h("span", { class: "chip" }, `Removed ${ago(a.deleted_at)}`))),
      [h("p", { class: "muted" }, "This account isn’t being metered. Its history is kept, and messages for it are waiting to be retried."),
        h("button", { type: "button", class: "btn primary", onclick: (e) => act(e.currentTarget, async () => { await api(`${path}/restore`, { method: "POST" }); await again(); }, "Welcome back") }, icon("undo", 18), "Bring it back")], leave);
    return;
  }

  const c = u.cap, [label, tone, mood] = CAP[c.status];
  const cap = h("input", { class: "input", id: "cap", type: "number", min: 0, max: 44640, value: c.monthly_cap_minutes, required: true });
  const stat = (name, x, color, wide) => h("div", { class: `stat${wide ? " wide" : ""}`, style: { "--c": `var(--${color})` } }, h("span", {}, name), h("b", { class: "num" }, minutes(x.duration_seconds)), h("small", { class: "num" }, `${plural(x.completed_calls, "call")}, ${money(x.cost_cents)} spent${x.failed_calls ? `, ${count(x.failed_calls)} failed` : ""}${x.late_calls ? `, ${count(x.late_calls)} late` : ""}`));
  const byDay = new Map(series.points.map((p) => [p.period_start, p.usage.duration_seconds]));
  const days = Array.from({ length: 30 }, (_, i) => isoDay(29 - i));

  openDrawer(tone === "ok" ? "" : tone === "wait" ? "warning" : "bad",
    h("div", { class: "who rise" }, face(id, mood, 72), h("div", {}, h("h2", { id: "drawer-title" }, a.metadata.name ?? id), h("span", { class: `chip ${tone}` }, label), h("span", { class: "chip" }, c.new_calls_allowed ? "May place calls" : "No new calls"))),
    [
      h("div", { class: "stats" }, stat("This month", u.this_month, "indigo", true), stat("Today", u.today, "teal"), stat("This week", u.this_week, "orange"), stat("All time", u.lifetime, "pink")),
      h("form", { class: "card", onsubmit: (e) => { e.preventDefault(); act(e.submitter, async () => { await api(path, { method: "PATCH", body: { monthly_cap_minutes: Number(cap.value) } }); await again(); }, "Cap updated"); } },
        h("div", { class: "row between small" }, h("b", {}, `${minutes(c.used_seconds)} of ${count(c.monthly_cap_minutes)} min`), h("span", { class: "muted" }, c.overage_seconds ? `${minutes(c.overage_seconds)} over` : `${minutes(c.remaining_seconds)} left`)),
        h("div", { class: "rail big", style: { margin: "10px 0 6px" } }, h("i", { style: { width: `${Math.min(100, (c.used_seconds / Math.max(1, c.monthly_cap_minutes * 60)) * 100)}%`, background: tone === "bad" ? "var(--bad)" : tone === "wait" ? "var(--wait)" : "var(--indigo)" } })),
        c.reached_at && h("p", { class: "small muted" }, `Reached ${stamp(c.reached_at)}`),
        h("div", { class: "row", style: { "align-items": "end", "margin-top": "12px" } }, h("label", { class: "field", style: { flex: "1" } }, "Monthly cap (minutes)", cap), h("button", { class: "btn primary", type: "submit" }, "Save"))),
      h("section", { class: "card" }, h("h3", {}, "Talk time, last 30 days"), series.points.length ? bars(days.map((d, i) => ({ value: byDay.get(d) ?? 0, title: d, label: i % 7 === 0 || i === 29 ? d.slice(5) : "" })), { low: true, format: minutes, label: "Talk time per day" }) : h("p", { class: "muted small", style: { "margin-top": "8px" } }, "No calls in the last 30 days.")),
      range(read), checkTotals(path, again), recent(calls), notes(a, path, again),
      h("dl", { class: "facts" }, [["Account id", id], ["Internal id", a.id], ["Created", stamp(a.created_at)], ["Last change", stamp(a.updated_at)]].map(([k, v]) => h("div", {}, h("dt", {}, k), h("dd", { class: k === "Internal id" ? "mono" : "" }, v)))),
      h("div", { class: "row between" }, h("p", { class: "small muted", style: { flex: "1 1 200px" } }, "Removing stops metering. Nothing is erased, and you can bring it back."), confirmButton("Remove account", "Yes, remove it", (b) => act(b, async () => { await api(path, { method: "DELETE" }); closeDrawer(); leave(); await refresh(); }, `${id} removed`))),
    ], leave);
}

const more = (iconName, title, ...body) => h("details", { class: "more" }, h("summary", {}, icon(iconName, 19), title, icon("down", 18)), h("div", {}, body));

function range(read) {
  const from = h("input", { class: "input", type: "date", value: isoDay(29), required: true }), to = h("input", { class: "input", type: "date", value: isoDay(), required: true }), out = h("div", { "aria-live": "polite" });
  return more("calendar", "Add up any dates", h("form", { class: "row", style: { "align-items": "end" }, onsubmit: (e) => { e.preventDefault(); act(e.submitter, async () => {
    const r = await api(`${read}/range?from=${from.value}&to=${to.value}`);
    out.replaceChildren(h("div", { class: "stat rise" }, h("b", { class: "num" }, minutes(r.usage.duration_seconds)), h("small", { class: "num" }, `${plural(r.usage.completed_calls, "call")}, ${money(r.usage.cost_cents)} spent. Read from ${plural(r.buckets_read, "ready-made total")}.`)));
  }); } }, h("label", { class: "field", style: { flex: "1 1 130px" } }, "From", from), h("label", { class: "field", style: { flex: "1 1 130px" } }, "To", to), h("button", { class: "btn", type: "submit" }, "Add up")), out);
}

function checkTotals(path, again) {
  const out = h("div", { "aria-live": "polite", class: "stack" });
  const check = async () => {
    const r = await api(`${path}/reconcile?dry_run=true`, { method: "POST" });
    const n = r.drift.length;
    out.replaceChildren(h("div", { class: "item rise" }, h("span", { class: `swatch ${n ? "bad" : "ok"}` }, icon(n ? "alert" : "check", 17)), h("span", { class: "grow" }, n ? `${plural(n, "total")} differ` : "Every total matches", h("small", {}, `${plural(r.calls_seen, "call")} recounted from the raw messages`))),
      n ? confirmButton("Repair totals", "Yes, repair", (b) => act(b, async () => { await api(`${path}/reconcile?dry_run=false`, { method: "POST" }); await again(); }, "Totals repaired"), "scale") : "");
  };
  return more("scale", "Check the totals", h("p", { class: "small muted" }, "Counts everything again from the original messages and compares. Checking never changes anything."), h("button", { type: "button", class: "btn", onclick: (e) => act(e.currentTarget, check) }, "Check now"), out);
}

function recent(calls) {
  return more("phone", "Recent calls", calls.items.length ? h("ul", { class: "list", style: { "margin-top": "0" } }, calls.items.map((x) => h("li", { class: "item" }, h("span", { class: `swatch ${x.status === "completed" ? "ok" : "bad"}` }, icon(x.status === "completed" ? "phone" : "failed", 17)), h("span", { class: "grow" }, x.status === "completed" ? minutes(x.duration_seconds) : "Failed", h("small", { class: "mono" }, x.provider_call_id)), h("span", { class: "small muted" }, x.is_late ? "late" : ago(x.ended_at)), h("span", { class: "num" }, money(x.cost_cents))))) : h("p", { class: "small muted" }, "No finished calls yet."));
}

function notes(a, path, again) {
  const box = h("textarea", { class: "input", spellcheck: "false", "aria-label": "Notes as JSON", id: "notes" });
  box.value = JSON.stringify(a.metadata, null, 2);
  return more("note", "Notes", box, h("button", { type: "button", class: "btn", onclick: (e) => act(e.currentTarget, async () => {
    let next;
    try { next = JSON.parse(box.value); } catch { throw new Error("That isn’t valid JSON yet."); }
    if (next === null || typeof next !== "object" || Array.isArray(next)) throw new Error("Notes must be a JSON object.");
    for (const key of Object.keys(a.metadata)) if (!(key in next)) next[key] = null; // removed here, so remove it there
    await api(path, { method: "PATCH", body: { metadata: next } });
    await again();
  }, "Notes saved") }, "Save notes"));
}
