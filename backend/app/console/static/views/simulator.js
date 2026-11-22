// Home screen. One tap sends tricky traffic through the real code and judges the result:
// what should have been counted (worked out independently) against what the meter counted.
import { allAccounts, api } from "../lib/api.js";
import { gauge } from "../lib/charts.js";
import { empty, face, failure, h, icon, pillSelect, reduced, segmented } from "../lib/dom.js";
import { CAP, count, EVENT, minutes, money, monthName, plural } from "../lib/format.js";

const SCENARIOS = [
  ["normal", "Everyday calls", "Start, talk, hang up.", "phone", "indigo", "Each call is stored once, then counted once when it ends."],
  ["failed", "Calls that fail", "Nobody picked up.", "failed", "indigo", "A failed call is recorded as failed. It adds no talk time and no cost."],
  ["duplicate", "Sent three times", "The same event, again and again.", "copy", "teal", "The event id is unique in the database. The first copy is stored; the other two are acknowledged and add nothing."],
  ["out_of_order", "Ended before it began", "The ending arrives first.", "swap", "teal", "A call is worked out from all of its events, so the order they arrive in makes no difference."],
  ["late", "Five weeks late", "Old news from last month.", "clock", "teal", "Counted in the month the call happened and flagged as late. This month’s cap is untouched."],
  ["burst", "A burst of long calls", "Pushes hard on the cap.", "fire", "orange", "Every call is recorded, because it already happened. At the cap, new calls stop being allowed."],
  ["malformed", "Broken messages", "Missing, mangled or empty.", "broken", "pink", "Refused with a clear client error before anything is stored. The service keeps running."],
  ["bad_signature", "Forged senders", "Wrong or missing signature.", "shield", "pink", "Refused before the message is even read. Signatures are compared in constant time."],
].map(([id, title, say, iconName, color, why]) => ({ id, title, say, icon: iconName, color, why }));

const byId = Object.fromEntries(SCENARIOS.map((x) => [x.id, x]));
const score = new Map(); // scenario -> "pass" | "fail", for this visit
const sleep = (ms) => new Promise((r) => setTimeout(r, reduced() ? Math.min(ms, 30) : ms));

