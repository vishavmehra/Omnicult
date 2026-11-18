"use client";

import { useQueries } from "@tanstack/react-query";

import { ErrorState, LoadingState } from "@/components/states";
import { useCampaign } from "@/features/workspaces/campaign-context";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { humanize } from "@/lib/format";
import { cn } from "@/lib/utils";

import { launchKeys, useVersionOptions } from "./api";
import { SERIES_VARS, VersionChip } from "./score-parts";

const TEXT_KINDS = new Set(["headline", "body", "cta", "tagline", "voiceover", "caption"]);
type Line = { id: string; kind: string; text: string; lang: string | null };

/** The words of each compared version, side by side, so a score is read against the creative it describes. */
export function VersionCopy({ versionIds, labels }: { versionIds: string[]; labels: string[] }) {
  const { campaign } = useCampaign();
  const { options } = useVersionOptions();
  const nodes = useQueries({
    queries: versionIds.map((id) => ({
      queryKey: [...launchKeys.versions(campaign.id), id],
      enabled: options.find((o) => o.id === id)?.source === "studio",
      queryFn: () => unwrap(api.GET("/api/v1/campaigns/{campaign_id}/versions/{version_id}", { params: { path: { campaign_id: campaign.id, version_id: id } } })),
    })),
  });

  return (
    <div className={cn("grid gap-4 md:grid-cols-2 xl:grid-cols-4", SERIES_VARS)}>
      {versionIds.map((id, i) => {
        const source = options.find((o) => o.id === id)?.source;
        const q = nodes[i];
        let lines: Line[] = [];
        if (source === "studio" && q.data) {
          lines = q.data.elements
            .filter((e) => TEXT_KINDS.has(e.kind) && typeof e.value === "string" && e.value.trim())
            .map((e) => ({ id: e.id, kind: e.kind, text: String(e.value), lang: e.language ?? null }));
        } else if (source === "content") {
          const c = campaign.versions.find((v) => v.id === id)?.content;
          lines = [
            ["headline", c?.headline],
            ["body", c?.body],
            ["cta", c?.call_to_action],
          ].flatMap(([kind, text]) => (text ? [{ id: kind as string, kind: kind as string, text: text as string, lang: null }] : []));
        }
        return (
          <section key={id} aria-label={labels[i]} className="min-w-0 rounded-card border border-border">
            <p className="flex items-center gap-2 border-b border-border px-4 py-2.5 text-[13px] font-semibold text-ink">
              <VersionChip index={i} />
              <span className="truncate">{labels[i]}</span>
            </p>
            {q.isPending && source === "studio" ? (
              <LoadingState label="Reading the copy…" className="px-4 py-3" />
            ) : q.error ? (
              <div className="p-3">
                <ErrorState error={q.error} onRetry={() => void q.refetch()} />
              </div>
            ) : lines.length === 0 ? (
              <p className="px-4 py-3 text-[13px] text-ink-muted">This version has no text elements.</p>
            ) : (
              <dl className="ledger-rules">
                {lines.map((l) => (
                  <div key={l.id} className="space-y-0.5 px-4 py-2.5">
                    <dt className="type-meta">{humanize(l.kind === "cta" ? "call to action" : l.kind)}{l.lang ? ` · ${l.lang}` : ""}</dt>
                    <dd lang={l.lang ?? undefined} className="text-[14px] leading-relaxed whitespace-pre-line text-ink">
                      {l.text}
                    </dd>
                  </div>
                ))}
              </dl>
            )}
          </section>
        );
      })}
    </div>
  );
}
