"use client";

import { PlugZap } from "lucide-react";

import { ContextPanel } from "@/components/shell/workspace-shell";
import { EmptyState } from "@/components/states";

import { useCampaign } from "./campaign-context";
import { CampaignFacts, FeatureScope, SectionTitle, WorkspaceHeader } from "./parts";

const FRESHNESS = [
  { label: "Live", meaning: "Pulled from a connected account within its normal reporting delay." },
  { label: "Delayed", meaning: "The platform has not reported recently; the last good value is shown with its time." },
  { label: "Provisional", meaning: "Reported, but the platform may still restate it (for example, attribution windows)." },
  { label: "Sample", meaning: "Demonstration data. Never presented as a connected account." },
];

const METRICS = [
  { group: "Delivery", metric: "Impressions and reach", unit: "count" },
  { group: "Cost", metric: "Spend and cost per result", unit: "INR" },
  { group: "Response", metric: "Click-through rate", unit: "%" },
  { group: "Video", metric: "View-through rate", unit: "%" },
  { group: "Outcome", metric: "Conversions against the brief's success metric", unit: "count" },
];

/**
 * Live Pulse: the analytics frame (metric definitions and freshness rules) with an honest "nothing connected" state.
 * No chart is drawn without data; no control is shown that would filter nothing.
 */
export function PulseWorkspace() {
  const { campaign } = useCampaign();
  return (
    <>
      <WorkspaceHeader workspace="pulse">
        <CampaignFacts />
      </WorkspaceHeader>
      <div className="space-y-6">
        <EmptyState
          title="No ad account is connected"
          description="Live Pulse reads delivery, cost, response, video and outcome metrics per region and version from connected platforms, and compares them with what Audience Lab predicted. Nothing on this page is sample data."
          needs={[
            { label: "Target regions in the brief", met: campaign.target_markets.length > 0 },
            { label: "A launched version", met: false },
            { label: "A connected ad platform account", met: false },
          ]}
          action={
            <p className="inline-flex items-center gap-1.5 text-[12.5px] text-ink-muted">
              <PlugZap aria-hidden className="size-3.5" />
              Connecting ad accounts is on the roadmap. The Regional Dashboard will first run on a clearly labelled sample dataset.
            </p>
          }
        />
        <section aria-labelledby="metrics" className="space-y-2.5">
          <SectionTitle id="metrics" meta="Each chart will state metric, unit, range, region, source and freshness">
            Metric definitions
          </SectionTitle>
          <div className="overflow-x-auto rounded-card border border-border bg-surface">
            <table className="type-ledger w-full min-w-[30rem] text-left text-[13px]">
              <thead className="bg-surface-muted text-[11.5px] text-ink-muted">
                <tr>
                  <th scope="col" className="px-3 py-2 font-medium">Group</th>
                  <th scope="col" className="px-3 py-2 font-medium">Metric</th>
                  <th scope="col" className="px-3 py-2 font-medium">Unit</th>
                  <th scope="col" className="px-3 py-2 font-medium">Latest value</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {METRICS.map((m) => (
                  <tr key={m.group}>
                    <th scope="row" className="px-3 py-2.5 font-medium text-ink">{m.group}</th>
                    <td className="px-3 py-2.5 text-ink-body">{m.metric}</td>
                    <td className="px-3 py-2.5 font-mono text-[12px] text-ink-secondary">{m.unit}</td>
                    <td className="px-3 py-2.5 text-ink-muted">No source connected</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>
      <ContextPanel title="Data freshness">
        <dl className="ledger-rules rounded-card border border-border">
          {FRESHNESS.map((f) => (
            <div key={f.label} className="space-y-0.5 px-3 py-2.5">
              <dt className="text-[13px] font-semibold text-ink">{f.label}</dt>
              <dd className="text-[12.5px] text-ink-secondary">{f.meaning}</dd>
            </div>
          ))}
        </dl>
        <FeatureScope workspace="pulse" />
      </ContextPanel>
    </>
  );
}
