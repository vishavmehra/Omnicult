// Run: node --test src/features/pulse/logic.test.mjs (Node 22.18+ strips the TypeScript types). No framework, no network.
import assert from "node:assert/strict";
import test from "node:test";

import {
  addDays, alertHeadline, classifyCostPattern, formatPctChange, formatPoints, formatSpan, formatTick, formatValue, judge,
  niceTicks, parseThresholds, rangePresets, shortVersion, slotFor, sortRegions, standout, DEFAULT_THRESHOLDS, NOT_AVAILABLE,
} from "./logic.ts";

test("a missing value is not available, never zero", () => {
  for (const unit of ["count", "inr", "ratio", "multiple"]) {
    assert.equal(formatValue(null, unit), NOT_AVAILABLE);
    assert.equal(formatValue(undefined, unit), NOT_AVAILABLE);
  }
  assert.equal(formatValue(0, "ratio"), "0.00%");
  assert.equal(formatPctChange(null), NOT_AVAILABLE);
  assert.equal(formatPoints(null), NOT_AVAILABLE);
});

test("units format as the ledger expects", () => {
  assert.equal(formatValue(0.00789, "ratio"), "0.79%");
  assert.equal(formatValue(0.2359, "ratio"), "23.6%");
  assert.equal(formatValue(-0.0567, "ratio", { signed: true }), "-5.67%");
  assert.equal(formatValue(2.4587, "multiple"), "2.46×");
  assert.equal(formatValue(74.5227, "inr"), "₹74.52");
  assert.equal(formatValue(377366.65, "inr"), "₹3,77,367");
  assert.equal(formatValue(377366.65, "inr", { compact: true }), "₹377K");
  assert.equal(formatValue(5063781, "count"), "50,63,781");
  assert.equal(formatValue(5063781, "count", { compact: true }), "5.06M");
  assert.equal(formatPctChange(1.0098), "+101%");
  assert.equal(formatPctChange(-0.714), "-71%");
  assert.equal(formatPctChange(0.056), "+5.6%");
});

test("dates and range presets", () => {
  assert.equal(addDays("2026-10-27", 20), "2026-11-16");
  assert.equal(formatSpan("2026-10-27", "2026-11-16"), "27 Oct to 16 Nov 2026");
  const presets = rangePresets({ date_from: "2026-10-27", date_to: "2026-11-16", provisional_from: "2026-11-15" });
  assert.deepEqual(presets.map((p) => p.key), ["all", "settled", "last7"]);
  assert.deepEqual(presets[1].range, { from: null, to: "2026-11-14" });
  assert.deepEqual(presets[2].range, { from: "2026-11-10", to: null });
  assert.deepEqual(rangePresets({ date_from: "2026-10-27", date_to: "2026-11-16", provisional_from: null }).map((p) => p.key), ["all", "last7"]);
});

test("better and worse depend on the metric's direction", () => {
  assert.equal(judge("ctr", 1.01, 0.005), "better");
  assert.equal(judge("cpa", -0.71, -800), "better");
  assert.equal(judge("cpm", 0.202, 13), "worse");
  assert.equal(judge("cpm", -0.005, -0.4), "same");
  assert.equal(judge("impressions", 0.4, 100), "neutral");
  assert.equal(judge("ctr", null, null), "neutral");
  // a gap between two weekly changes is read in points, not as a percentage of a negative baseline
  assert.equal(judge("ctr_change_vs_first_week", -0.76, 0.24), "better");
});

test("series colours follow the entity, not its position", () => {
  assert.equal(slotFor("region", "IN-WB"), 4);
  assert.equal(slotFor("region", "IN-WB", ["IN-WB"]), 4);
  assert.equal(slotFor("version", "v1 Original (Marathi)"), 1);
  assert.equal(slotFor("version", "v3 Adapted B (local festival reference)", ["v3 Adapted B (local festival reference)"]), 3);
  assert.equal(slotFor("platform", "youtube"), 2);
  assert.equal(shortVersion("v2 Adapted A (regional language)"), "Adapted A");
  assert.equal(shortVersion("v1 Original (Marathi)"), "Original");
  assert.equal(shortVersion("Plain label"), "Plain label");
});

test("regions keep the campaign's order, unknown ones last", () => {
  assert.deepEqual(sortRegions(["IN-WB", "IN-KL", "IN-MH", "IN-TN"], (c) => c), ["IN-MH", "IN-TN", "IN-KL", "IN-WB"]);
  assert.deepEqual(sortRegions(["IN-ZZ", "IN-AA", "IN-TN"], (c) => c), ["IN-TN", "IN-AA", "IN-ZZ"]);
});

