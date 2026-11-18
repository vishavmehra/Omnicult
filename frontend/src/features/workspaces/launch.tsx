"use client";

import { ShieldCheck } from "lucide-react";

import { ContextPanel } from "@/components/shell/workspace-shell";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useCapabilities } from "@/features/launch/api";
import { CompareTab } from "@/features/launch/compare";
import { InputsProvider } from "@/features/launch/inputs-store";
import { ReadinessTab } from "@/features/launch/readiness-board";

import { useCampaign } from "./campaign-context";
import { CampaignFacts, EarlierTools, FeatureScope, WorkspaceHeader } from "./parts";

function RoleNote() {
  const caps = useCapabilities();
  if (caps.loading) return null;
  const word = caps.role ?? "unknown";
  return (
    <section aria-label="Your role" className="space-y-1.5">
      <h3 className="flex items-center gap-1.5 text-[13px] font-semibold text-ink">
        <ShieldCheck aria-hidden className="size-4" />
        Your role: {word}
      </h3>
      <ul className="list-disc space-y-1 pl-5 text-[12.5px] text-ink-secondary">
        <li>Owners and editors compute verdicts.</li>
        <li>Owners, editors and reviewers record decisions.</li>
        <li>Viewers read scores, verdicts and decisions, and cannot approve.</li>
      </ul>
      {caps.reason && <p className="text-[12.5px] text-ink-body">{caps.reason}</p>}
    </section>
  );
}

/**
 * Launch Room: Compare and Score under fixed rules (mvp-2) and the Readiness Board by region (ready-1), with the verdict history
 * and human approvals. Scores and verdicts are computed by deterministic code from typed observations; a model never sets them.
 */
export function LaunchWorkspace() {
  const { campaign } = useCampaign();
  return (
    <InputsProvider campaignId={campaign.id}>
      <WorkspaceHeader workspace="launch">
        <CampaignFacts />
      </WorkspaceHeader>

      <Tabs defaultValue="readiness" className="gap-6">
        <TabsList aria-label="Launch Room" className="h-9 self-start">
          <TabsTrigger value="readiness" className="px-3">Readiness Board</TabsTrigger>
          <TabsTrigger value="compare" className="px-3">Compare and Score</TabsTrigger>
        </TabsList>
        <TabsContent value="readiness" keepMounted>
          <ReadinessTab />
        </TabsContent>
        <TabsContent value="compare" keepMounted>
          <CompareTab />
        </TabsContent>
      </Tabs>

      <ContextPanel title="How decisions are made">
        <div className="space-y-2 text-[13px] text-ink-body">
          <p>
            Scores and verdicts come from fixed rules over typed observations. A model may supply an observation; it never supplies a score or a verdict, and the same inputs
            under the same rule versions always give the same result.
          </p>
          <p className="text-ink-secondary">Go is a recommendation to seek human approval. Quick Read counts come from a simulated panel.</p>
        </div>
        <RoleNote />
        <EarlierTools
          tools={[
            { segment: "loop", label: "Loop", note: "Evaluate original against candidates with a recommendation" },
            { segment: "voice", label: "Voice", note: "Adaptations with change lists and revisions" },
          ]}
        />
        <FeatureScope workspace="launch" />
      </ContextPanel>
    </InputsProvider>
  );
}
