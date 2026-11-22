// Small DOM helpers. Data is only ever inserted as text, never as HTML.
import { ICONS } from "./icon-data.js";

export const $ = (selector, root = document) => root.querySelector(selector);
export const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

function build(node, props, kids) {
  for (const [name, value] of Object.entries(props)) {
    if (value == null || value === false) continue;
    if (name.startsWith("on")) node.addEventListener(name.slice(2), value);
    else if (name === "style") for (const [k, v] of Object.entries(value)) node.style.setProperty(k, v);
    else if (name === "value") node.value = value;
    else node.setAttribute(name, value === true ? "" : value);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid == null || kid === false) continue;
    node.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return node;
}

export const h = (tag, props = {}, ...kids) => build(document.createElement(tag), props, kids);
export const s = (tag, props = {}, ...kids) => build(document.createElementNS("http://www.w3.org/2000/svg", tag), props, kids);

export function icon(name, size = 20, className = "") {
  return s("svg", { width: size, height: size, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", "stroke-width": 1.8, "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true", class: className },
    ICONS[name].map(([tag, props]) => s(tag, props)));
}

const FACES = [["#c7c3ff", "#4f46e5"], ["#b9ecfb", "#0284a8"], ["#ffd5b8", "#d9480f"], ["#ffc9e3", "#c01f74"], ["#d6f5a8", "#4d7c0f"], ["#ffe58f", "#a16207"], ["#bff0de", "#0f766e"], ["#e4ccff", "#7e22ce"]];

/** A small face whose mood mirrors a state: happy, curious or asleep. Decorative: words say it too. */
export function face(seed, mood = "happy", size = 42) {
  const n = [...String(seed)].reduce((sum, c) => (sum * 31 + c.charCodeAt(0)) >>> 0, 7);
  const [bg, fg] = FACES[n % FACES.length];
  const line = (d) => s("path", { d });
  const eyes = [14, 26].map((cx) => s("circle", { cx, cy: 17.5, r: 2.1, fill: fg, stroke: "none" }));
  const parts = mood === "asleep" ? [line("M11.5 18.5q2 2 4 0"), line("M24.5 18.5q2 2 4 0"), line("M17.5 26.5h5")]
    : mood === "sad" ? [...eyes, line("M14 27.5q6 -5.5 12 0")]
    : mood === "curious" ? [...eyes, s("circle", { cx: 20, cy: 26, r: 2.2 })] : [...eyes, line("M14 23.5q6 6.5 12 0")];
  return s("svg", { width: size, height: size, viewBox: "0 0 40 40", class: "face", "aria-hidden": "true" },
    s("rect", { width: 40, height: 40, rx: 13, fill: bg }),
    s("g", { transform: `rotate(${(n % 24) - 12} 20 20)`, stroke: fg, "stroke-width": 2.6, "stroke-linecap": "round", fill: "none" }, parts));
}

export function toast(message, bad = false) {
  const note = h("div", { class: bad ? "bad" : "" }, icon(bad ? "alert" : "check", 18), message);
  $("#toasts").append(note);
  setTimeout(() => note.remove(), bad ? 7000 : 3500);
}

/** Run an action from a button: busy while it runs, a toast when it fails. */
export async function act(button, work, done) {
  if (button) button.disabled = true;
  try {
    const result = await work();
    if (done) toast(typeof done === "function" ? done(result) : done);
    return result;
  } catch (error) {
    toast(error.message, true);
    return undefined;
  } finally {
    if (button) button.disabled = false;
  }
}

/** Asks for a second click instead of opening a dialog. */
export function confirmButton(label, question, run, iconName = "trash") {
  const text = h("span", {}, label);
  const button = h("button", { type: "button", class: "btn sm danger" }, icon(iconName, 17), text);
  let timer = null;
  const disarm = () => { clearTimeout(timer); timer = null; button.classList.remove("armed"); text.textContent = label; };
  button.addEventListener("click", () => {
    if (timer) { disarm(); run(button); return; }
    button.classList.add("armed");
    text.textContent = question;
    timer = setTimeout(disarm, 4000);
  });
  return button;
}

/** Segmented choice. Returns the element; calls back with the chosen value. */
export function segmented(label, options, value, onPick) {
  const group = h("div", { class: "seg", role: "group", "aria-label": label });
  const paint = (current) => group.replaceChildren(...options.map(([v, text]) =>
    h("button", { type: "button", "aria-pressed": String(v === current), onclick: () => { paint(v); onPick(v); [...group.children].find((b) => b.getAttribute("aria-pressed") === "true").focus(); } }, text)));
  paint(value);
  return group;
}

export function pillSelect(label, options, value, onPick, lead = () => null) {
  const shown = h("span", {});
  const slot = h("span", {});
  const select = h("select", { "aria-label": label }, options.map(([v, text]) => h("option", { value: v }, text)));
  const paint = () => { shown.textContent = options.find(([v]) => v === select.value)?.[1] ?? ""; slot.replaceChildren(lead(select.value) ?? ""); };
  select.value = value;
  select.addEventListener("change", () => { paint(); onPick(select.value); });
  paint();
  return h("label", { class: "pill-select" }, slot, shown, select, icon("down", 17));
}

export const skeletons = (n = 4) => h("div", { class: "list", "aria-busy": "true" }, Array.from({ length: n }, () => h("div", { class: "skeleton" })));

export function empty(mood, title, text, ...actions) {
  return h("div", { class: "empty rise" }, face(title, mood, 76), h("strong", {}, title), h("p", {}, text), actions);
}

export function failure(error, retry) {
  return empty("sad", "That didn’t load", error.message, h("button", { type: "button", class: "btn", onclick: retry }, icon("refresh", 18), "Try again"));
}

// ---- drawer ----
export function openDrawer(tone, head, body, onClose) {
  const drawer = $("#drawer");
  const close = h("button", { type: "button", class: "icon-btn", "aria-label": "Close", onclick: () => drawer.close() }, icon("close", 20));
  drawer.replaceChildren(h("div", { class: `panel ${tone}` }, h("header", {}, h("div", { class: "row between" }, h("span", {}), close), head), h("div", { class: "body" }, body)));
  drawer.onclick = (e) => { if (e.target === drawer) drawer.close(); };
  drawer.onclose = () => { drawer.replaceChildren(); onClose?.(); };
  if (!drawer.open) drawer.showModal();
}
export function closeDrawer() { const d = $("#drawer"); if (d.open) { d.onclose = null; d.close(); d.replaceChildren(); } }
