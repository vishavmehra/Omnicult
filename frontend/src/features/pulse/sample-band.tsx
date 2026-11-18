"use client";

import { formatDateTime } from "@/lib/format";
import type { components } from "@/lib/api/schema";

import { formatDay, formatSpan, SAMPLE_LABEL } from "./logic";
import { SampleTag } from "./ui";

type Status = components["schemas"]["DatasetStatus"];

/**
 * The permanent label. It sticks under the shell header so "Sample data, not from a connected account" is on screen at every
 * scroll position, not in a footnote. The text is the API's own `label` when a response carries it.
 */
export function SampleBand({ status }: { status: Status | undefined }) {
  const label = status?.label ?? SAMPLE_LABEL;
  const loaded = Boolean(status?.loaded && status.date_from && status.date_to);
  const provisional =
    loaded && status?.provisional_from && status.date_to
      ? `Provisional from ${formatDay(status.provisional_from)}, so the last days are still being reported`
      : null;
  return (
    <div
      role="note"
      aria-label="Data source"
      className="sticky top-[4.5rem] z-10 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-card border border-warning/40 bg-warning-soft px-3.5 py-2 shadow-raised"
    >
      <SampleTag />
      <p className="text-[13.5px] font-semibold text-ink">{label}</p>
      <p className="type-ledger flex flex-wrap gap-x-3 gap-y-0.5 text-[12.5px] text-ink-secondary sm:ml-auto">
        <span>Not real time</span>
        {loaded && status?.date_from && status.date_to ? <span>{formatSpan(status.date_from, status.date_to)}</span> : <span>Not loaded yet</span>}
        {provisional && <span className="hidden lg:inline">{provisional}</span>}
        {loaded && status?.last_updated_at && <span>Generated {formatDateTime(status.last_updated_at)}</span>}
      </p>
    </div>
  );
}
