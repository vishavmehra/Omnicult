"use client";

import { ErrorState, LoadingState } from "@/components/states";

import { useMetricCatalogue } from "./api";
import { Section } from "./ui";

const GROUP_LABEL: Record<string, string> = {
  delivery: "Delivery",
  cost: "Cost",
  response: "Response",
  video: "Video",
  outcome: "Outcome",
  site: "Site",
  conversation: "Conversation",
  brand: "Brand",
  creative_health: "Creative health",
};
const UNIT_LABEL: Record<string, string> = { count: "count", inr: "INR", ratio: "ratio (%)", multiple: "multiple (×)" };

/** Metric definitions: collapsed once the dashboard is up, because the ledger already carries its labels; open before it. */
export function MetricDefinitions({ campaignId, open }: { campaignId: string; open: boolean }) {
  const catalogue = useMetricCatalogue(campaignId);
  return (
    <Section id="definitions" title="Metric definitions" meta={<span>Calculated in code from stored base metrics</span>}>
      <details open={open} className="group rounded-card border border-border bg-surface">
        <summary className="cursor-pointer px-4 py-2.5 text-[13px] text-ink-secondary hover:text-ink">
          {catalogue.data ? `${catalogue.data.items.length} metrics, ${catalogue.data.items.filter((m) => m.in_sample).length} with values` : "Metric definitions"}
        </summary>
        <div className="border-t border-border">
          {catalogue.error ? (
            <div className="p-3">
              <ErrorState error={catalogue.error} onRetry={() => void catalogue.refetch()} />
            </div>
          ) : !catalogue.data ? (
            <LoadingState label="Reading metric definitions…" className="px-4" />
          ) : (
            <>
              <div className="max-h-[28rem] overflow-auto">
                <table className="type-ledger w-full min-w-[40rem] text-left text-[12.5px]">
                  <caption className="sr-only">Every metric Live Pulse defines: group, unit, formula, and whether there are values for it.</caption>
                  <thead className="sticky top-0 bg-surface-muted text-ink-secondary">
                    <tr>
                      <th scope="col" className="px-3 py-2 font-medium">Metric</th>
                      <th scope="col" className="px-3 py-2 font-medium">Group</th>
                      <th scope="col" className="px-3 py-2 font-medium">Unit</th>
                      <th scope="col" className="px-3 py-2 font-medium">Formula or meaning</th>
                      <th scope="col" className="px-3 py-2 font-medium">Has values</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {catalogue.data.items.map((m) => (
                      <tr key={m.name}>
                        <th scope="row" className="px-3 py-2 font-medium text-ink">{m.label}</th>
                        <td className="px-3 py-2 text-ink-body">{GROUP_LABEL[m.group] ?? m.group}</td>
                        <td className="px-3 py-2 text-ink-body">{UNIT_LABEL[m.unit] ?? m.unit}</td>
                        <td className="px-3 py-2 text-ink-body">
                          {m.formula ? <span className="font-mono text-[11.5px]">{m.formula}</span> : m.description}
                        </td>
                        <td className="px-3 py-2 text-ink-body">{m.in_sample ? "Yes" : <span className="text-ink-muted">No values</span>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <ul className="list-disc space-y-1 border-t border-border px-4 py-3 pl-9 text-[12.5px] text-ink-secondary marker:text-ink-muted">
                {catalogue.data.notes.map((n) => (
                  <li key={n}>{n}</li>
                ))}
              </ul>
            </>
          )}
        </div>
      </details>
    </Section>
  );
}
