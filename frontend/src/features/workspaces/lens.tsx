"use client";

import { MapPin } from "lucide-react";
import { useState } from "react";

import { EvidenceMeter } from "@/components/evidence/evidence-meter";
import { ContextPanel } from "@/components/shell/workspace-shell";
import { EmptyState } from "@/components/states";
import { cn } from "@/lib/utils";

import { useCampaign } from "./campaign-context";
import { CampaignFacts, EarlierTools, FeatureScope, SectionTitle, WorkspaceHeader } from "./parts";

const PROFILE_SECTIONS = ["Languages and scripts", "Language mix", "Festivals and moments", "Food", "Colours and symbols", "Humour", "Family roles", "Local customs", "Regional sensitivities", "Public trends"];

/** Market Lens: a region rail, the selected region's profile, and its Evidence Meter. Nothing is shown that was not sourced. */
export function LensWorkspace() {
  const { campaign } = useCampaign();
  const regions = campaign.target_markets;
  const [selected, setSelected] = useState(regions[0]?.country_code ?? null);
  const region = regions.find((r) => r.country_code === selected) ?? null;

  return (
    <>
      <WorkspaceHeader workspace="lens">
        <CampaignFacts />
      </WorkspaceHeader>

      <div className="grid gap-6 lg:grid-cols-[15rem_minmax(0,1fr)]">
        <nav aria-label="Target regions" className="space-y-2">
          <SectionTitle meta={`${regions.length}`}>Regions</SectionTitle>
          {regions.length === 0 ? (
            <p className="text-[13px] text-ink-muted">No target regions in the brief. Add them in Campaign Desk.</p>
          ) : (
            <ul className="flex gap-1.5 overflow-x-auto pb-1 lg:flex-col lg:overflow-visible">
              {regions.map((r) => {
                const on = r.country_code === selected;
                return (
                  <li key={r.country_code} className="shrink-0">
                    <button
                      type="button"
                      onClick={() => setSelected(r.country_code)}
                      aria-pressed={on}
                      className={cn(
                        "flex h-10 w-full items-center gap-2 rounded-lg border px-3 text-left text-[14px]",
                        on ? "clay border-border font-medium text-ink" : "border-transparent text-ink-secondary hover:bg-surface-muted hover:text-ink",
                      )}
                    >
                      <MapPin aria-hidden className={cn("size-4", on ? "text-pop" : "text-ink-muted")} />
                      <span className="flex-1 truncate">{r.display_name}</span>
                      <span className="font-mono text-[11px] text-ink-muted">{r.country_code}</span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
          <p className="text-[12px] leading-relaxed text-ink-muted">
            The current data model stores countries. Indian states (ISO 3166-2:IN, such as IN-TN) arrive with the culture service.
          </p>
        </nav>

        <div className="min-w-0 space-y-6">
          <section aria-labelledby="profile" className="space-y-3">
            <SectionTitle id="profile" meta={region ? region.country_code : undefined}>
              {region ? `${region.display_name}: profile` : "Region profile"}
            </SectionTitle>
            <EmptyState
              title={region ? `No sourced claims for ${region.display_name} yet` : "Choose a region"}
              description={
                <>
                  A profile is assembled from claims, each with its source, date, kind, scope and confidence. Nothing is filled in to make the page look
                  complete: a section with no claims stays empty and says so.
                </>
              }
              needs={[
                { label: "A target region in the brief", met: regions.length > 0 },
                { label: "Culture sources connected (Wikidata, Wikipedia, Census 2011, public holidays)", met: false },
                { label: "Claims retrieved and confidence computed for this region", met: false },
              ]}
            />
            <ul aria-label="Profile sections" className="grid grid-cols-2 gap-px overflow-hidden rounded-card border border-border bg-border sm:grid-cols-3 xl:grid-cols-5">
              {PROFILE_SECTIONS.map((s) => (
                <li key={s} className="bg-surface px-3 py-2.5">
                  <p className="text-[12.5px] font-medium text-ink-body">{s}</p>
                  <p className="type-meta mt-0.5">0 claims</p>
                </li>
              ))}
            </ul>
          </section>

          <section aria-label="Evidence meter" className="rounded-card border border-border bg-surface px-4 py-4">
            <EvidenceMeter counts={{}} independentGroups={0} scopeLabel={region?.display_name ?? "this campaign"} />
          </section>
        </div>
      </div>

      <ContextPanel title="Region context">
        <EarlierTools
          tools={[
            { segment: "atlas", label: "Atlas", note: "Cultural discovery and market brief" },
            { segment: "cultural-dna", label: "Cultural DNA", note: "Versioned cultural profile of a market" },
            { segment: "market-expansion", label: "Market Expansion", note: "Compare markets on shared evidence" },
            { segment: "trend-watch", label: "Trend Watch", note: "Snapshots compared over time" },
          ]}
        />
        <FeatureScope workspace="lens" />
      </ContextPanel>
    </>
  );
}
