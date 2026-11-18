"use client";

import { CircleOff, PlugZap } from "lucide-react";

import { Tag } from "@/components/evidence/badges";
import { ErrorState, LoadingState } from "@/components/states";

import { useConnections, useMetricCatalogue } from "./api";
import { platformLabel } from "./logic";
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

/**
 * Platform connections. They say plainly that they are not available: no connect button exists because none can work in
 * this build. Predicted vs Actual lives in its own tab (features/pulse-t3).
 */
export function SourcesAndCalibration({ campaignId }: { campaignId: string }) {
  const connections = useConnections(campaignId);
  return (
    <Section id="sources" title="Platform connections" meta={<span>Connecting accounts is roadmap in this build</span>}>
      <div className="max-w-3xl">
        <section aria-labelledby="connections-title" className="rounded-card border border-border bg-surface">
          <div className="border-b border-border px-4 py-3">
            <h3 id="connections-title" className="text-[14px] font-semibold text-ink">
              Platform connections
            </h3>
            <p className="mt-0.5 text-[12.5px] text-ink-secondary">Connecting ad accounts is not available in this build.</p>
          </div>
          {connections.error ? (
            <div className="p-3">
              <ErrorState error={connections.error} onRetry={() => void connections.refetch()} />
            </div>
          ) : !connections.data ? (
            <LoadingState label="Reading connection status…" className="px-4" />
          ) : (
            <ul className="ledger-rules">
              {connections.data.items.map((c) => (
                <li key={c.platform} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5">
                  <span className="min-w-24 text-[13.5px] font-medium text-ink">{c.label || platformLabel(c.platform)}</span>
                  {c.status === "not_connected" ? (
                    <Tag className="border-border bg-surface-muted text-ink-secondary">
                      <CircleOff aria-hidden />
                      Not connected
                    </Tag>
                  ) : (
                    <Tag className="border-border bg-surface-muted text-ink">{c.status.replace("_", " ")}</Tag>
                  )}
                  <span className="type-meta sm:ml-auto">{c.last_sync_at ? `Last sync ${c.last_sync_at}` : "No sync yet"}</span>
                </li>
              ))}
            </ul>
          )}
          <p className="flex items-start gap-1.5 border-t border-border px-4 py-2.5 text-[12.5px] text-ink-secondary">
            <PlugZap aria-hidden className="mt-0.5 size-3.5 shrink-0" />
            Connecting accounts is on the roadmap, so there is nothing to connect or authorise here.
          </p>
        </section>

      </div>
    </Section>
  );
}

/** Metric definitions: collapsed once the dashboard is up, because the ledger already carries its labels; open before it. */
export function MetricDefinitions({ campaignId, open }: { campaignId: string; open: boolean }) {
  const catalogue = useMetricCatalogue(campaignId);
  return (
    <Section id="definitions" title="Metric definitions" meta={<span>Calculated in code from stored base metrics</span>}>
      <details open={open} className="group rounded-card border border-border bg-surface">
        <summary className="cursor-pointer px-4 py-2.5 text-[13px] text-ink-secondary hover:text-ink">
          {catalogue.data ? `${catalogue.data.items.length} metrics, ${catalogue.data.items.filter((m) => m.in_sample).length} with values in the sample` : "Metric definitions"}
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
                  <caption className="sr-only">Every metric Live Pulse defines: group, unit, formula, source platforms in the plan, and whether the sample has values for it.</caption>
                  <thead className="sticky top-0 bg-surface-muted text-ink-secondary">
                    <tr>
                      <th scope="col" className="px-3 py-2 font-medium">Metric</th>
                      <th scope="col" className="px-3 py-2 font-medium">Group</th>
                      <th scope="col" className="px-3 py-2 font-medium">Unit</th>
                      <th scope="col" className="px-3 py-2 font-medium">Formula or meaning</th>
                      <th scope="col" className="px-3 py-2 font-medium">Planned sources</th>
                      <th scope="col" className="px-3 py-2 font-medium">In the sample</th>
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
                        <td className="px-3 py-2 text-ink-secondary">{m.platforms.map((p) => (p === "google_trends" ? "Google Trends" : platformLabel(p))).join(", ")}</td>
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
