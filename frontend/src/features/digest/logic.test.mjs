// Run: node --test src/features/digest/logic.test.mjs (Node 22.18+ strips the TypeScript types). No framework, no network.
import assert from "node:assert/strict";
import test from "node:test";

import {
  addDays, asPulseView, highlight, isoWeekLabel, langTag, runWeeks, sentimentRead, shareText, sourceHref, weekChoices, weekSpan,
} from "./logic.ts";

test("the Pulse view comes from the address and falls back to the dashboard", () => {
  assert.equal(asPulseView("comments"), "comments");
  assert.equal(asPulseView("digest"), "digest");
  for (const bad of [null, undefined, "", "nope", "Comments"]) assert.equal(asPulseView(bad), "overview");
});

test("sentiment shares count only the comments a model labelled", () => {
  assert.equal(sentimentRead(null), null);
  assert.equal(sentimentRead({ positive: 0, neutral: 0, negative: 0, mixed: 0, unread: 9 }), null);
  const r = sentimentRead({ positive: 2, neutral: 1, negative: 1, mixed: 0, unread: 6 });
  assert.equal(r.read, 4);
  assert.deepEqual(r.shares, { positive: 0.5, neutral: 0.25, negative: 0.25, mixed: 0 });
  assert.equal(shareText(0.256), "26%");
  assert.equal(shareText(null), "n/a");
});

test("a matched term is marked where it occurs, whatever its case", () => {
  assert.deepEqual(highlight("Best faral tin, they say", "best faral"), [
    { text: "Best faral", match: true },
    { text: " tin, they say", match: false },
  ]);
  assert.deepEqual(highlight("प्रत्येक जाहिरातीत सर्वोत्तम म्हणतात", "सर्वोत्तम").map((s) => s.match), [false, true, false]);
  assert.deepEqual(highlight("no match here", "onam"), [{ text: "no match here", match: false }]);
  assert.deepEqual(highlight("text", null), [{ text: "text", match: false }]);
  assert.deepEqual(highlight("Onam", "onam"), [{ text: "Onam", match: true }]);
});

test("a regional language in Latin letters is tagged as such, so no regional face is applied", () => {
  assert.equal(langTag("ta", "Taml"), "ta");
  assert.equal(langTag("ta", "Latn"), "ta-Latn");
  assert.equal(langTag("en", "Latn"), "en");
});

test("ISO weeks follow the standard, across a year boundary", () => {
  assert.equal(isoWeekLabel("2026-11-09"), "2026-W46");
  assert.equal(isoWeekLabel("2026-11-15"), "2026-W46");
  assert.equal(isoWeekLabel("2026-11-16"), "2026-W47");
  assert.equal(isoWeekLabel("2026-12-31"), "2026-W53");
  assert.equal(isoWeekLabel("2027-01-03"), "2026-W53");
  assert.equal(isoWeekLabel("2027-01-04"), "2027-W01");
  assert.equal(isoWeekLabel("2024-12-30"), "2025-W01");
  assert.equal(isoWeekLabel("2026-01-01"), "2026-W01");
});

test("the week choices start at the week in progress and step back a week at a time", () => {
  const choices = weekChoices({ start: "2026-11-16", end: "2026-11-22" }, 3);
  assert.deepEqual(choices.map((c) => c.value), ["2026-11-16", "2026-11-09", "2026-11-02"]);
  assert.equal(choices[0].label, "2026-W47, 16 Nov to 22 Nov (this week)");
  assert.equal(choices[1].label, "2026-W46, 9 Nov to 15 Nov");
  assert.equal(addDays("2026-11-02", -7), "2026-10-26");
  assert.equal(weekSpan("2026-12-28", "2027-01-03"), "28 Dec to 3 Jan");
});

test("the sample run is cut into seven-day weeks from its first day", () => {
  const weeks = runWeeks("2026-10-27", "2026-11-16");
  assert.deepEqual(weeks.map((w) => [w.label, w.from, w.to]), [
    ["Week 1", "2026-10-27", "2026-11-02"], ["Week 2", "2026-11-03", "2026-11-09"], ["Week 3", "2026-11-10", "2026-11-16"],
  ]);
  assert.equal(runWeeks("2026-10-27", "2026-11-12").at(-1).to, "2026-11-12");
  assert.deepEqual(runWeeks(null, null), []);
});

test("a digest source leads to the record behind it", () => {
  const id = "c1";
  assert.equal(sourceHref(id, { workspace: "pulse", view: "comments", ref: "cm-0001" }), "/app/c/c1/pulse?view=comments");
  assert.equal(sourceHref(id, { workspace: "pulse", view: null, ref: null }), "/app/c/c1/pulse");
  assert.equal(sourceHref(id, { workspace: "studio", view: null, ref: "v9" }), "/app/c/c1/studio?v=v9");
  assert.equal(sourceHref(id, { workspace: "launch", view: null, ref: "x" }), "/app/c/c1/launch");
});
