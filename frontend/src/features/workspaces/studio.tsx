"use client";

import { Eye, Film, Lock, Mic, Type } from "lucide-react";
import { useState } from "react";

import { ContextPanel } from "@/components/shell/workspace-shell";
import { EmptyState } from "@/components/states";
import type { CampaignContent } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

import { useCampaign } from "./campaign-context";
import { CreativeMat, FeatureScope, versionsOldestFirst } from "./parts";

const TEXT_FIELDS: { key: "headline" | "body" | "call_to_action"; label: string }[] = [
  { key: "headline", label: "Headline" },
  { key: "body", label: "Body" },
  { key: "call_to_action", label: "Call to action" },
];

function Track({ Icon, label, children }: { Icon: typeof Type; label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[7.5rem_minmax(0,1fr)] items-stretch border-t border-border first:border-t-0">
      <div className="flex items-center gap-2 border-r border-border px-3 py-2 text-[12.5px] font-medium text-ink-secondary">
        <Icon aria-hidden className="size-3.5" />
        {label}
      </div>
      <div className="min-w-0 px-2 py-2">{children}</div>
    </div>
  );
}

function TextTrack({ content }: { content: CampaignContent }) {
  const present = TEXT_FIELDS.filter((f) => content[f.key]);
  if (!present.length) return <p className="px-1 text-[12.5px] text-ink-muted">No text in this version.</p>;
  return (
    <ol className="flex gap-1.5 overflow-x-auto">
      {present.map((f) => (
        <li key={f.key} className="clay min-w-[9rem] flex-1 rounded-md border border-border px-2.5 py-1.5">
          <p className="type-meta">{f.label}</p>
          <p className="truncate text-[12.5px] text-ink">{content[f.key]}</p>
        </li>
      ))}
    </ol>
  );
}

/**
 * Creative Studio: the creative stays the hero. Status bar, preview mat, context panel (findings, evidence, risk, tweak
 * chips), timeline tracks, and the version bar. Versions and copy are real; analysis panels say what has not run yet.
 */
