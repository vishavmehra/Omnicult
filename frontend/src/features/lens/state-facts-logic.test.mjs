// Run: node --test src/features/lens/state-facts-logic.test.mjs (Node 22.18+ strips the TypeScript types). No framework, no network.
import assert from "node:assert/strict";
import test from "node:test";

import { barPosition, barScale, factShape, formatFact, versusIndia } from "./state-facts-logic.ts";

test("figures keep the precision the source gives", () => {
  assert.equal(formatFact("percent", 46.9), "46.9%");
  assert.equal(formatFact("percent", 99), "99.0%");
  assert.equal(formatFact("per100", 104.29), "104.3");
  assert.match(formatFact("inr", 275583), /^₹\s?2,75,583$/);
  assert.equal(formatFact("million", 306.842), "306.8 million");
  assert.equal(formatFact("million", 0.738), "0.74 million");
  assert.equal(versusIndia("million", 306.8, 2948.2), null); // a state's visits beside the country's total say nothing
  assert.equal(formatFact("whole", 1033), "1,033");
  assert.equal(formatFact("whole", 11320.4), "11,320");
  assert.equal(formatFact("decimal", 3.8946), "3.9");
  assert.equal(formatFact("million", 77.609), "77.6 million");
});

test("a bar for a percentage is out of 100 and any other bar is a little taller than its tallest value", () => {
  assert.equal(barScale("percent", 12, 99), 100);
  assert.ok(Math.abs(barScale("inr", 5701, 8165, null) - 8165 * 1.12) < 1e-9);
  assert.equal(barScale("per100"), 1);
  assert.equal(barPosition(50, 100), 50);
  assert.equal(barPosition(500, 100), 100);
  assert.equal(barPosition(-5, 100), 0);
});

test("the comparison with India says which way and by how much, or says nothing without an all-India figure", () => {
  assert.deepEqual(versusIndia("percent", 46.9, 33.3), { direction: "above", text: "13.6 pts above India" });
  assert.deepEqual(versusIndia("per100", 79.41, 68.19), { direction: "above", text: "11.2 above India" });
  assert.equal(versusIndia("percent", 80.1, 72.98)?.direction, "above");
  assert.deepEqual(versusIndia("percent", 20, 25), { direction: "below", text: "5.0 pts below India" });
  assert.equal(versusIndia("inr", 100, 100)?.text, "Level with India");
  assert.match(versusIndia("inr", 8165, 6000)?.text ?? "", /above India$/);
  assert.deepEqual(versusIndia("whole", 546.69, 427.2), { direction: "above", text: "119 above India" });
  assert.deepEqual(versusIndia("whole", 1208, 1691.7), { direction: "below", text: "484 below India" });
  assert.equal(versusIndia("whole", 71.2, 71)?.text, "Level with India"); // 0.2 of a point is not a whole unit
  assert.deepEqual(versusIndia("inr", 20707.75, 21036.19), { direction: "below", text: "₹328 below India" });
  assert.equal(versusIndia("percent", 20, null), null);
  assert.equal(versusIndia("percent", 20, undefined), null);
});

test("a fact is drawn by what it holds", () => {
  const none = { length: 0 };
  assert.equal(factShape({ unit: "inr", value: null, series: none, parts: { length: 2 } }), "parts");
  assert.equal(factShape({ unit: "percent", value: 80, series: { length: 2 }, parts: none }), "trend");
  assert.equal(factShape({ unit: "percent", value: 46.9, series: { length: 1 }, parts: none }), "ring");
  assert.equal(factShape({ unit: "per100", value: 79, series: { length: 1 }, parts: { length: 2 } }), "bar");
});
