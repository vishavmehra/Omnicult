"use client";

import { Languages, UserRoundSearch } from "lucide-react";
import { useMemo, useState } from "react";

import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Tag } from "@/components/evidence/badges";
import { KIND_LABEL, scriptName } from "@/features/studio/model";

import { useScriptReport } from "./api";
import { AnchorLine, MarkedText, plural, ToneTag, type Mark } from "./parts";
import type { ScriptReportElement, ScriptReportIssue } from "./types";

const ISSUE_LABEL: Record<string, string> = {
  foreign_script: "Another script",
  wrong_script: "Script",
  mixed_script_word: "Mixed script word",
  unexpected_latin: "Latin words",
  numerals: "Numerals",
  joiner: "Joiner (ZWJ or ZWNJ)",
  invisible: "Invisible character",
  unicode: "Character sequence",
  encoding: "Damaged text",
  glossary_spelling: "Glossary spelling",
  glossary_variant: "Glossary spelling",
  prohibited_term: "Prohibited term",
  back_translation: "Back-translation",
  declared_mismatch: "Declared script",
  no_language: "No language set",
  rendering: "Text shaping",
};

const marksOf = (issues: ScriptReportIssue[]): Mark[] =>
  issues.filter((i) => i.start != null && i.end != null).map((i) => ({ start: i.start!, end: i.end!, tone: i.severity }));

function ElementRow({ element, versionLanguage }: { element: ScriptReportElement; versionLanguage: string | null }) {
  const lang = element.language ?? versionLanguage;
  const shares = Object.entries(element.shares)
    .map(([code, share]) => `${scriptName(code)} ${Math.round(share * 100)}%`)
    .join(", ");
  return (
    <article aria-label={`${KIND_LABEL[element.kind]} ${element.element_id}`} className="space-y-2.5 px-4 py-3.5">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <h4 className="text-[14px] font-semibold text-ink">{KIND_LABEL[element.kind]}</h4>
        <ToneTag tone={element.status === "ok" ? "ok" : element.status} label={element.status === "ok" ? "Passed" : element.status === "review" ? "Needs a look" : "Problem"} />
        {element.native_review_recommended && (
          <Tag className="border-warning/30 bg-warning-soft text-warning" title="A native reader should confirm this line before it runs.">
            <UserRoundSearch aria-hidden />
            Native review recommended
          </Tag>
        )}
      </header>
      <AnchorLine anchor={element.anchor} elementId={element.element_id} />
      <MarkedText text={element.text} marks={marksOf(element.issues)} lang={lang} />
      <p className="type-meta">
        {element.expected_script ? <>Expected {scriptName(element.expected_script)}</> : "No script expected"}
        {shares && <> · letters: {shares}</>}
      </p>
      {element.issues.length > 0 && (
        <ul aria-label="Issues" className="space-y-1.5">
          {element.issues.map((issue, i) => (
            <li key={i} className="flex flex-wrap items-baseline gap-x-2.5 gap-y-0.5 text-[13px]">
              <ToneTag tone={issue.severity} />
              <span className="font-medium text-ink-body">{ISSUE_LABEL[issue.code] ?? issue.code}</span>
              <span className="min-w-0 flex-1 text-ink-body">{issue.message}</span>
            </li>
          ))}
        </ul>
      )}
      {element.terms.length > 0 && (
        <ul aria-label="Brand Glossary terms in this line" className="flex flex-wrap gap-x-4 gap-y-1 text-[12.5px] text-ink-secondary">
          {element.terms.map((t, i) => (
            <li key={i}>
              <span lang={lang ?? undefined} className="text-ink">
                {t.form}
              </span>
              {t.protected && " (protected)"}
              {t.pronunciation && <> · say it: {t.pronunciation}</>}
            </li>
          ))}
        </ul>
      )}
      {element.back_translation && (
        <p className="text-[12.5px] text-ink-secondary">
          <span className="font-medium text-ink-body">{element.back_translation.state === "current" ? "Back-translation" : "Earlier back-translation (the text was edited since)"}:</span>{" "}
          {element.back_translation.text}
          {element.back_translation.clean === true && " · protected and prohibited terms checked: clean"}
        </p>
      )}
    </article>
  );
}

/**
 * Script Check: every text element of the selected version, checked in code for script, mixed scripts, numerals, joiners,
 * damaged characters and the Brand Glossary, with the exact characters marked in the element's own text.
 */
export function ScriptCheckPanel({ campaignId, versionId }: { campaignId: string; versionId: string }) {
  const report = useScriptReport(campaignId, versionId);
  const [onlyIssues, setOnlyIssues] = useState(false);
  const elements = useMemo(() => report.data?.elements ?? [], [report.data]);
  const shown = useMemo(
    () => (onlyIssues ? elements.filter((e) => e.issues.some((i) => i.severity !== "info") || e.native_review_recommended) : elements),
    [elements, onlyIssues],
  );

  if (report.isPending) return <LoadingState label="Checking the script of every line…" />;
  if (report.isError) return <ErrorState error={report.error} onRetry={() => void report.refetch()} />;
  const data = report.data;
  if (elements.length === 0) {
    return (
      <EmptyState
        title="No text to check in this version"
        description="Script Check reads headlines, body copy, calls to action, taglines and captions. This version has none with text."
        needs={[{ label: "A text element in the version", met: false }]}
      />
    );
  }
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2">
        <p className="text-[14px] text-ink">
          <span className="font-semibold">{plural(data.counts.ok, "line")} passed</span>
          {data.counts.review > 0 && <>, {data.counts.review} to look at</>}
          {data.counts.problem > 0 && <>, {data.counts.problem} with a problem</>}
          <span className="text-ink-secondary"> · {plural(data.counts.issues, "finding")}</span>
        </p>
        <label className="inline-flex cursor-pointer items-center gap-2 text-[13px] text-ink-body">
          <input type="checkbox" className="size-4" checked={onlyIssues} onChange={(e) => setOnlyIssues(e.target.checked)} />
          Only lines that need a look
        </label>
      </div>
      {shown.length === 0 ? (
        <p className="rounded-card border border-dashed border-border-strong/50 px-4 py-3 text-[13.5px] text-ink-secondary">Every line passed the code checks. Information-only notes are hidden.</p>
      ) : (
        <div className="ledger-rules overflow-hidden rounded-card border border-border bg-surface">
          {shown.map((e) => (
            <ElementRow key={e.element_id} element={e} versionLanguage={data.language} />
          ))}
        </div>
      )}
      {data.skipped.length > 0 && <p className="type-meta">Not text: {data.skipped.map((s) => `${s.element_id} (${s.reason.replace(/\.$/, "")})`).join("; ")}.</p>}
      <p className="type-meta flex items-start gap-1.5">
        <Languages aria-hidden className="mt-0.5 size-3.5 shrink-0" />
        <span>
          Source: checks run in code ({data.check_version}, shaping engine {data.shaping_engine}) against the Brand Glossary; no model. Code cannot judge meaning: a native reader confirms spelling and tone.
        </span>
      </p>
    </div>
  );
}
