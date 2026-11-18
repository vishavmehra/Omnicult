"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";

import { ErrorState, LoadingState } from "@/components/states";
import { useCampaign } from "@/features/workspaces/campaign-context";
import { cn } from "@/lib/utils";

import { useRemakeCapabilities, useRemakes, useVersionList } from "./api";
import { SoundPanel } from "./sound-panel";
import { VisualPanel } from "./visual-panel";

const VIEWS = [
  { key: "visuals", label: "Visuals", note: "Regional scene, locked regions kept, text drawn in code" },
  { key: "sound", label: "Sound", note: "Voice-over of the transcreated lines" },
] as const;

/** Remake: a regional key visual (Visuals) and a spoken voice-over (Sound) for one version of the campaign. */
export function RemakeWorkspace() {
  const { campaign, project } = useCampaign();
  const router = useRouter();
  const params = useSearchParams();
  const view = params.get("view") === "sound" ? "sound" : "visuals";
  const caps = useRemakeCapabilities(campaign.id);
  const versions = useVersionList(campaign.id);
  const remakes = useRemakes(campaign.id);
  const demo = project.mode === "demo";
  const error = caps.error ?? versions.error ?? remakes.error;

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3 border-b border-border pb-4">
        <div className="min-w-0 space-y-1">
          <Link href={`/app/c/${campaign.id}/studio`} className="inline-flex items-center gap-1 text-[12.5px] text-ink-secondary hover:text-ink">
            <ArrowLeft aria-hidden className="size-3.5" />
            Creative Studio
          </Link>
          <h1 className="type-title text-[30px] text-ink sm:text-[34px]">Remake</h1>
          <p className="max-w-[68ch] text-[14.5px] text-ink-secondary">
            {VIEWS.find((v) => v.key === view)?.note}. The result is a new version; the version you start from is not changed.
          </p>
        </div>
        <div role="tablist" aria-label="Remake type" className="inline-flex rounded-lg border border-border bg-surface p-0.5">
          {VIEWS.map((v) => (
            <button
              key={v.key}
              type="button"
              role="tab"
              id={`remake-tab-${v.key}`}
              aria-selected={view === v.key}
              aria-controls="remake-panel"
              onClick={() => router.replace(`/app/c/${campaign.id}/studio/remake?view=${v.key}`, { scroll: false })}
              className={cn(
                "h-8 rounded-md px-3.5 text-[13.5px] font-medium outline-none focus-visible:ring-3 focus-visible:ring-ring/30",
                view === v.key ? "bg-surface-raised text-ink shadow-card" : "text-ink-secondary hover:text-ink",
              )}
            >
              {v.label}
            </button>
          ))}
        </div>
      </header>

      <div id="remake-panel" role="tabpanel" aria-labelledby={`remake-tab-${view}`}>
        {error ? (
          <ErrorState error={error} onRetry={() => { void caps.refetch(); void versions.refetch(); void remakes.refetch(); }} />
        ) : !caps.data || !versions.data || !remakes.data ? (
          <LoadingState label="Loading Remake…" />
        ) : view === "sound" ? (
          <SoundPanel campaignId={campaign.id} demo={demo} caps={caps.data} versions={versions.data} outputs={remakes.data} />
        ) : (
          <VisualPanel campaignId={campaign.id} projectId={project.id} demo={demo} caps={caps.data} versions={versions.data} outputs={remakes.data} />
        )}
      </div>
    </div>
  );
}
