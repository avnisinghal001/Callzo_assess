import assert from "node:assert/strict";
import { test } from "node:test";
import { samePayload, serverMessage, toPayload, validate } from "../src/settings/model.ts";
import { deadEnd, initialState, needsSave, readyToSubmit, reducer, stepsOneToThreeSaved, type Action, type SettingsState } from "../src/settings/reducer.ts";

const FULL = { 1: { name: "A", email: "a@b.c" }, 2: { plan: "pro", billing_country: "US" }, 3: {}, 4: { webhook_url: "" } };
const run = (s: SettingsState, ...as: Action[]) => as.reduce(reducer, s);
const loaded = (saved: object = FULL, recovered = {}) => run(initialState(), { type: "loaded", saved, defaults: {}, recovered });

test("payloads match the API contract", () => {
  assert.deepEqual(toPayload(1, { name: " A ", email: "a@b.c" }), { name: "A", email: "a@b.c" });
  assert.deepEqual(toPayload(3, { minutes_cap: "500", sms_cap: "" }), { minutes_cap: 500 });
  assert.deepEqual(toPayload(4, { webhook_url: "" }), { webhook_url: "" });
  assert.ok(samePayload({ minutes_cap: 500 }, { minutes_cap: 500 }));
  assert.ok(!samePayload({ minutes_cap: 500 }, {}));
  assert.ok(!samePayload({}, null));
});

test("local validation", () => {
  assert.deepEqual(Object.keys(validate(1, { name: "", email: "x" })), ["name", "email"]);
  assert.deepEqual(Object.keys(validate(2, { plan: "pro", billing_country: "ZZ" })), ["billing_country"]);
  assert.deepEqual(validate(3, { minutes_cap: "", sms_cap: "0" }), {});
  assert.deepEqual(Object.keys(validate(3, { minutes_cap: "-1", sms_cap: "abc" })), ["minutes_cap", "sms_cap"]);
  assert.deepEqual(validate(4, { webhook_url: "" }), {});
  assert.deepEqual(Object.keys(validate(4, { webhook_url: "ftp://x" })), ["webhook_url"]);
});

test("an unchanged saved step never needs saving; a never-saved optional step does", () => {
  const s = loaded();
  assert.ok(([1, 2, 3, 4] as const).every((n) => !needsSave(s.steps[n], n)));
  assert.ok(needsSave(loaded({}).steps[3], 3));
});

test("the quirk: a refused step 2 keeps the typed value, the saved value, and every other step", () => {
  const s = run(loaded(), { type: "edit", step: 2, field: "billing_country", value: "CA" }, { type: "saving", step: 2 },
    { type: "rejected", step: 2, errors: { billing_country: "no" } });
  assert.equal(s.steps[2].draft.billing_country, "CA");
  assert.equal(s.steps[2].saved?.billing_country, "US");
  assert.equal(s.steps[2].status, "failed");
  assert.deepEqual(s.steps[4], loaded().steps[4]);
  assert.ok(!readyToSubmit(s));
  const back = reducer(s, { type: "revert", step: 2 });
  assert.equal(back.steps[2].draft.billing_country, "US");
  assert.ok(readyToSubmit(back));
});

test("typing during a save leaves the step unsaved when the older save lands", () => {
  const s = run(loaded(), { type: "edit", step: 1, field: "name", value: "B" }, { type: "saving", step: 1 },
    { type: "edit", step: 1, field: "name", value: "BC" }, { type: "saved", step: 1, data: { name: "B", email: "a@b.c" } });
  assert.equal(s.steps[1].draft.name, "BC");
  assert.equal(s.steps[1].status, "dirty");
});

test("a network failure keeps the text and claims nothing", () => {
  const s = run(loaded(), { type: "edit", step: 4, field: "webhook_url", value: "https://x" }, { type: "saving", step: 4 }, { type: "failed", step: 4, message: "m" });
  assert.equal(s.steps[4].draft.webhook_url, "https://x");
  assert.equal(s.steps[4].saved?.webhook_url, "");
  assert.ok(!readyToSubmit(s));
});

test("recovered edits are marked unsaved, and the notice ends when they are saved", () => {
  const s = loaded(FULL, { 1: { name: "Z", email: "a@b.c" } });
  assert.ok(s.recovered);
  assert.equal(s.steps[1].status, "dirty");
  assert.ok(!reducer(s, { type: "saved", step: 1, data: { name: "Z", email: "a@b.c" } }).recovered);
  assert.ok(!loaded(FULL, { 1: { name: "A", email: "a@b.c" } }).recovered);
});

test("dead end and step 4 lock", () => {
  assert.ok(deadEnd(loaded({ 4: { webhook_url: "" } })));
  assert.ok(!deadEnd(loaded()));
  assert.ok(!stepsOneToThreeSaved(loaded({ 1: FULL[1] })));
});

test("server wording hides internal names", () => assert.ok(!serverMessage("billing_country is required").includes("_")));
