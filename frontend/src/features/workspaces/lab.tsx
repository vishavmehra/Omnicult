"use client";

import { CircleAlert, LoaderCircle, TriangleAlert } from "lucide-react";
import { useCallback } from "react";

import { SyntheticLabel } from "@/components/evidence/badges";
import { ContextPanel } from "@/components/shell/workspace-shell";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useRuns } from "@/features/lab/api";
import { AskTab } from "@/features/lab/ask-panel";
import { QuickReadTab } from "@/features/lab/quick-read";
import { RiskCheckTab } from "@/features/lab/risk-check";
import { StudyTab } from "@/features/lab/study";
import { isActive } from "@/features/lab/types";
import { LAB_TABS, useLabLocation, type LabTab } from "@/features/lab/use-lab-location";

import { useCampaign } from "./campaign-context";
import { CampaignFacts, CreativeMat, FeatureScope, SectionTitle, WorkspaceHeader } from "./parts";

const TAB_LABEL: Record<LabTab, string> = { quick: "Quick Read", study: "Audience Study", ask: "Ask the Panel", risk: "Risk Check" };

/**
 * One line that answers "what is going on in this lab": how many runs are moving, finished with gaps, or failed, across
 * the three kinds. Counts come from the same lists the tabs show, so there is nothing to disagree.
 */
function LabActivity() {
  const { campaign } = useCampaign();
  const lists = [useRuns(campaign.id, "quick_read"), useRuns(campaign.id, "audience_study"), useRuns(campaign.id, "risk_check")];
  const all = lists.flatMap((l) => l.data ?? []);
  if (all.length === 0) return null;
  const running = all.filter((r) => isActive(r.status)).length;
  const gaps = all.filter((r) => r.status === "partial").length;
  const failed = all.filter((r) => r.status === "failed").length;
  return (
    <p className="type-ledger flex flex-wrap items-center gap-x-4 gap-y-1 pt-1 text-[12.5px] text-ink-muted" aria-live="polite">
      <span>{all.length} {all.length === 1 ? "run" : "runs"} in this campaign</span>
      {running > 0 && (
        <span className="inline-flex items-center gap-1 text-info">
          <LoaderCircle aria-hidden className="size-3.5 animate-spin motion-reduce:animate-none" />
          {running} running
        </span>
      )}
      {gaps > 0 && (
        <span className="inline-flex items-center gap-1 text-warning">
          <TriangleAlert aria-hidden className="size-3.5" />
          {gaps} completed with gaps
        </span>
      )}
      {failed > 0 && (
        <span className="inline-flex items-center gap-1 text-danger">
          <CircleAlert aria-hidden className="size-3.5" />
          {failed} failed
        </span>
      )}
    </p>
  );
}

/**
 * Audience Lab: Quick Read, Audience Study, Ask the Panel and Risk Check on one campaign. Every result is labelled
 * synthetic, the panel size is never presented as people surveyed, and each tab keeps its place in the URL.
 */
export function LabWorkspace() {
  const { campaign, project } = useCampaign();
  const loc = useLabLocation();
  const onTab = useCallback((v: unknown) => loc.setTab(v as LabTab), [loc]);

  return (
    <>
      <WorkspaceHeader workspace="lab">
        <CampaignFacts />
        <div className="flex flex-wrap items-center gap-2 pt-2">
          <SyntheticLabel>
            {project.mode === "demo"
              ? "Synthetic audience on demo fixtures. Simulated reactions, not consumer research."
              : "Synthetic audience. Simulated reactions, not consumer research."}
          </SyntheticLabel>
        </div>
        <LabActivity />
      </WorkspaceHeader>

      <Tabs value={loc.tab} onValueChange={onTab} className="gap-5">
        <TabsList variant="line" aria-label="Audience Lab" className="h-auto w-full justify-start gap-1 overflow-x-auto border-b border-border pb-1">
          {LAB_TABS.map((t) => (
            <TabsTrigger key={t} value={t} className="h-9 flex-none px-3 text-[14px] after:bottom-[-5px]">
              {TAB_LABEL[t]}
            </TabsTrigger>
          ))}
        </TabsList>
        <TabsContent value="quick">
          <QuickReadTab loc={loc} />
        </TabsContent>
        <TabsContent value="study">
          <StudyTab loc={loc} />
        </TabsContent>
        <TabsContent value="ask">
          <AskTab loc={loc} />
        </TabsContent>
        <TabsContent value="risk">
          <RiskCheckTab loc={loc} />
        </TabsContent>
      </Tabs>

      <ContextPanel title="Lab context">
        <section aria-labelledby="under-test" className="space-y-2.5">
          <SectionTitle id="under-test" meta={`v${campaign.current_version.version_number}`}>
            Creative under test
          </SectionTitle>
          <CreativeMat content={campaign.current_version.content} size="sm" />
          <p className="text-[12.5px] text-ink-muted">Quick Read and Audience Study react to this copy unless you pick another version in the form.</p>
        </section>
        <section aria-labelledby="lab-limits" className="space-y-2">
          <h3 id="lab-limits" className="text-[13px] font-semibold text-ink">
            What a synthetic panel can and cannot show
          </h3>
          <ul className="list-disc space-y-1 pl-5 text-[13px] leading-relaxed text-ink-body marker:text-ink-muted">
            <li>It rehearses reactions and questions for real research. It does not measure real people or predict sales.</li>
            <li>The panel size is a setting, not a count of people surveyed. Twelve answers from one model are not twelve observations.</li>
            <li>Agreement between participants is not confirmation: they share one model&apos;s biases.</li>
            <li>A statement is claim-supported only when it cites an observed or calculated claim. Everything else is interpretation.</li>
            <li>Risk Check findings are for human review. They are never legal advice, and no finding is not clearance.</li>
          </ul>
        </section>
        <FeatureScope workspace="lab" />
      </ContextPanel>
    </>
  );
}
