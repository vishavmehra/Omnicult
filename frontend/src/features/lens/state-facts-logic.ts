/**
 * State facts display logic: pure functions with no React, so each rule can be tested on its own (state-facts-logic.test.mjs,
 * run with `node --test`). Nothing here invents a number: it formats, scales and compares what the API returned.
 */
/** whole: a whole number (per 1,000, per square kilometre, kilowatt-hours, a 0 to 100 score); decimal: a plain number with one decimal. */
export type FactUnit = "percent" | "per100" | "inr" | "million" | "whole" | "decimal";

const rupees = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 });
const oneDecimal = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const upToTwo = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 });
const wholeNumber = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });

/** The exact figure as the source gives it: one decimal for a percentage or a rate, whole rupees for money, whole numbers with Indian digit grouping, millions as published. */
export function formatFact(unit: FactUnit, value: number): string {
  if (unit === "million") return `${(value >= 10 ? oneDecimal : upToTwo).format(value)} million`;
  if (unit === "whole") return wholeNumber.format(value);
  return unit === "inr" ? rupees.format(value) : unit === "percent" ? `${oneDecimal.format(value)}%` : oneDecimal.format(value);
}

/** The top of a bar for these values: 100 for a percentage, a little above the largest value otherwise. */
export function barScale(unit: FactUnit, ...values: (number | null | undefined)[]): number {
  if (unit === "percent") return 100;
  const top = Math.max(0, ...values.filter((v): v is number => typeof v === "number"));
  return top > 0 ? top * 1.12 : 1;
}

/** Where a value sits on a bar of the given scale, as a percentage clamped to 0..100. */
export function barPosition(value: number, scale: number): number {
  return Math.max(0, Math.min(100, (value / scale) * 100));
}

export type VersusIndia = { direction: "above" | "below" | "level"; text: string };

/** How a state compares with the all-India figure, in the figure's own unit. Null when the dataset has no all-India row. */
export function versusIndia(unit: FactUnit, value: number, national: number | null | undefined): VersusIndia | null {
  if (national === null || national === undefined || unit === "million") return null; // a count beside the country's total says nothing
  const step = unit === "whole" ? 1 : 10; // a whole-number figure is compared in whole units, anything else to a tenth
  const gap = Math.round((value - national) * step) / step;
  if (gap === 0) return { direction: "level", text: "Level with India" };
  const size = unit === "inr" ? rupees.format(Math.abs(gap)) : unit === "whole" ? wholeNumber.format(Math.abs(gap)) : `${oneDecimal.format(Math.abs(gap))}${unit === "percent" ? " pts" : ""}`;
  return { direction: gap > 0 ? "above" : "below", text: `${size} ${gap > 0 ? "above" : "below"} India` };
}

/** How a fact is drawn: a ring for a share with one period, a trend for a series, bars for parts, a bar otherwise. */
export function factShape(fact: { unit: FactUnit; value: number | null; series: { length: number }; parts: { length: number } }): "parts" | "trend" | "ring" | "bar" {
  if (fact.parts.length > 0 && fact.value === null) return "parts";
  if (fact.series.length >= 2) return "trend";
  return fact.unit === "percent" ? "ring" : "bar";
}