export async function simulator(root, { signal }) {
  let accounts, enabled = true;
  try {
    const [list, overview] = await Promise.all([allAccounts(), api("/admin/v1/overview")]);
    accounts = list;
    enabled = overview.sandbox_enabled;
  } catch (error) {
    root.replaceChildren(failure(error, () => simulator(root, { signal })));
    return;
  }
  if (signal.aborted) return;
  if (!enabled) {
    root.replaceChildren(empty("asleep", "The simulator is off on this server", "It only runs where test traffic is welcome. Set ENABLE_SANDBOX=true to wake it up."));
    return;
  }
  if (!accounts.length) {
    root.replaceChildren(empty("curious", "No accounts yet", "Create one first, then come back and send it some traffic.", h("a", { class: "btn primary", href: "#/accounts" }, "Go to accounts")));
    return;
  }

  let account = accounts[0].external_id, amount = 5, busy = false;
  const tiles = new Map();
  const stage = h("section", { class: "card stage", "aria-live": "polite", "aria-label": "Result" });
  const board = h("aside", { class: "card board", "aria-label": "Scorecard" });
  const runAll = h("button", { type: "button", class: "btn primary", onclick: () => all() }, icon("play", 18), "Run all 8");

  const grid = h("div", { class: "scenarios", role: "group", "aria-label": "Scenarios" }, SCENARIOS.map((x) => {
    const mark = h("span", { class: "mark" }, icon("play", 15));
    const tile = h("button", { type: "button", class: `scenario c-${x.color}`, "aria-pressed": "false", onclick: () => one(x.id) },
      h("span", { class: "badge" }, icon(x.icon, 21)), h("strong", {}, x.title), h("span", { class: "say" }, x.say), mark, h("span", { class: "sr", "data-state": "" }, "Not run yet"));
    tiles.set(x.id, { tile, mark });
    return tile;
  }));

  root.replaceChildren(
    h("div", { class: "head" },
      h("div", {}, h("h1", {}, "Simulator"), h("p", {}, "Send awkward call traffic and see whether the meter still gets it exactly right.")),
      h("div", { class: "row" },
        pillSelect("Account", accounts.map((a) => [a.external_id, a.external_id]), account, (v) => { account = v; }, (v) => face(v, "happy", 28)),
        segmented("How many calls", [[1, "1 call"], [5, "5 calls"], [20, "20 calls"]], amount, (v) => { amount = v; }), runAll)),
    grid, h("div", { class: "cols" }, stage, board));
  idle();
  paintBoard();

  function idle() {
    stage.replaceChildren(empty("happy", "Pick something awkward", "Tap a tile above. Your traffic goes through the same checks, storage and workers as the real thing."));
  }

  function paintTile(id, state) {
    const { tile, mark } = tiles.get(id);
    mark.className = `mark ${state === "pass" || state === "fail" ? `${state} pop` : ""}`;
    mark.replaceChildren(state === "busy" ? icon("refresh", 15, "spin") : icon(state === "pass" ? "check" : state === "fail" ? "close" : "play", 15));
    tile.querySelector("[data-state]").textContent = { pass: "Passed", fail: "Failed", busy: "Running" }[state] ?? "Not run yet";
  }

  function paintBoard() {
    const passed = [...score.values()].filter((v) => v === "pass").length;
    const failed = score.size - passed;
    board.replaceChildren(h("h3", {}, "How is it holding up?"),
      gauge([{ value: passed, color: "var(--ok)" }, { value: failed, color: "var(--bad)" }], `${passed} of 8`, failed ? `${failed} need a look` : passed === 8 ? "everything held" : "scenarios proven", 8),
      h("ul", { class: "list" }, SCENARIOS.map((x) => {
        const state = score.get(x.id);
        const tone = state === "pass" ? "ok" : state === "fail" ? "bad" : "";
        return h("li", {}, h("button", { type: "button", class: "item", disabled: busy, onclick: () => one(x.id) },
          h("span", { class: `swatch ${tone}` }, icon(state === "pass" ? "check" : state === "fail" ? "close" : x.icon, 17)), h("span", { class: "grow" }, x.title),
          h("span", { class: "small muted" }, state === "pass" ? "Held" : state === "fail" ? "Failed" : "Not run")));
      })));
  }

  function setBusy(value) {
    busy = value;
    runAll.disabled = value;
    for (const { tile } of tiles.values()) tile.disabled = value;
    paintBoard();
  }

  async function one(id) {
    if (busy) return;
    setBusy(true);
    try { await run(id); } finally { if (!signal.aborted) setBusy(false); }
  }

  async function all() {
    if (busy) return;
    setBusy(true);
    try {
      for (const x of SCENARIOS) {
        if (signal.aborted) return;
        await run(x.id);
        await sleep(450);
      }
    } finally { if (!signal.aborted) setBusy(false); }
  }

  async function run(id) {
    const x = byId[id];
    for (const [key, { tile }] of tiles) tile.setAttribute("aria-pressed", String(key === id));
    paintTile(id, "busy");
    const pipe = pipeline(x);
    const tail = h("div", {});
    stage.style.setProperty("--c", `var(--${x.color})`);
    stage.scrollIntoView({ block: "nearest", behavior: reduced() ? "auto" : "smooth" });
    stage.replaceChildren(h("div", { class: "row between" }, h("h2", {}, x.title), h("span", { class: "chip" }, account)), pipe.node, tail);
    try {
      const sent = await api("/admin/v1/sandbox/scenarios", { method: "POST", body: { scenario: id, account, count: amount } });
      const accepted = sent.results.filter((r) => r.outcome === "accepted").length;
      const duplicates = sent.results.filter((r) => r.outcome === "duplicate").length;
      const refused = sent.results.filter((r) => r.outcome === "rejected").length;
      await pipe.reach(0, sent.sent);
      await pipe.reach(1, sent.sent - refused, refused ? `${count(refused)} refused` : "all valid");
      let verdict;
      if (refused) {
        pipe.stop(2, "nothing stored");
        pipe.stop(3, "nothing counted");
        const ok = refused === sent.sent && sent.results.every((r) => r.status_code >= 400 && r.status_code < 500);
        verdict = { ok, title: ok ? "All turned away" : "Something got through", text: ok ? `${plural(refused, "bad request")}, ${plural(refused, "clear refusal")}. Nothing reached the database.` : "Some of these should have been refused.", rows: [] };
      } else {
        await pipe.reach(2, accepted, duplicates ? `${plural(duplicates, "copy", "copies")} ignored` : "each one once");
        const seen = await settled(sent);
        await pipe.reach(3, seen.actual.completed_calls + seen.actual.failed_calls, "calls counted");
        verdict = judge(x, sent, seen, accepted, duplicates);
      }
      if (signal.aborted) return;
      score.set(id, verdict.ok ? "pass" : "fail");
      paintTile(id, score.get(id));
      tail.replaceChildren(...result(x, sent, verdict));
      if (verdict.ok) confetti(tail.firstElementChild);
    } catch (error) {
      score.set(id, "fail");
      paintTile(id, "fail");
      tail.replaceChildren(failure(error, () => one(id)));
    }
    paintBoard();
  }

  /** Wait until workers have counted everything this run sent. */
  async function settled(sent) {
    const deadline = Date.now() + 20000;
    for (;;) {
      const seen = await api("/admin/v1/sandbox/verify", { method: "POST", body: { account: sent.account, call_ids: sent.call_ids } });
      if (seen.waiting_events === 0) return seen;
      if (Date.now() > deadline) throw new Error("Workers haven’t picked this up yet. Are any running?");
      await new Promise((r) => setTimeout(r, 250));
    }
  }
}