export function StudioWorkspace() {
  const { campaign, project } = useCampaign();
  const versions = versionsOldestFirst(campaign);
  const original = versions[0];
  const [selectedId, setSelectedId] = useState(campaign.current_version.id);
  const [compare, setCompare] = useState(false);
  const selected = versions.find((v) => v.id === selectedId) ?? campaign.current_version;
  const showCompare = compare && original && original.id !== selected.id;

  return (
    <>
      <h1 className="sr-only">Creative Studio</h1>
      <div className="flex min-h-[calc(100dvh-10rem)] flex-col gap-4">
        {/* Status bar: campaign, version, regions, editing state. */}
        <div className="type-ledger flex flex-wrap items-center gap-x-5 gap-y-2 rounded-card border border-border bg-surface px-4 py-2.5 text-[13px]">
          <span className="type-title text-[19px] text-ink">Creative Studio</span>
          <span className="text-ink-body">{campaign.name}</span>
          <span className="text-ink-muted">
            Version <span className="text-ink">v{selected.version_number}</span>
            {selected.id === campaign.current_version.id && " (current)"}
          </span>
          <span className="text-ink-muted">
            Regions: <span className="text-ink-body">{campaign.target_markets.map((m) => m.display_name).join(", ") || "none set"}</span>
          </span>
          <span className="ml-auto inline-flex items-center gap-1.5 font-medium text-ink-secondary">
            <Eye aria-hidden className="size-4" />
            Viewing
            {project.mode === "demo" && (
              <span className="inline-flex items-center gap-1 text-ink-muted">
                Â· <Lock aria-hidden className="size-3.5" /> demo content is locked
              </span>
            )}
          </span>
        </div>

        {/* Preview: the original stays visible; compare puts it beside the selected version. */}
        <section aria-label="Creative preview" className={cn("grid flex-1 gap-4", showCompare && "md:grid-cols-2")}>
          {showCompare && (
            <div className="space-y-2">
              <p className="type-meta">Original Â· v{original.version_number}</p>
              <CreativeMat content={original.content} className="h-[calc(100%-1.5rem)]" />
            </div>
          )}
          <div className="space-y-2">
            {showCompare && <p className="type-meta">Selected Â· v{selected.version_number}</p>}
            <CreativeMat content={selected.content} className={cn("min-h-[16rem]", showCompare && "h-[calc(100%-1.5rem)]")} />
          </div>
        </section>

        {/* Timeline tracks. Text is real; scenes and audio need a video or audio creative. */}
        <section aria-label="Timeline" className="overflow-hidden rounded-card border border-border bg-surface">
          <Track Icon={Film} label="Scenes">
            <p className="px-1 py-1 text-[12.5px] text-ink-muted">No scenes. This creative is text only; upload a video creative to see keyframes and scenes.</p>
          </Track>
          <Track Icon={Type} label="Text">
            <TextTrack content={selected.content} />
          </Track>
          <Track Icon={Mic} label="Audio">
            <p className="px-1 py-1 text-[12.5px] text-ink-muted">No audio track.</p>
          </Track>
        </section>

        {/* Version bar. */}
        <section aria-label="Versions" className="flex flex-wrap items-center gap-3 rounded-card border border-border bg-surface px-3 py-2.5">
          <div role="group" aria-label="Version" className="clay-well flex max-w-full gap-1 overflow-x-auto rounded-lg p-1">
            {versions.map((v) => {
              const on = v.id === selected.id;
              return (
                <button
                  key={v.id}
                  type="button"
                  aria-pressed={on}
                  onClick={() => setSelectedId(v.id)}
                  title={`Saved ${formatDateTime(v.created_at)}`}
                  className={cn(
                    "h-8 shrink-0 rounded-md px-3 font-mono text-[12.5px] transition-colors",
                    on ? "clay text-ink" : "text-ink-secondary hover:text-ink",
                  )}
                >
                  v{v.version_number}
                  {v.version_number === 1 && <span className="ml-1 font-sans text-[11px] text-ink-muted">original</span>}
                </button>
              );
            })}
          </div>
          <label className={cn("inline-flex items-center gap-2 text-[13px]", versions.length < 2 ? "text-ink-muted" : "text-ink-body")}>
            <input
              type="checkbox"
              checked={compare}
              disabled={versions.length < 2 || selected.id === original?.id}
              onChange={(e) => setCompare(e.target.checked)}
              className="size-4 accent-[var(--primary)]"
            />
            Compare with the original
          </label>
          <p className="type-meta ml-auto">
            {versions.length} {versions.length === 1 ? "version" : "versions"} Â· every saved edit creates a new version; the original is never overwritten
          </p>
        </section>
      </div>

      <ContextPanel title="Creative context">
        <EmptyState
          title="No analysis on this creative yet"
          description="Creative X-Ray decomposes the creative into scenes, text, claims and visual observations; regional findings, risk flags and tweak chips attach to those parts."
          needs={[
            { label: "A creative version", met: versions.length > 0 },
            { label: "Target regions in the brief", met: campaign.target_markets.length > 0 },
            { label: "Creative X-Ray run on this version", met: false },
          ]}
        />
        <section aria-label="Tweak chips" className="space-y-1.5">
          <h3 className="text-[13px] font-semibold text-ink">Tweak chips</h3>
          <p className="text-[12.5px] text-ink-muted">Suggested changes appear here with a reason, their evidence and their cost, for you to inspect before applying.</p>
        </section>
        <section aria-label="Locks" className="space-y-1.5">
          <h3 className="inline-flex items-center gap-1.5 text-[13px] font-semibold text-ink">
            <Lock aria-hidden className="size-3.5" />
            Locked elements
          </h3>
          {project.brand.protected_terms.length ? (
            <p className="text-[13px] text-ink-body">
              Protected terms from the Brand Kit stay verbatim: <span className="text-ink">{project.brand.protected_terms.join(", ")}</span>.
            </p>
          ) : (
            <p className="text-[12.5px] text-ink-muted">No protected terms in the Brand Kit.</p>
          )}
        </section>
        <FeatureScope workspace="studio" />
      </ContextPanel>
    </>
  );
}
