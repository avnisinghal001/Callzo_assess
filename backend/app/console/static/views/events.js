import { allAccounts, api, enc } from "../lib/api.js";
import { $, act, closeDrawer, confirmButton, empty, failure, h, icon, openDrawer, pillSelect, segmented, skeletons, toast } from "../lib/dom.js";
import { ago, count, EVENT, money, plural, stamp, STATE } from "../lib/format.js";

const SHELVES = [["processed", "Counted"], ["pending", "Waiting"], ["dead", "Gave up"], ["voided", "Set aside"]];
const QUIET = { processed: ["curious", "Nothing counted yet", "Send some traffic from the simulator."], pending: ["happy", "All caught up", "Nothing is waiting to be counted."], dead: ["happy", "Nothing gave up", "Every message found its way."], voided: ["happy", "Nothing set aside", "Messages you set aside land here and can be put back."] };

export async function events(root, { signal, arg }) {
  let shelf = SHELVES.some(([v]) => v === arg) ? arg : "processed", account = "", cursor = null;
  const list = h("ul", { class: "rows" });
  const more = h("button", { type: "button", class: "btn", hidden: true, onclick: (e) => act(e.currentTarget, () => load(false)) }, "Show more");
  const actions = h("div", { class: "row" });
  let options = [["", "Every account"]];
  try { options = options.concat((await allAccounts()).map((a) => [a.external_id, a.external_id])); } catch { /* the filter is optional; the list below reports its own errors */ }
  if (signal.aborted) return;
  root.replaceChildren(h("div", { class: "head" }, h("div", {}, h("h1", {}, "Events"), h("p", {}, "Every message exactly as it arrived, and what became of it."))),
    h("section", { class: "sheet" }, h("header", {}, segmented("Show", SHELVES, shelf, (v) => { shelf = v; load(true); }), h("div", { class: "row" }, actions, pillSelect("Account", options, "", (v) => { account = v; load(true); }, () => icon("users", 18)))), list, h("div", { class: "row", style: { padding: "0 24px 20px", "justify-content": "center" } }, more)));

  async function load(reset) {
    if (reset) { cursor = null; list.replaceChildren(h("li", {}, skeletons(5))); more.hidden = true; }
    try {
      const page = await api(`/admin/v1/events?status=${shelf}&limit=30${account ? `&account=${enc(account)}` : ""}${cursor ? `&cursor=${enc(cursor)}` : ""}`);
      if (signal.aborted) return;
      if (reset) list.replaceChildren();
      list.append(...page.items.map(row));
      cursor = page.next_cursor;
      more.hidden = !cursor;
      if (!list.children.length) list.append(h("li", {}, empty(...QUIET[shelf])));
      actions.replaceChildren(...(shelf === "dead" && page.items.length ? [confirmButton("Try all again", "Yes, try all", (b) => act(b, async () => { const r = await api(`/admin/v1/events/requeue-dead${account ? `?account=${enc(account)}` : ""}`, { method: "POST" }); await load(true); return r; }, (r) => `${plural(r.requeued, "message")} back in the queue`), "refresh")] : []));
    } catch (error) {
      if (reset) list.replaceChildren(h("li", {}, failure(error, () => load(true)))); else throw error;
    }
  }
  function row(e) {
    const [label, iconName, tone] = EVENT[e.event_type];
    const [state, color] = STATE[e.deleted_at ? "voided" : e.status];
    return h("li", {}, h("button", { type: "button", class: "line event", "data-event": e.id, onclick: () => open(e.id) },
      h("div", { class: "who" }, h("span", { class: `swatch ${tone}` }, icon(iconName, 17)), h("div", {}, h("strong", {}, label), h("small", { class: "mono" }, e.provider_event_id))),
      h("span", { class: "hide-sm small" }, e.account_external_id), h("span", { class: "hide-sm small muted" }, ago(e.received_at)), h("span", {}, h("span", { class: `chip ${color}` }, state)), icon("right", 18)));
  }
  async function open(id) {
    const leave = () => document.querySelector(`[data-event="${id}"]`)?.focus();
    signal.addEventListener("abort", closeDrawer);
    openDrawer("grey", h("h2", { id: "drawer-title" }, "Opening"), skeletons(4), leave);
    let e;
    try { e = await api(`/admin/v1/events/${id}`); } catch (error) { openDrawer("grey", h("h2", { id: "drawer-title" }, "Event"), failure(error, () => open(id)), leave); return; }
    if (signal.aborted || !$("#drawer").open) return;
    const [label, iconName] = EVENT[e.event_type], [state, tone] = STATE[e.deleted_at ? "voided" : e.status];
    const again = async () => { await load(true); await open(id); };
    const reason = h("input", { class: "input", id: "reason", maxlength: 500, placeholder: "Why is it wrong?" });
    const doing = [];
    if (e.deleted_at) doing.push(h("button", { type: "button", class: "btn primary", onclick: (b) => act(b.currentTarget, async () => { await api(`/admin/v1/events/${id}/restore`, { method: "POST" }); await again(); }, "Put back. A worker will count it.") }, icon("undo", 18), "Put it back"));
    else {
      if (e.status !== "processed") doing.push(h("button", { type: "button", class: "btn primary", onclick: (b) => act(b.currentTarget, async () => { await api(`/admin/v1/events/${id}/requeue`, { method: "POST" }); await again(); }, "Back in the queue") }, icon("refresh", 18), "Try again now"));
      doing.push(h("details", { class: "more" }, h("summary", {}, icon("trash", 19), "Set it aside", icon("down", 18)), h("div", {}, h("p", { class: "small muted" }, "Leaves it out of every total, straight away. The message itself is kept, and it can be put back."), h("label", { class: "field" }, "Reason", reason),
        h("button", { type: "button", class: "btn danger", onclick: (b) => { if (!reason.value.trim()) { toast("Add a reason first", true); reason.focus(); return; } act(b.currentTarget, async () => { await api(`/admin/v1/events/${id}/void`, { method: "POST", body: { reason: reason.value.trim() } }); await again(); }, "Set aside. Totals updated."); } }, "Set aside"))));
    }
    const facts = [["Account", e.account_external_id], ["Call", e.provider_call_id], ["Happened", stamp(e.occurred_at)], ["Arrived", stamp(e.received_at)], ["Counted", stamp(e.processed_at)], ["Tries", count(e.attempts)]];
    if (e.event_type === "call.ended") facts.push(["Length and cost", `${e.duration_seconds} s, ${money(e.cost_cents)}`]);
    if (e.metadata.void) facts.push(["Set aside because", e.metadata.void.reason]);
    if (e.last_error) facts.push(["Last problem", e.last_error]);
    facts.push(["Internal id", e.id]);
    openDrawer(tone === "bad" ? "bad" : tone === "wait" ? "warning" : tone === "ok" ? "ok" : "grey", h("div", { class: "who rise" }, h("span", { class: `swatch ${tone}`, style: { width: "56px", height: "56px", "border-radius": "18px", background: "rgb(255 255 255 / .8)" } }, icon(iconName, 28)), h("div", {}, h("h2", { id: "drawer-title" }, label), h("span", { class: `chip ${tone}` }, state), h("span", { class: "chip" }, e.metadata.source === "webhook" ? "From the provider" : "From the simulator"))),
      [h("dl", { class: "facts" }, facts.map(([k, v]) => h("div", {}, h("dt", {}, k), h("dd", {}, v)))), h("h3", {}, "The message, formatted for reading"), h("pre", {}, pretty(e.raw_body)), doing], leave);
  }
  await load(true);
}

function pretty(body) { try { return JSON.stringify(JSON.parse(body), null, 2); } catch { return body || "(empty)"; } }
