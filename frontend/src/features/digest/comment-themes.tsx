"use client";

import { regionLabel, shortVersion } from "@/features/pulse/logic";
import { Section } from "@/features/pulse/ui";
import { ErrorState, LoadingState } from "@/components/states";
import { cn } from "@/lib/utils";

import { useCommentThemes, type CommentFilters } from "./api";
import { SENTIMENT_LABEL, SENTIMENTS } from "./logic";
import { ModelTag } from "./ui";

/** The model's themes, each with the comments it carries counted by code and example comments quoted verbatim from the stored ones. */
export function CommentThemes({ campaignId, filters }: { campaignId: string; filters: CommentFilters }) {
  const themes = useCommentThemes(campaignId, filters, true);
  const data = themes.data;
  return (
    <Section id="themes" title="Themes" meta={<ModelTag />}>
      {themes.error && !data ? (
        <ErrorState error={themes.error} onRetry={() => void themes.refetch()} />
      ) : !data ? (
        <LoadingState label="Grouping the themes…" />
      ) : !data.analysis ? (
        <p className="max-w-[68ch] text-[13.5px] text-ink-secondary">Themes appear once the comments have been read.</p>
      ) : data.themes.length === 0 ? (
        <p className="max-w-[68ch] text-[13.5px] text-ink-secondary">No theme is carried by the comments in this view.</p>
      ) : (
        <>
          <ul className={cn("ledger-rules rounded-card border border-border bg-surface transition-opacity", themes.isPlaceholderData && "opacity-60")}>
            {data.themes.map((t) => {
              const split = SENTIMENTS.filter((k) => t.sentiment[k] > 0).map((k) => `${t.sentiment[k]} ${SENTIMENT_LABEL[k].toLowerCase()}`);
              return (
                <li key={t.id}>
                  <details className="group">
                    <summary className="flex cursor-pointer list-none flex-wrap items-baseline gap-x-3 gap-y-1 px-4 py-3 hover:bg-surface-muted focus-visible:-outline-offset-2 [&::-webkit-details-marker]:hidden">
                      <span className="text-[14.5px] font-medium text-ink">{t.label}</span>
                      <span className="type-ledger text-[12.5px] text-ink-muted tabular-nums">
                        {t.comments} {t.comments === 1 ? "comment" : "comments"}
                        {split.length ? ` · ${split.join(", ")}` : ""}
                      </span>
                      <span className="basis-full text-[13.5px] text-ink-secondary">{t.summary}</span>
                      <span className="type-meta basis-full">
                        {t.regions.map((r) => `${regionLabel(r.key)} ${r.comments}`).join(" · ")}
                        <span className="ml-2 text-ink-muted group-open:hidden">Show example comments</span>
                        <span className="ml-2 hidden text-ink-muted group-open:inline">Hide example comments</span>
                      </span>
                    </summary>
                    <ul className="space-y-2 px-4 pb-3">
                      {t.quotes.map((q) => (
                        <li key={q.id} className="rounded-lg border border-border bg-surface-muted/60 px-3 py-2">
                          <blockquote lang={q.language} className="text-[14px] leading-relaxed text-ink-body">
                            {q.text}
                          </blockquote>
                          <p className="type-meta mt-1">
                            {regionLabel(q.region_code)} · {shortVersion(q.version_label)} · {q.likes} {q.likes === 1 ? "like" : "likes"}
                            {q.sentiment ? ` · ${SENTIMENT_LABEL[q.sentiment]} (model label)` : ""}
                          </p>
                        </li>
                      ))}
                    </ul>
                  </details>
                </li>
              );
            })}
          </ul>
          <p className="max-w-[78ch] text-[12.5px] leading-snug text-ink-secondary">
            The theme names and descriptions are the model&apos;s. The counts are calculated from its labels, and each example is a stored comment, most liked first, never written by a model.
            {data.unthemed > 0 ? ` ${data.unthemed} read comments carry no theme.` : ""}
          </p>
        </>
      )}
    </Section>
  );
}
