// Run: node --test src/components/shell/workspaces.test.mjs (Node 22.18+ strips the TypeScript types). No framework, no network.
import assert from "node:assert/strict";
import test from "node:test";

import { PLATFORM_FEATURES, WORKSPACES, WORKSPACE_ORDER, navFeatures, workspaceViews } from "./workspaces.ts";

const ID = "c1";
const chips = (key) => workspaceViews(key).map((v) => v.href(ID));

// Every tab or view a workspace page can show, as the address that opens it. The chip row is the only tab row, so each must have a chip.
const PLACES = {
  desk: ["", "?tab=brand-kit", "?tab=creative"],
  lens: ["", "?view=profile", "?view=calendar", "?view=compare", "?view=language-map", "?view=trends", "?view=shelf"],
  studio: ["?tab=elements", "?tab=transcreate", "?tab=direct", "?tab=compare", "?tab=glossary", "?tab=format", "?tab=claims", "?tab=script", "/xray", "/remake", "/remake?view=sound", "/remake?view=video", "/generate"],
  lab: ["", "?tab=study", "?tab=ask", "?tab=risk", "?tab=focus", "?tab=buzz", "?tab=check"],
  launch: ["", "?tab=compare", "?tab=region-plan", "?tab=review-links", "?tab=asset-pack"],
  pulse: ["", "?view=predicted", "?view=alerts", "?view=comments", "?view=fatigue", "?view=digest"],
  proof: ["", "?view=map", "?view=search", "?view=history", "?view=health"],
};

test("every tab of every workspace has a chip", () => {
  for (const key of WORKSPACE_ORDER) {
    const have = chips(key);
    for (const place of PLACES[key]) assert.ok(have.includes(`/app/c/${ID}/${key}${place}`), `${key}: no chip for ${place || "the default tab"}`);
  }
});

test("no two chips open the same place, and merged features share one chip", () => {
  for (const key of WORKSPACE_ORDER) assert.equal(new Set(chips(key)).size, chips(key).length, key);
  const names = (key) => workspaceViews(key).map((v) => v.name);
  assert.ok(names("studio").includes("Transcreate · Tone Dials"));
  assert.ok(names("lens").includes("State Profile · Evidence Meter"));
  assert.ok(names("proof").includes("Run History · Resumable Runs · Model Gateway"));
});

test("action-only features stay in the catalogue but are never listed", () => {
  const actions = WORKSPACE_ORDER.flatMap((k) => WORKSPACES[k].features).filter((f) => f.action);
  assert.deepEqual(actions.map((f) => f.id), [5, 6]);
  for (const key of WORKSPACE_ORDER) {
    assert.ok(navFeatures(key).every((f) => !f.action && f.href));
    assert.ok(workspaceViews(key).every((v) => !/Command Bar|Demo Mode/.test(v.name)));
  }
  const built = [...WORKSPACE_ORDER.flatMap((k) => WORKSPACES[k].features), ...PLATFORM_FEATURES].filter((f) => f.status === "built");
  assert.equal(built.length, 56);
});