function judge(x, sent, seen, accepted, duplicates) {
  const want = sent.expected, got = seen.actual;
  const rows = [
    ["Calls", want.completed_calls + want.failed_calls, got.completed_calls + got.failed_calls, count],
    ["Talk time", want.duration_seconds, got.duration_seconds, minutes],
    ["Cost", want.cost_cents, got.cost_cents, money],
    x.id === "failed" ? ["Failed", want.failed_calls, got.failed_calls, count] : ["Arrived late", want.late_calls, got.late_calls, count],
  ];
  const ok = Object.keys(want).every((k) => want[k] === got[k]) && (x.id !== "duplicate" || (accepted === 1 && duplicates === 2));
  let text = `${plural(sent.sent, "message")} in, ${plural(got.completed_calls + got.failed_calls, "call")} counted.`;
  if (x.id === "late" && seen.months.length) text += ` Booked in ${seen.months.map(monthName).join(" and ")}.`;
  return { ok, title: ok ? "Exactly right" : "The totals don’t match", text, rows, cap: x.id === "burst" ? seen.cap : null };
}

function result(x, sent, verdict) {
  const parts = [h("div", { class: "verdict rise" }, face(x.id, verdict.ok ? "happy" : "sad", 56), h("div", {}, h("strong", {}, verdict.title), h("p", {}, verdict.text)))];
  if (verdict.rows.length) {
    parts.push(h("dl", { class: "match rise" }, verdict.rows.map(([label, want, got, show]) =>
      h("div", {}, h("dt", {}, label, h("span", { class: want === got ? "ok" : "bad" }, icon(want === got ? "tick" : "alert", 19))), h("dd", { class: "got num" }, show(got)), h("dd", { class: "want num" }, `expected ${show(want)}`)))));
  }
  if (verdict.cap) {
    const c = verdict.cap, [label, tone] = CAP[c.status];
    parts.push(h("div", { class: "verdict rise" }, h("span", { class: `swatch ${tone}` }, icon("gauge", 19)), h("div", { style: { flex: "1" } },
      h("div", { class: "row between small" }, h("b", {}, `${minutes(c.used_seconds)} of ${count(c.monthly_cap_minutes)} min this month`), h("span", { class: `chip ${tone}` }, label)),
      h("div", { class: "rail big", style: { margin: "8px 0" } }, h("i", { style: { width: `${Math.min(100, (c.used_seconds / Math.max(1, c.monthly_cap_minutes * 60)) * 100)}%`, background: tone === "bad" ? "var(--bad)" : tone === "wait" ? "var(--wait)" : "var(--indigo)" } })),
      h("p", { class: "small" }, c.new_calls_allowed ? "New calls are still allowed." : "New calls are no longer allowed this month."))));
  }
  parts.push(h("p", { class: "why" }, icon("smile", 20), h("span", {}, x.why)));
  parts.push(h("h3", { style: { "margin-top": "18px" } }, "What was sent"));
  parts.push(h("ul", { class: "sent" }, sent.results.map((r) => {
    const tone = r.outcome === "accepted" ? "ok" : r.outcome === "duplicate" ? "info" : "bad";
    const [label, iconName] = EVENT[r.label] ?? [r.label[0].toUpperCase() + r.label.slice(1), x.icon];
    return h("li", {}, icon(iconName, 18), h("span", {}, label, r.event_id && h("span", { class: "mono" }, `  ${r.event_id}`)),
      h("span", { class: "small muted" }, { accepted: "Stored", duplicate: "Already had it", rejected: "Refused" }[r.outcome]), h("span", { class: `chip num ${tone}` }, r.status_code));
  })));
  return parts;
}

