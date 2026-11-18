// Runnable check for the pure Studio logic (no framework, no network):
//   node frontend/src/features/studio/model.check.mjs
// Node strips the types from model.ts. Exits non-zero on the first failed assertion.
import assert from "node:assert/strict";

import { asLines, buildTree, lineFor, lineage, numberVersions, originalOf, pairElements } from "./model.ts";

const v = (id, parent, at, extra = {}) => ({ id, parent_id: parent, created_at: `2026-11-18T10:00:0${at}Z`, label: id, region_code: null, language: null, actor: "user", ...extra });
// o is the original; a (Tamil) and b (Malayalam) both come from o, so they are two branches; c follows a.
const versions = [v("o", null, 0), v("a", "o", 1), v("b", "o", 2), v("c", "a", 3)];

assert.deepEqual([...numberVersions(versions)], [["o", 1], ["a", 2], ["b", 3], ["c", 4]]);
assert.deepEqual(
  buildTree(versions).map((r) => [r.version.id, r.depth, r.branchStart]),
  [["o", 0, false], ["a", 1, true], ["c", 1, false], ["b", 1, true]],
  "a node continues its parent's line unless the parent has several children",
);
assert.deepEqual(lineage(versions, "c").map((x) => x.id), ["c", "a", "o"]);
assert.equal(originalOf(versions, "c")?.id, "o");
assert.equal(originalOf(versions, "o")?.id, "o");

const node = (elements) => ({ elements });
const el = (id, value) => ({ id, kind: "headline", value });
const pairs = pairElements(node([el("h", "Hi"), el("gone", "x")]), node([el("h", "Namaste"), el("new", "y")]));
assert.deepEqual(pairs.map((p) => [p.id, p.original?.value ?? null, p.current?.value ?? null]), [["h", "Hi", "Namaste"], ["new", null, "y"], ["gone", "x", null]]);

const line = (value, passed = true) => ({ element_id: "h", kind: "headline", regional_copy: value, back_translation: `bt:${value}`, passed, problems: [], script_check: {}, term_checks: {} });
const op = (id, result, lines, status = "applied") => ({ id, kind: "transcreate", status, result_version_id: result, params: { lines } });
const ops = [op("t1", "a", [line("tamil-1")])];
const chain = lineage(versions, "c");
assert.equal(lineFor(ops, chain, "h", "tamil-1")?.state, "current");
assert.equal(lineFor(ops, chain, "h", "edited by hand")?.state, "edited", "a later edit keeps the earlier line, marked as edited");
assert.equal(lineFor(ops, chain, "other", "x"), null);
assert.equal(lineFor([op("t2", "a", [line("tamil-1", false)])], chain, "h", "tamil-1"), null, "a line that failed its checks was never applied");
assert.equal(lineFor([op("t3", "a", [line("tamil-1")], "rejected")], chain, "h", "tamil-1"), null);
assert.deepEqual(asLines({ lines: [line("ok"), { element_id: 1 }, null] }).length, 1, "malformed lines are ignored");
assert.deepEqual(asLines(undefined), []);

console.log("model.check.mjs: all assertions passed");
