import { h, s } from "./dom.js";

/** Smooth area line for a tile. Decorative: the number beside it carries the value. */
export function spark(values) {
  const peak = Math.max(1, ...values);
  const step = 100 / Math.max(1, values.length - 1);
  const points = values.map((v, i) => [i * step, 52 - (v / peak) * 44]);
  const line = points.reduce((d, [x, y], i) => {
    if (!i) return `M${x} ${y}`;
    const [px, py] = points[i - 1];
    return `${d}C${px + step / 2} ${py} ${x - step / 2} ${y} ${x} ${y}`;
  }, "");
  return s("svg", { class: "spark", viewBox: "0 0 100 56", preserveAspectRatio: "none", "aria-hidden": "true" },
    s("path", { d: `${line}L100 56L0 56Z`, fill: "currentColor", opacity: 0.22 }),
    s("path", { d: line, fill: "none", stroke: "currentColor", "stroke-width": 1.4, opacity: 0.6, "vector-effect": "non-scaling-stroke" }));
}

const R = 84, ARC = Math.PI * R, GAP = 24, PATH = `M${110 - R} 104A${R} ${R} 0 0 1 ${110 + R} 104`;

/** Half-circle share. parts: [{value, color}]. `total` leaves the rest of the track visible. */
export function gauge(parts, big, small, total) {
  const sum = total ?? parts.reduce((n, p) => n + p.value, 0);
  const shown = parts.filter((p) => p.value > 0);
  const usable = ARC - Math.max(0, shown.length - 1) * GAP;
  let at = 0;
  const arcs = shown.map((p) => {
    const len = Math.max(3, (p.value / sum) * usable);
    const arc = s("path", { d: PATH, fill: "none", stroke: p.color, "stroke-width": 22, "stroke-linecap": "round", "stroke-dasharray": `${len} ${ARC * 2}`, "stroke-dashoffset": -at });
    at += len + GAP;
    return arc;
  });
  return h("div", { class: "gauge" },
    s("svg", { viewBox: "0 0 220 120", "aria-hidden": "true" }, s("path", { d: PATH, fill: "none", stroke: "var(--track)", "stroke-width": 22, "stroke-linecap": "round" }), arcs),
    h("div", {}, h("b", { class: "num" }, big), h("small", {}, small)));
}

/** Pill bars on a track. data: [{value, label, title}] */
export function bars(data, { low = false, color, format, label }) {
  const peak = Math.max(1, ...data.map((d) => d.value));
  const tip = h("div", { class: "tip", hidden: true });
  const box = h("div", { class: `bars${low ? " low" : ""}`, style: color ? { "--c": color } : {}, role: "img", "aria-label": `${label}. Highest ${format(Math.max(...data.map((d) => d.value)))}.` });
  data.forEach((d) => {
    const fill = h("i");
    const bar = h("div", { class: "bar",
      onmouseenter: () => { tip.replaceChildren(h("b", { class: "num" }, format(d.value)), d.title); tip.hidden = false; const x = bar.offsetLeft + bar.offsetWidth / 2; tip.style.left = `${Math.min(Math.max(x, 60), box.offsetWidth - 60)}px`; tip.style.top = `${Math.max(46, bar.offsetHeight * (1 - d.value / peak)) - 4}px`; },
      onmouseleave: () => { tip.hidden = true; } }, fill);
    box.append(bar);
    requestAnimationFrame(() => { fill.style.height = d.value ? `max(8px, ${(d.value / peak) * 100}%)` : "0"; });
  });
  box.append(tip);
  const axis = h("div", { class: "axis", "aria-hidden": "true" }, data.filter((d) => d.label).map((d) => h("span", {}, d.label)));
  return h("div", {}, box, axis);
}