function pipeline(x) {
  const fill = h("div", { class: "fill" });
  const stations = [["Sent", "send"], ["Checked", "checked"], ["Stored", "database"], ["Counted", "gauge"]].map(([label, name]) => {
    const number = h("b", { class: "num" }, "–"), note = h("small", {});
    return { number, note, node: h("div", { class: "station" }, h("div", { class: "node" }, icon(name, 24)), number, h("span", {}, label), note) };
  });
  const node = h("div", { class: "pipe" }, fill, stations.map((x2) => x2.node));
  node.style.setProperty("--c", `var(--${x.color})`);
  return {
    node,
    async reach(i, value, note = "") {
      if (i > 0) {
        fill.style.width = `${i * 25}%`;
        parcels(node, i);
        await sleep(620);
      }
      stations[i].node.classList.add("on");
      stations[i].number.textContent = count(value);
      stations[i].note.textContent = note;
      await sleep(i ? 120 : 220);
    },
    stop(i, note) { stations[i].number.textContent = "0"; stations[i].note.textContent = note; },
  };
}

function parcels(pipe, i) {
  if (reduced()) return;
  const step = pipe.offsetWidth / 4;
  for (let k = 0; k < 5; k++) {
    const dot = h("span", { class: "parcel" });
    pipe.append(dot);
    dot.animate([{ transform: `translateX(${(i - 1) * step - 7}px) scale(.6)`, opacity: 0.2 }, { opacity: 1, offset: 0.3 }, { transform: `translateX(${i * step - 7}px) scale(1)`, opacity: 0 }],
      { duration: 560, delay: k * 70, easing: "cubic-bezier(.4,0,.2,1)", fill: "both" }).finished.then(() => dot.remove(), () => dot.remove());
  }
}

function confetti(card) {
  if (reduced() || !card?.animate) return;
  card.style.position = "relative";
  const colors = ["#4f46e5", "#0284a8", "#d9480f", "#e0318c", "#f5a50b", "#16a34a"];
  for (let i = 0; i < 18; i++) {
    const bit = h("i", { class: "bit", style: { left: "40px", top: "28px", background: colors[i % colors.length] } });
    card.append(bit);
    const angle = (i / 18) * Math.PI * 2, far = 46 + (i % 4) * 18;
    bit.animate([{ transform: "none", opacity: 1 }, { transform: `translate(${Math.cos(angle) * far}px, ${Math.sin(angle) * far + 26}px) rotate(${i * 50}deg)`, opacity: 0 }],
      { duration: 1000, easing: "cubic-bezier(.2,.7,.4,1)", fill: "both" }).finished.then(() => bit.remove(), () => bit.remove());
  }
}
