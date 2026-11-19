"use client";

import { ArrowLeftRight, ArrowDown, ArrowUp, Flag, MessageSquareText, Minus, ThumbsDown, ThumbsUp, TriangleAlert, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { Tag } from "@/components/evidence/badges";
import { LABEL_MEANING } from "@/lib/evidence";
import { cn } from "@/lib/utils";

import { MODEL_INTERPRETATION, SENTIMENT_LABEL, type SentimentLabel } from "./logic";

/** The disclosure for anything a model wrote or labelled: dashed border and the speech mark, same words as the evidence labels. */
export function ModelTag({ className, children = MODEL_INTERPRETATION }: { className?: string; children?: ReactNode }) {
  return (
    <Tag className={cn("border-dashed border-ink-secondary/50 bg-surface text-ink-secondary", className)} title={LABEL_MEANING["Model interpretation"]}>
      <MessageSquareText aria-hidden />
      {children}
    </Tag>
  );
}

const SENTIMENT: Record<SentimentLabel, { Icon: LucideIcon; className: string }> = {
  positive: { Icon: ThumbsUp, className: "text-success" },
  neutral: { Icon: Minus, className: "text-ink-secondary" },
  negative: { Icon: ThumbsDown, className: "text-danger" },
  mixed: { Icon: ArrowLeftRight, className: "text-warning" },
};

/** A model's sentiment label for one comment: icon, word and the dashed model-interpretation border (colour never carries it alone). */
export function SentimentTag({ sentiment }: { sentiment: SentimentLabel }) {
  const { Icon, className } = SENTIMENT[sentiment];
  return (
    <Tag className="border-dashed border-ink-secondary/50 bg-surface text-ink-secondary" title={`${SENTIMENT_LABEL[sentiment]}. ${LABEL_MEANING["Model interpretation"]}`}>
      <Icon aria-hidden className={className} />
      {SENTIMENT_LABEL[sentiment]}
    </Tag>
  );
}

/** A watch-term match that code found in the comment text. The match is observed; the note says what it may mean. */
export function MatchTag({ kind, label, note }: { kind: "planted_claim" | "cultural_misstep"; label: string; note: string }) {
  const Icon = kind === "planted_claim" ? TriangleAlert : Flag;
  return (
    <Tag className="border-warning/30 bg-warning-soft text-warning" title={`${note} Found by matching a watch term in the comment text.`}>
      <Icon aria-hidden />
      {label}
    </Tag>
  );
}

export type Judgement = "better" | "worse" | "same" | "neutral";

/** Change against the earlier period: an arrow for the direction and, when the metric has a good direction, the word for it. */
export function Move({ text, direction, judgement, className }: { text: string; direction: "up" | "down" | "flat"; judgement: Judgement; className?: string }) {
  const Icon = direction === "up" ? ArrowUp : direction === "down" ? ArrowDown : Minus;
  const tone = judgement === "better" ? "text-success" : judgement === "worse" ? "text-danger" : "text-ink-secondary";
  return (
    <span className={cn("inline-flex items-center gap-1 text-[12px] tabular-nums", tone, className)}>
      <Icon aria-hidden className="size-3" />
      {text}
      {(judgement === "better" || judgement === "worse") && <span className="sr-only"> ({judgement})</span>}
    </span>
  );
}
