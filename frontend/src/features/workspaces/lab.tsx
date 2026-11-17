"use client";

import { SyntheticLabel } from "@/components/evidence/badges";
import { ContextPanel } from "@/components/shell/workspace-shell";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";

import { useCampaign } from "./campaign-context";
import { CampaignFacts, CreativeMat, EarlierTools, FeatureScope, SectionTitle, useCampaignRuns, WorkspaceHeader } from "./parts";
import { RunLedger } from "./run-ledger";

const COMPOSITION = ["State", "Language", "City tier", "Age band"];

/**
 * Audience Lab: the creative under test stays in view, the study configuration beside it, and every result is labelled
 * synthetic. Runs listed here are this campaign's real rehearsal, panel and risk runs.
 */
export function LabWorkspace() {
  const { campaign } = useCampaign();
  const runs = useCampaignRuns(["campaign_rehearsal", "population_study", "social_simulation", "risk_scan"]);
  const rehearsals = runs.data?.filter((r) => r.run_type !== "risk_scan") ?? [];
  const risk = runs.data?.filter((r) => r.run_type === "risk_scan") ?? [];

  return (
    <>
      <WorkspaceHeader workspace="lab">
        <CampaignFacts />
        <div className="pt-2">
          <SyntheticLabel>Synthetic audience: simulated opinions, not consumer research or proof of purchase intent</SyntheticLabel>
        </div>
      </WorkspaceHeader>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]">
        <section aria-labelledby="under-test" className="space-y-3">
          <SectionTitle id="under-test" meta={`v${campaign.current_version.version_number}`}>
            Creative under test
          </SectionTitle>
          <CreativeMat content={campaign.current_version.content} size="sm" />
          <div className="rounded-card border border-border bg-surface">
            <p className="border-b border-border px-3 py-2 text-[13px] font-semibold text-ink">Participant composition</p>
            <dl className="ledger-rules type-ledger text-[13px]">
              {COMPOSITION.map((d) => (
                <div key={d} className="flex justify-between gap-3 px-3 py-2">
                  <dt className="text-ink-secondary">{d}</dt>
                  <dd className="text-ink-muted">Set when a study is configured</dd>
                </div>
              ))}
            </dl>
          </div>
        </section>

        <div className="min-w-0 space-y-6">
          {runs.error ? (
            <ErrorState error={runs.error} onRetry={() => void runs.refetch()} />
          ) : runs.isPending ? (
            <LoadingState label="Loading this campaign's studies…" />
          ) : (
            <>
              <section aria-labelledby="quick-read" className="space-y-2.5">
                <SectionTitle id="quick-read" meta="Rehearsals, panels and buzz simulations">
                  Quick Read and studies
                </SectionTitle>
                {rehearsals.length === 0 ? (
                  <EmptyState
                    title="No audience runs for this campaign"
                    description="A Quick Read asks a synthetic panel how the creative lands: first reactions, message understanding, confusion and regional concerns. Each answer keeps its participant profile, model and prompt version."
                    needs={[
                      { label: `A creative version (v${campaign.current_version.version_number} is ready)`, met: true },
                      { label: "At least one target region", met: campaign.target_markets.length > 0 },
                      { label: "A study configured from the earlier Audience page (Omnicult Quick Read arrives with the model gateway)", met: false },
                    ]}
                  />
                ) : (
                  <RunLedger runs={rehearsals} empty="" />
                )}
              </section>
              <section aria-labelledby="risk-check" className="space-y-2.5">
                <SectionTitle id="risk-check" meta="Findings attach to a part of the creative">
                  Risk Check
                </SectionTitle>
                <RunLedger runs={risk} empty="No risk scans for this campaign yet." />
              </section>
            </>
          )}
        </div>
      </div>

      <ContextPanel title="Study context">
        <p className="text-[13px] leading-relaxed text-ink-body">
          Repeated answers from one model are not independent confirmation. Synthetic results can never raise a claim above Moderate confidence on their
          own.
        </p>
        <EarlierTools
          tools={[
            { segment: "audience", label: "Audience", note: "Population studies, interviews and quick rehearsals" },
            { segment: "risk-radar", label: "Risk Radar", note: "Risk scan with accept, dismiss and apply" },
            { segment: "arena", label: "Campaign Arena", note: "Variants against one synthetic audience" },
          ]}
        />
        <FeatureScope workspace="lab" />
      </ContextPanel>
    </>
  );
}