test("axis ticks start at zero and cover the data", () => {
  assert.deepEqual(niceTicks(0.0103), [0, 0.0025, 0.005, 0.0075, 0.01, 0.0125]);
  assert.deepEqual(niceTicks(2134), [0, 500, 1000, 1500, 2000, 2500]);
  assert.deepEqual(niceTicks(0), [0, 1]);
  assert.equal(formatTick(0.0125, "ratio"), "1.25%");
  assert.equal(formatTick(0.1, "ratio"), "10%");
  assert.equal(formatTick(1500, "inr"), "₹1,500");
});

const region = (rows) => ({
  region_code: "IN-TN",
  region_name: "Tamil Nadu",
  baseline_version: "v1",
  versions: rows.map(([label, base, value, pct]) => ({
    version_label: label,
    is_baseline: base,
    first_day: "2026-10-27",
    last_day: "2026-11-16",
    metrics: [
      { metric: "cpa", label: "CPA", unit: "inr", value, provisional: false, delta_vs_baseline: base ? null : value - rows[0][2], delta_pct_vs_baseline: pct },
    ],
  })),
});

test("the version that leads is found per metric direction", () => {
  const r = region([["v1", true, 1221, null], ["v2", false, 349, -0.714], ["v3", false, 477, -0.61]]);
  const s = standout(r, "cpa");
  assert.equal(s.versionLabel, "v2");
  assert.equal(s.baselineLeads, false);
  assert.equal(s.deltaPct, -0.714);
  assert.equal(standout(r, "impressions"), null);
  assert.equal(standout(region([["v1", true, 100, null]]), "cpa"), null);
  assert.equal(standout(region([["v1", true, 100, null], ["v2", false, 140, 0.4]]), "cpa").baselineLeads, true);
});

const days = (values, provisionalFrom = Infinity) =>
  values.map((value, i) => ({ date: addDays("2026-10-27", i), value, provisional: i >= provisionalFrom }));

test("a cost alert tells a standing gap from a rise", () => {
  // Original where it was costlier from day one: already far above the region average of 480 in week one.
  const persistent = classifyCostPattern(
    days([1100, 1250, 1180, 1300, 1220, 1190, 1240, 1210, 1260, 1230, 1200, 1250, 1220, 1240, 1180, 1100, 9]),
    480,
    0.3,
  );
  assert.equal(persistent.kind, "persistent");
  assert.ok(persistent.firstVsAverage > 1);
  // In line with the average for ten days, then up by about a third.
  const flat = Array(10).fill(70);
  const rising = classifyCostPattern(days([...flat, ...Array(7).fill(95)]), 70, 0.3);
  assert.equal(rising.kind, "rising");
  assert.ok(Math.abs(rising.firstVsAverage) < 0.01);
  assert.ok(rising.lastVsAverage > 0.3);
  // provisional and missing days are never used, and thin data is not guessed at
  assert.equal(classifyCostPattern(days([1, 2, 3, null, 5]), 3, 0.3).kind, "unknown");
  const withProvisional = classifyCostPattern(days([...flat, ...Array(7).fill(95), 5, 5], 17), 70, 0.3);
  assert.equal(withProvisional.kind, "rising");
  assert.equal(withProvisional.lastWeek, 95);
});

test("alert headlines carry the arithmetic", () => {
  const base = {
    campaign_id: "c", region_code: "IN-TN", version_label: "v1", window_from: "2026-11-08", window_to: "2026-11-14",
    as_of: "2026-11-14", suggested_action: "", source_path: "", is_sample: true, label: "",
  };
  assert.equal(
    alertHeadline({ ...base, alert_type: "ctr_drop", metric: "ctr", threshold: -0.2, observed_value: -0.319, comparison_value: 0.005, comparison: "" }, "Kerala"),
    "CTR is 31.9% below this version's first week",
  );
  assert.equal(
    alertHeadline({ ...base, alert_type: "cost_spike", metric: "cpa", threshold: 0.3, observed_value: 1.539, comparison_value: 482.08, comparison: "" }, "Tamil Nadu"),
    "CPA is 153.9% above the Tamil Nadu average",
  );
});

test("threshold form maps percent to ratio and rejects out-of-range values", () => {
  const ok = parseThresholds(DEFAULT_THRESHOLDS);
  assert.equal(ok.ok, true);
  assert.deepEqual(ok.query, { ctr_drop_pct: 0.2, frequency_threshold: 2.5, frequency_min_ctr_decline_pct: 0.1, cost_spike_pct: 0.3, min_conversions: 30 });
  const bad = parseThresholds({ ctrDropPct: "0", frequency: "1", frequencyCtrPct: "", costSpikePct: "501", minConversions: "2.5" });
  assert.equal(bad.ok, false);
  assert.deepEqual(Object.keys(bad.errors).sort(), ["costSpikePct", "ctrDropPct", "frequency", "frequencyCtrPct", "minConversions"]);
});
