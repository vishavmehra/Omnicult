// Run: node --test src/features/lens/calendar-logic.test.mjs (Node 22.18+ strips the TypeScript types). No framework, no network.
import assert from "node:assert/strict";
import test from "node:test";

import {
  addDays, bandRun, byDate, countLine, dayAriaLabel, isoOf, monthSpan, monthWeeks, moveDate, nearest, startDay, strongestKind, weekday,
} from "./calendar-logic.ts";

const e = (date, name, kind, extra = {}) => ({ key: `${date}:${name}`, date, name, kind, about: null, why: [], sources: [], claim_id: null, tentative: false, in_window: null, ...extra });

test("months are weeks of seven, Monday first, padded with nulls", () => {
  const apr = monthWeeks(2027, 4); // 1 April 2027 is a Thursday
  assert.equal(weekday("2027-04-01"), 3);
  assert.deepEqual(apr[0].slice(0, 4), [null, null, null, "2027-04-01"]);
  assert.ok(apr.every((w) => w.length === 7));
  assert.equal(apr.flat().filter(Boolean).length, 30);
  assert.equal(monthWeeks(2028, 2).flat().filter(Boolean).length, 29); // leap year
  assert.equal(monthWeeks(2027, 2).length, 4); // February 2027 starts on a Monday and fills four rows exactly
  assert.equal(monthWeeks(2026, 2).length, 5); // 1 February 2026 is a Sunday
});

test("days add across months and years without a time-zone shift", () => {
  assert.equal(addDays("2027-03-31", 1), "2027-04-01");
  assert.equal(addDays("2027-01-01", -1), "2026-12-31");
  assert.equal(addDays("2027-03-28", 7), "2027-04-04"); // across a European DST change
  assert.equal(isoOf(new Date(2027, 3, 14, 23, 59)), "2027-04-14");
});

test("keys move by day, week and month, and never leave the year", () => {
  assert.equal(moveDate("ArrowRight", "2027-04-30", 2027), "2027-05-01");
  assert.equal(moveDate("ArrowDown", "2027-04-28", 2027), "2027-05-05");
  assert.equal(moveDate("ArrowLeft", "2027-01-01", 2027), "2027-01-01");
  assert.equal(moveDate("ArrowDown", "2027-12-30", 2027), "2027-12-30");
  assert.equal(moveDate("Home", "2027-04-14", 2027), "2027-04-12"); // Wednesday to Monday
  assert.equal(moveDate("End", "2027-04-14", 2027), "2027-04-18");
  assert.equal(moveDate("Home", "2027-04-02", 2027), "2027-04-01"); // the row starts on the 1st
  assert.equal(moveDate("End", "2027-04-28", 2027), "2027-04-30");
  assert.equal(moveDate("PageDown", "2027-01-31", 2027), "2027-02-28");
  assert.equal(moveDate("PageUp", "2027-01-15", 2027), "2027-01-15");
  assert.equal(moveDate("Enter", "2027-01-15", 2027), null);
});

test("counts and labels come from the entries", () => {
  const list = [e("2027-04-14", "Vishu", "festival"), e("2027-04-14", "Ambedkar Jayanti", "observance"), e("2027-01-26", "Republic Day", "public_holiday")];
  assert.equal(countLine(list), "3 dated moments: 1 public holiday, 1 festival, 1 observance");
  assert.equal(countLine([list[0]]), "1 dated moment: 1 festival");
  assert.equal(countLine([]), "No dated moments");
  const days = byDate(list);
  assert.equal(days.get("2027-04-14").length, 2);
  assert.equal(strongestKind(days.get("2027-04-14")), "festival");
  assert.equal(
    dayAriaLabel("2027-04-14", days.get("2027-04-14"), "campaign dates", false),
    "14 April 2027: Vishu, festival; Ambedkar Jayanti, observance. Inside the campaign dates.",
  );
  assert.equal(dayAriaLabel("2027-04-15", undefined, null, true), "15 April 2027: no dated moment. Today.");
  assert.match(dayAriaLabel("2027-04-10", [e("2027-04-10", "Eid", "public_holiday", { tentative: true })], null, false), /Eid, public holiday, tentative date\./);
});

test("the window band runs across a week row and marks its ends", () => {
  const w = { date_from: "2027-04-14", date_to: "2027-04-20" };
  const [, , third, fourth] = monthWeeks(2027, 4); // 12-18 and 19-25 April
  assert.deepEqual(bandRun(third, w), { start: 2, end: 6, opens: true, closes: false });
  assert.deepEqual(bandRun(fourth, w), { start: 0, end: 1, opens: false, closes: true });
  assert.equal(bandRun(monthWeeks(2027, 4)[0], w), null);
});

test("the calendar opens on the window, then on today, then on the year's first moment", () => {
  const marked = ["2027-01-26", "2027-04-14", "2027-08-15"];
  assert.equal(startDay(marked, 2027, { date_from: "2027-04-01", date_to: "2027-05-01" }, "2026-11-19"), "2027-04-14");
  assert.equal(startDay(marked, 2027, null, "2027-03-01"), "2027-04-14");
  assert.equal(startDay(marked, 2027, null, "2027-09-01"), "2027-08-15");
  assert.equal(startDay(marked, 2027, null, "2026-11-19"), "2027-01-26");
  assert.equal(startDay([], 2027, null, "2026-11-19"), "2027-01-01");
  assert.equal(nearest("2027-04-01", marked), "2027-04-14");
  assert.equal(nearest("2027-04-01", []), null);
});

test("typical months read as a span or a list", () => {
  assert.equal(monthSpan([10, 11]), "Oct–Nov");
  assert.equal(monthSpan([3]), "Mar");
  assert.equal(monthSpan([4, 1]), "Jan, Apr");
});
