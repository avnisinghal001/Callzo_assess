// Console shell: routes, navigation and the health light. No framework and no build step.
import { onOverview, pollOverview } from "./lib/api.js";
import { $, closeDrawer, h, icon } from "./lib/dom.js";
import { plural } from "./lib/format.js";
import { accounts } from "./views/accounts.js";
import { events } from "./views/events.js";
import { history } from "./views/history.js";
import { live } from "./views/live.js";
import { simulator } from "./views/simulator.js";

const VIEWS = { simulator: ["Simulator", "tube", simulator], live: ["Live", "pulse", live], accounts: ["Accounts", "users", accounts], events: ["Events", "inbox", events], history: ["History", "history", history] };
const POLL_MS = 4000;

$("#logo").append(icon("phone", 22));
$("#nav").append(...Object.entries(VIEWS).map(([id, [label, iconName]]) => h("a", { href: `#/${id}`, "data-view": id }, icon(iconName, 17), label)));

let running = null;
let first = true;
async function route() {
  const [, id = "", arg = ""] = location.hash.split("/");
  const name = VIEWS[id] ? id : "simulator";
  running?.abort();
  running = new AbortController();
  closeDrawer();
  document.title = `${VIEWS[name][0]} · Callzo metering`;
  for (const link of document.querySelectorAll("#nav a")) {
    if (link.dataset.view === name) link.setAttribute("aria-current", "page"); else link.removeAttribute("aria-current");
  }
  const main = $("#main");
  const view = h("div", { class: "stack rise" });
  main.replaceChildren(view);
  if (!first) main.focus({ preventScroll: true });
  first = false;
  await VIEWS[name][2](view, { signal: running.signal, arg: decodeURIComponent(arg) });
}

onOverview((data, error) => {
  const say = (tone, text) => $("#health").replaceChildren(h("span", { class: `dot ${tone}` }), h("span", {}, text));
  if (error) return say("bad", "Can’t reach the server");
  const workers = data.instances.filter((i) => i.role === "worker" && i.alive).length;
  if (!workers) return say("bad", "No workers awake");
  if (data.inbox.dead) return say("bad", `${plural(data.inbox.dead, "message")} gave up`);
  if (data.inbox.oldest_due_seconds > 30) return say("wait", `Catching up, ${data.inbox.pending} waiting`);
  return say("ok", "All good");
});

addEventListener("hashchange", route);
addEventListener("visibilitychange", () => { if (!document.hidden) pollOverview(); });
setInterval(() => { if (!document.hidden) pollOverview(); }, POLL_MS);
pollOverview();
route();
