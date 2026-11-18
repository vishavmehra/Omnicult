/**
 * Runnable check for the Audience Lab rules that must never silently change. No framework, no network:
 *   node frontend/scripts/lab-logic-check.mjs
 * Node 24 strips the types of the .ts files imported here; they use only `import type`, so nothing needs a bundler.
 */
import assert from "node:assert/strict";

import { buildElements, buildScenes } from "../src/features/lab/risk-input.ts";
import { citedClaims, describeAnchor, isGrounded, isSplit, langFor, pluralise, sortFindings, tallyBy } from "../src/features/lab/logic.ts";

const claim = (id, kind) => ({ id, kind, region_code: "IN-TN", category: "festival", attribute: "x", value_text: "t", confidence: "moderate" });
const claims = [claim("a", "observed"), claim("b", "calculated"), claim("c", "interpretation"), claim("d", "synthetic")];

// A statement is claim-supported only when it cites an observed or calculated claim the run actually had.
assert.equal(isGrounded({ basis: "claim_supported", claim_ids: ["a"] }, claims), true);
assert.equal(isGrounded({ basis: "claim_supported", claim_ids: ["b"] }, claims), true);
assert.equal(isGrounded({ basis: "claim_supported", claim_ids: ["c"] }, claims), false, "an interpretation never grounds a statement");
assert.equal(isGrounded({ basis: "claim_supported", claim_ids: ["d"] }, claims), false, "a synthetic claim never grounds a statement");
assert.equal(isGrounded({ basis: "claim_supported", claim_ids: ["zzz"] }, claims), false, "a claim the run was not given grounds nothing");
assert.equal(isGrounded({ basis: "claim_supported", claim_ids: [] }, claims), false);
assert.equal(isGrounded({ basis: "interpretation", claim_ids: ["a"] }, claims), false, "the API's own label is respected too");
assert.deepEqual(citedClaims({ claim_ids: ["a", "zzz", "c"] }, claims).map((c) => c.id), ["a", "c"]);

// Findings: severity first, blocking Go first within a level, then the order the check produced them.
const f = (id, severity, blocks_go, ordinal) => ({ id, severity, blocks_go, ordinal });
assert.deepEqual(
  sortFindings([f("m1", "medium", false, 0), f("l1", "low", true, 1), f("h2", "high", false, 3), f("h1", "high", true, 2), f("m2", "medium", true, 4)]).map((x) => x.id),
  ["h1", "h2", "m2", "m1", "l1"],
);

// Reaction tallies are counted, not estimated; a missing response is skipped.
const p = (tier, sentiment) => ({ city_tier: tier, response: sentiment ? { sentiment } : null });
const rows = tallyBy([p("tier1", "positive"), p("tier1", "negative"), p("rural", "positive"), p("rural", null)], (x) => ({ value: x.city_tier, label: x.city_tier }));
assert.deepEqual(rows.map((r) => [r.value, r.total]), [["tier1", 2], ["rural", 1]]);
assert.equal(rows[0].counts.positive, 1);

// "Split" needs two or more reactions and no category holding 70% or more.
const dist = (counts) => ({ denominator: Object.values(counts).reduce((a, b) => a + b, 0), failed: 0, counts, rates: {} });
assert.equal(isSplit(dist({ positive: 3, mixed: 0, neutral: 0, negative: 3, confused: 0 })), true);
assert.equal(isSplit(dist({ positive: 9, mixed: 0, neutral: 0, negative: 1, confused: 0 })), false);
assert.equal(isSplit(dist({ positive: 4, mixed: 0, neutral: 0, negative: 0, confused: 0 })), false);

// Anchors read in words; Indic text gets its language only when it is Indic.
assert.deepEqual(describeAnchor({ scene_id: "S5", start_ms: 19900, end_ms: 29400, bbox: [0.1, 0.85, 0.8, 0.08] }), {
  scene: "S5",
  time: "19.9 s to 29.4 s",
  box: "80% wide, 8% high, 10% from the left and 85% from the top",
});
assert.deepEqual(describeAnchor({}), { scene: null, time: null, box: null });
assert.equal(langFor("Diwali means faral", "mr"), undefined);
assert.equal(langFor("दिवाळी म्हणजे फराळ", "mr"), "mr");
assert.equal(pluralise(1, "finding"), "1 finding");
assert.equal(pluralise(3, "finding"), "3 findings");

// Risk Check input: copy is kept first when the 60-element cap bites; scenes are timed only on an id match.
const el = (id, kind, scene_id = null) => ({ id, kind, value: id, language: null, script: null, bbox: null, scene_id, locked: false });
const many = [...Array.from({ length: 58 }, (_, i) => el(`img${i}`, "image_region")), el("cta", "cta"), el("head", "headline"), el("tag", "tagline")];
const built = buildElements(many);
assert.equal(built.elements.length, 60);
assert.equal(built.omitted, 1);
assert.deepEqual(built.elements.slice(0, 3).map((e) => e.id), ["head", "cta", "tag"]);
assert.equal(built.elements.some((e) => e.id === "img57"), false, "the last non-copy element is the one left out");
const { scenes, timed } = buildScenes([el("a", "headline", "S1"), el("b", "caption", "S5"), el("c", "logo", null)], [{ id: "uuid-1", start_ms: 0, end_ms: 4700, setting: "Balcony", anchor: { scene_id: "S1" } }]);
assert.deepEqual(scenes.map((s) => [s.id, s.start_ms, s.end_ms]), [["S1", 0, 4700], ["S5", null, null]]);
assert.equal(timed, 1);

console.log("lab logic: all checks passed");
