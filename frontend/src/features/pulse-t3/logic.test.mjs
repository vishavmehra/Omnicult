// Run: node --test src/features/pulse-t3/logic.test.mjs (Node 22.18+ strips the TypeScript types). No framework, no network.
import assert from "node:assert/strict";
import test from "node:test";

import {
  ALERT_TYPES, describeRule, emptyForm, evaluationLine, eventActor, FATIGUE_DEFAULTS, formatRank, formatTau, formFromRule, linePaths, parseFatigueForm,
  parseRuleForm, plot, scopeText, summaryDetail, summaryHeadline,
} from "./logic.ts";

const summary = (over = {}) => ({
  predictor: "launch_score", label: "Launch Room score", pairs: 4, agree: 1, near: 2, differ: 1, concordant: 3, discordant: 3, tied: 0,
  kendall_tau_b: 0, reading: "mixed", ...over,
});

test("a rank is whole, or a mean of tied places", () => {
  assert.equal(formatRank(1), "1");
  assert.equal(formatRank(2.5), "2.5");
  assert.equal(formatTau(null), "n/a");
  assert.equal(formatTau(0), "0.00");
  assert.equal(formatTau(-0.3333), "-0.33");
  assert.equal(formatTau(1), "+1.00");
});

test("the summary words only the counts the API computed", () => {
  assert.equal(summaryHeadline(summary()), "a mixed order: 3 of 6 comparisons between two pairs agree");
  assert.equal(summaryHeadline(summary({ reading: "mostly_agrees", concordant: 5, discordant: 1 })), "mostly the same order: 5 of 6 comparisons between two pairs agree");
  assert.equal(summaryHeadline(summary({ pairs: 2, reading: "too_few_pairs", kendall_tau_b: null })), "2 pairs: too few to read an order");
  assert.equal(summaryHeadline(summary({ pairs: 0, reading: "too_few_pairs" })), "No pairs yet");
  assert.match(summaryDetail(summary()), /1 agree, 2 near, 1 differ across 4 pairs\. 3 ordered the opposite way, 0 tied\. Kendall's tau-b 0\.00\./);
  assert.match(summaryDetail(summary({ pairs: 2, reading: "too_few_pairs" })), /needs at least 3 pairs/);
});

test("the rule form reads percentages as ratios and refuses what the API would refuse", () => {
  const ok = parseRuleForm("ctr_drop", emptyForm("ctr_drop"));
  assert.deepEqual(ok, { ok: true, params: { ctr_drop_pct: 0.2 } });
  const cost = emptyForm("cost_spike");
  cost.costMetric = "cpm";
  assert.deepEqual(parseRuleForm("cost_spike", cost), { ok: true, params: { cost_spike_pct: 0.3, min_conversions: 30, cost_metric: "cpm" } });
  assert.deepEqual(parseRuleForm("prediction_miss", emptyForm("prediction_miss")), { ok: true, params: { min_rank_gap: 2 } });
  const bad = (type, key, value) => {
    const form = emptyForm(type);
    form.values[key] = value;
    const r = parseRuleForm(type, form);
    return r.ok ? null : r.errors[key];
  };
  assert.ok(bad("ctr_drop", "ctr_drop_pct", "0"), "0% is not above 0");
  assert.ok(bad("ctr_drop", "ctr_drop_pct", "101"));
  assert.equal(bad("ctr_drop", "ctr_drop_pct", "100"), null);
  assert.ok(bad("ctr_drop", "ctr_drop_pct", ""));
  assert.ok(bad("frequency_fatigue", "frequency_threshold", "1"), "frequency must be above 1");
  assert.equal(bad("frequency_fatigue", "frequency_threshold", "20"), null);
  assert.ok(bad("frequency_fatigue", "frequency_threshold", "20.5"));
  assert.ok(bad("cost_spike", "cost_spike_pct", "501"));
  assert.equal(bad("cost_spike", "cost_spike_pct", "500"), null);
  assert.ok(bad("cost_spike", "min_conversions", "0"));
  assert.ok(bad("cost_spike", "min_conversions", "2.5"), "a whole number");
  assert.ok(bad("cost_spike", "min_conversions", "10001"));
  assert.ok(bad("prediction_miss", "min_rank_gap", "21"));
  const unnamed = emptyForm("ctr_drop");
  unnamed.name = "  ";
  assert.ok(!parseRuleForm("ctr_drop", unnamed).ok);
});

test("every alert type lists the fields its rule reads, and the form round-trips a saved rule", () => {
  assert.deepEqual(ALERT_TYPES.ctr_drop.fields, ["ctr_drop_pct"]);
  assert.deepEqual(ALERT_TYPES.frequency_fatigue.fields, ["frequency_threshold", "frequency_min_ctr_decline_pct"]);
  const rule = {
    id: "r1", name: "Kerala cost", alert_type: "cost_spike", region_code: "IN-KL", version_label: null, enabled: true, open_alerts: 0,
    params: { ctr_drop_pct: null, frequency_threshold: null, frequency_min_ctr_decline_pct: null, cost_spike_pct: 0.35, min_conversions: 40, cost_metric: "cpa", min_rank_gap: null },
    created_at: "2026-11-18T00:00:00Z", updated_at: "2026-11-18T00:00:00Z",
  };
  const form = formFromRule(rule);
  assert.deepEqual(form.values, { cost_spike_pct: "35", min_conversions: "40" });
  assert.equal(form.costMetric, "cpa");
  assert.deepEqual(parseRuleForm("cost_spike", form), { ok: true, params: { cost_spike_pct: 0.35, min_conversions: 40, cost_metric: "cpa" } });
  assert.equal(describeRule(rule), "CPA 35% or more above the region average, CPA from 40 conversions");
  assert.equal(scopeText(rule, (c) => ({ "IN-KL": "Kerala" })[c]), "Kerala, every version");
  assert.equal(scopeText({ region_code: null, version_label: "v1" }, () => ""), "Every region, v1");
});

test("an event names who or what did it", () => {
  assert.equal(eventActor({ trigger: "user", actor_user_id: "u1" }), "a person");
  assert.equal(eventActor({ trigger: "scheduler", actor_user_id: null }), "scheduled run");
  assert.equal(eventActor({ trigger: "manual", actor_user_id: "u1" }), "a person, on demand");
  assert.equal(
    evaluationLine({ trigger: "manual", rules_evaluated: 4, alerts_found: 1, opened: 1, reopened: 0, resolved: 0, not_evaluated: 2 }),
    "4 rules read, 1 alert firing, 1 opened or reopened, 2 not readable",
  );
});

test("fatigue thresholds use the API's bounds", () => {
  assert.deepEqual(parseFatigueForm(FATIGUE_DEFAULTS), { ok: true, query: { ctr_decline_pct: 0.1, view_rate_decline_pct: 0.1, frequency_threshold: 2.5 } });
  const bad = parseFatigueForm({ ctr: "0", viewRate: "101", frequency: "1" });
  assert.ok(!bad.ok && bad.errors.ctr && bad.errors.viewRate && bad.errors.frequency);
});

test("a series never draws a missing day as zero, and provisional days are a dashed continuation", () => {
  const days = [
    { date: "2026-11-01", value: 0.01, provisional: false },
    { date: "2026-11-02", value: null, provisional: false },
    { date: "2026-11-03", value: 0.02, provisional: false },
    { date: "2026-11-04", value: 0.015, provisional: true },
  ];
  const { points, max } = plot(days, 100, 50, { l: 0, r: 0, t: 0, b: 0 });
  assert.equal(points.length, 3);
  assert.ok(max > 0.02);
  assert.deepEqual(points.map((p) => p.x), [0, 200 / 3, 100]);
  const { settled, provisional } = linePaths(points);
  assert.match(settled, /^M0\.0 .* L66\.7 /);
  assert.match(provisional, /^M66\.7 .* L100\.0 /);
  assert.deepEqual(plot([], 100, 50, { l: 0, r: 0, t: 0, b: 0 }).points, []);
});
