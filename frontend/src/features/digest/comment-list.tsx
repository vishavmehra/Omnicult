"use client";

import { ArrowUpRight } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { regionLabel, shortVersion } from "@/features/pulse/logic";
import { SelectField, Segmented, Section } from "@/features/pulse/ui";
import type { components } from "@/lib/api/schema";
import { formatDay } from "@/features/pulse/logic";
import { cn } from "@/lib/utils";

import { useCommentList, useCommentThemes, type CommentFilters, type ListOptions } from "./api";
import { highlight, langTag, LANGUAGE_NAME, SENTIMENT_LABEL, SENTIMENTS } from "./logic";
import { MatchTag, ModelTag, SentimentTag } from "./ui";

type Summary = components["schemas"]["CommentSummary"];
type Item = components["schemas"]["CommentItem"];

const PAGE = 20;

/** The comments themselves. By default only those that match a watch term (the planted claim, a different festival), anchored to a version. */
export function CommentList({ campaignId, filters, summary }: { campaignId: string; filters: CommentFilters; summary: Summary }) {
  const [show, setShow] = useState<"flagged" | "all">(summary.is_sample ? "flagged" : "all"); // real comments rarely match a watch term: show them all
  const [sentiment, setSentiment] = useState<ListOptions["sentiment"]>(null);
  const [theme, setTheme] = useState<string | null>(null);
  const [sort, setSort] = useState<ListOptions["sort"]>("likes");
  const [limit, setLimit] = useState(PAGE);
  const themes = useCommentThemes(campaignId, filters, true);
  const read = summary.analysis !== null;
  const options: ListOptions = { flag: show === "flagged" ? "any" : null, sentiment, theme, sort, limit };
  const list = useCommentList(campaignId, filters, options, true);
  const flagged = summary.totals.flagged_comments;

  function reset<T>(set: (v: T) => void) {
    return (v: T) => {
      set(v);
      setLimit(PAGE);
    };
  }

  return (
    <Section id="comments" title="Comments" meta={read ? <ModelTag>Model interpretation: sentiment and themes</ModelTag> : undefined}>
      <div className="flex flex-wrap items-end gap-x-5 gap-y-3">
        <div className="space-y-1">
          <p className="text-[12px] font-medium text-ink-secondary">Show</p>
          <Segmented
            label="Which comments"
            value={show}
            onChange={reset(setShow)}
            options={[
              { value: "flagged", label: `Flagged (${flagged})`, title: "Comments that mention the unsourced claim or name a different festival" },
              { value: "all", label: `All (${summary.totals.comments})` },
            ]}
          />
        </div>
        {read && (
          <SelectField
            label="Sentiment"
            className="w-36"
            value={sentiment ?? ""}
            onChange={(v) => reset(setSentiment)((v || null) as ListOptions["sentiment"])}
            options={[{ value: "", label: "Any" }, ...SENTIMENTS.map((s) => ({ value: s, label: SENTIMENT_LABEL[s] }))]}
          />
        )}
        {read && (themes.data?.themes.length ?? 0) > 0 && (
          <SelectField
            label="Theme"
            className="w-52"
            value={theme ?? ""}
            onChange={(v) => reset(setTheme)(v || null)}
            options={[{ value: "", label: "Any" }, ...(themes.data?.themes ?? []).map((t) => ({ value: t.id, label: t.label }))]}
          />
        )}
        <SelectField
          label="Order"
          className="w-36"
          value={sort}
          onChange={(v) => reset(setSort)(v as ListOptions["sort"])}
          options={[{ value: "likes", label: "Most liked" }, { value: "recent", label: "Newest" }]}
        />
      </div>
      {list.error && !list.data ? (
        <ErrorState error={list.error} onRetry={() => void list.refetch()} />
      ) : !list.data ? (
        <LoadingState label="Loading the comments…" />
      ) : list.data.items.length === 0 ? (
        <p className="text-[13.5px] text-ink-secondary">No comment matches these filters.</p>
      ) : (
        <>
          <ul className={cn("ledger-rules rounded-card border border-border bg-surface transition-opacity", list.isPlaceholderData && "opacity-60")} aria-busy={list.isPlaceholderData}>
            {list.data.items.map((c) => (
              <CommentRow key={c.id} campaignId={campaignId} item={c} />
            ))}
          </ul>
          <div className="flex flex-wrap items-center gap-3">
            <p className="type-meta">
              Showing {list.data.items.length} of {list.data.total}
            </p>
            {list.data.items.length < list.data.total && (
              <Button variant="outline" size="sm" onClick={() => setLimit(limit + PAGE)}>
                Show more
              </Button>
            )}
          </div>
        </>
      )}
    </Section>
  );
}

function CommentRow({ campaignId, item }: { campaignId: string; item: Item }) {
  const matched = item.flags[0]?.matched_term;
  const parts = highlight(item.text, matched);
  const language = LANGUAGE_NAME[item.language] ?? item.language;
  return (
    <li className="space-y-2 px-4 py-3">
      <p className="type-ledger flex flex-wrap gap-x-3 gap-y-0.5 text-[12.5px] text-ink-muted">
        <span className="text-ink-body">
          {regionLabel(item.region_code, { [item.region_code]: item.region_name })}, {shortVersion(item.version_label)}
        </span>
        <span>{formatDay(item.day)}</span>
        <span>
          {language}
          {item.code_mixed ? (item.script === "Latn" ? ", in Latin letters, mixed with English" : ", mixed with English") : ""}
        </span>
        <span>
          {item.likes} {item.likes === 1 ? "like" : "likes"}
        </span>
      </p>
      <p lang={langTag(item.language, item.script)} className="max-w-[72ch] text-[14.5px] leading-relaxed text-ink">
        {parts.map((p, i) =>
          p.match ? (
            <mark key={i} className="rounded-sm bg-warning-soft px-0.5 text-ink">
              {p.text}
            </mark>
          ) : (
            <span key={i}>{p.text}</span>
          ),
        )}
      </p>
      <div className="flex flex-wrap items-center gap-1.5">
        {item.flags.map((f) => (
          <MatchTag key={f.watch_id} kind={f.kind} label={f.label} note={f.note} />
        ))}
        {item.interpretation && <SentimentTag sentiment={item.interpretation.sentiment} />}
        {item.interpretation?.themes.map((t) => (
          <span key={t.id} className="rounded-sm border border-dashed border-ink-secondary/40 px-1.5 py-px text-[11px] text-ink-secondary">
            {t.label}
          </span>
        ))}
      </div>
      <p className="type-meta flex flex-wrap items-center gap-x-2">
        <span>
          Posted under <span className="text-ink-body">{item.anchor.version_label}</span> in {item.anchor.region_name}
        </span>
        {item.anchor.studio_version_id && (
          <Link
            href={`/app/c/${campaignId}/studio?v=${item.anchor.studio_version_id}`}
            className="inline-flex items-center gap-0.5 rounded-sm text-rose hover:underline"
          >
            Open &ldquo;{item.anchor.studio_version_label}&rdquo; in Creative Studio
            <ArrowUpRight aria-hidden className="size-3.5" />
          </Link>
        )}
      </p>
    </li>
  );
}
