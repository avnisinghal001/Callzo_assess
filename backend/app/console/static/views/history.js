import { api, enc } from "../lib/api.js";
import { act, empty, failure, h, icon, skeletons } from "../lib/dom.js";
import { clock, count, day, plural } from "../lib/format.js";

const SAY = {
  "account.create": (e, m) => ["plus", "ok", `${e.target} was created with a cap of ${count(m.cap)} min`],
  "account.update": (e, m) => ["gauge", "info", m.cap_before !== m.cap_after ? `${e.target}’s cap went from ${count(m.cap_before)} to ${count(m.cap_after)} min` : `${e.target}’s notes were edited`],
  "account.delete": (e) => ["trash", "bad", `${e.target} was removed`],
  "account.restore": (e) => ["undo", "ok", `${e.target} was brought back`],
  "event.void": (e, m) => ["trash", "bad", `A message for ${m.account} was set aside: ${m.reason}`],
  "event.restore": () => ["undo", "ok", "A message was put back"],
  "event.requeue": () => ["refresh", "info", "A message was sent to the queue again"],
  "event.requeue_dead": (e, m) => ["refresh", "info", `${plural(m.requeued, "message")} that gave up went back to the queue`],
  "reconcile.repair": (e, m) => ["scale", m.drifted_buckets ? "wait" : "ok", m.drifted_buckets ? `${e.target}: ${plural(m.drifted_buckets, "total")} repaired` : `${e.target} was recounted; nothing to repair`],
  "reconcile.drift_found": (e, m) => ["alert", "bad", `The hourly check found differences in ${m.accounts.join(", ")}`],
  "sandbox.run": (e, m) => ["play", "info", `Simulator: ${m.scenario.replaceAll("_", " ")}, ${plural(m.sent, "message")} to ${e.target}`],
};
const who = (actor) => (actor === "console" ? "from this console" : actor === "scheduler" ? "by the scheduler" : `with key ${actor.split(":")[1] ?? actor}`);

export async function history(root, { signal }) {
  let cursor = null, lastDay = "";
  const list = h("ul", { class: "rows", style: { "padding-top": "8px" } });
  const more = h("button", { type: "button", class: "btn", hidden: true, onclick: (e) => act(e.currentTarget, load) }, "Show more");
  root.replaceChildren(h("div", { class: "head" }, h("div", {}, h("h1", {}, "History"), h("p", {}, "Every change, who made it, and the request behind it."))), h("section", { class: "sheet" }, list, h("div", { class: "row", style: { padding: "0 24px 20px", "justify-content": "center" } }, more)));
  list.replaceChildren(h("li", {}, skeletons(6)));
  async function load() {
    const page = await api(`/admin/v1/audit?limit=40${cursor ? `&cursor=${enc(cursor)}` : ""}`);
    if (signal.aborted) return;
    if (!cursor) list.replaceChildren();
    for (const e of page.items) {
      const d = day(e.created_at);
      if (d !== lastDay) { list.append(h("li", { class: "day" }, d)); lastDay = d; }
      const [iconName, tone, text] = SAY[e.action]?.(e, e.metadata) ?? ["note", "", `${e.action} ${e.target}`];
      list.append(h("li", { class: "item", style: { "min-height": "58px" } }, h("span", { class: `swatch ${tone}` }, icon(iconName, 17)), h("span", { class: "grow" }, text, h("small", {}, `${who(e.actor)}${e.request_id ? `, request ${e.request_id.slice(0, 12)}` : ""}`)), h("span", { class: "small muted num" }, clock(e.created_at))));
    }
    cursor = page.next_cursor;
    more.hidden = !cursor;
    if (!list.children.length) list.append(h("li", {}, empty("happy", "A clean slate", "Changes you make will be written down here.")));
  }
  const first = () => load().catch((error) => list.replaceChildren(h("li", {}, failure(error, first))));
  await first();
}
