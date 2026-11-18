"use client";

import { Database, MessageSquareText, TriangleAlert } from "lucide-react";
import type { ReactNode } from "react";

import { Tag } from "@/components/evidence/badges";

import { ClaimsDisclosure } from "./claims";
import { KIND_LABEL, lineCounts, lineProblems, scriptName } from "./model";
import { Failed, languageLabel, Passed, Status, useStudio } from "./parts";
import type { LineResult } from "./types";

/** One quiet source line under a result: what the back-translation is and where the checks run. */
export function TranscreateLimits() {
  return <p className="type-meta">Source: back-translation by the same model run as the copy; script and glossary checks computed in code; no native-speaker review.</p>;
}

function CheckRow({ label, result, children }: { label: string; result: ReactNode; children?: ReactNode }) {
  return (
    <div className="grid grid-cols-[8.5rem_minmax(0,1fr)] gap-x-3 gap-y-0.5 px-3 py-1.5 sm:grid-cols-[9.5rem_9.5rem_minmax(0,1fr)]">
      <dt className="text-[12.5px] text-ink-secondary">{label}</dt>
      <dd className="contents">
        <span>{result}</span>
        <span className="col-span-2 text-[12.5px] text-ink-body sm:col-span-1">{children}</span>
      </dd>
    </div>
  );
}

function Checks({ line }: { line: LineResult }) {
  const t = line.term_checks;
  const s = line.script_check;
  const protectedBad = t.missing_in_copy.length > 0 || t.missing_in_back_translation.length > 0;
  const prohibitedBad = t.prohibited_in_copy.length > 0 || t.prohibited_in_back_translation.length > 0;
  const shares = Object.entries(s.shares)
    .map(([code, share]) => `${scriptName(code)} ${Math.round(share * 100)}%`)
    .join(", ");
  return (
    <dl aria-label="Checks" className="ledger-rules type-ledger overflow-hidden rounded-lg border border-border">
      <CheckRow label={`Script (${scriptName(s.expected_script)})`} result={s.ok ? <Passed /> : <Failed />}>
        {s.message}
        {shares && <span className="text-ink-muted"> Letters by script: {shares}.</span>}
      </CheckRow>
      <CheckRow label="Protected terms" result={protectedBad ? <Failed /> : <Passed />}>
        {protectedBad ? (
          <>
            {t.missing_in_copy.length > 0 && <>Missing from the regional copy: {t.missing_in_copy.join(", ")}. </>}
            {t.missing_in_back_translation.length > 0 && <>Altered in the back-translation: {t.missing_in_back_translation.join(", ")}.</>}
          </>
        ) : t.preserved_terms.length ? (
          <>Kept in the copy: {t.preserved_terms.join(", ")}. Checked in the back-translation too.</>
        ) : (
          "No protected term appears in the source line."
        )}
      </CheckRow>
      <CheckRow label="Prohibited terms" result={prohibitedBad ? <Failed /> : <Passed />}>
        {prohibitedBad ? (
          <>
            {t.prohibited_in_copy.length > 0 && <>In the regional copy: {t.prohibited_in_copy.join(", ")}. </>}
            {t.prohibited_in_back_translation.length > 0 && <>In the back-translation: {t.prohibited_in_back_translation.join(", ")}.</>}
          </>
        ) : (
          "None found in the copy or the back-translation."
        )}
      </CheckRow>
      <CheckRow
        label="Preferred translation"
        result={
          t.preferred_translation_missing.length ? (
            <Status tone="warning" Icon={TriangleAlert}>
              Not followed
            </Status>
          ) : (
            <Passed>Followed</Passed>
          )
        }
      >
        {t.preferred_translation_missing.length ? `The glossary prefers a specific rendering of: ${t.preferred_translation_missing.join(", ")}. Not blocking.` : "No glossary preference was missed."}
      </CheckRow>
    </dl>
  );
}

/**
 * Every line of a transcreation: the source beside the regional copy, the English back-translation under it, why the model
 * adapted it that way (labelled as interpretation unless claims support it), the claims it cites, and the check results.
 * Only lines that passed were applied; the rest stay here, marked for review.
 */
export function LineResults({ lines, language }: { lines: LineResult[]; language: string }) {
  const { workspaceId, languageNames } = useStudio();
  const { passed, review } = lineCounts(lines);
  return (
    <div className="space-y-2.5">
      <p className="text-[13.5px] text-ink">
        {passed} of {lines.length} {lines.length === 1 ? "line" : "lines"} applied to the new version
        {review > 0 ? `; ${review} kept back for review.` : "."}
      </p>
      <div className="ledger-rules overflow-hidden rounded-card border border-border bg-surface">
        {lines.map((line) => {
          const problems = lineProblems(line);
          return (
            <article key={line.element_id} aria-label={`${KIND_LABEL[line.kind]} ${line.element_id}`} className="space-y-3 px-4 py-3.5">
              <header className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <h4 className="text-[14px] font-semibold text-ink">
                  {KIND_LABEL[line.kind]} <span className="font-mono text-[11.5px] font-normal text-ink-muted">{line.element_id}</span>
                </h4>
                {line.passed ? (
                  <Passed>Applied</Passed>
                ) : (
                  <Status tone="warning" Icon={TriangleAlert}>
                    Needs review, not applied
                  </Status>
                )}
              </header>
              <div className="grid gap-x-6 gap-y-3 md:grid-cols-2">
                <div className="min-w-0">
                  <p className="type-meta mb-1 font-medium text-ink-secondary">Source</p>
                  <p className="text-[14.5px] leading-relaxed text-ink-body">{line.source_text}</p>
                </div>
                <div className="min-w-0 space-y-2">
                  <div>
                    <p className="type-meta mb-1 font-medium text-ink-secondary">Regional copy · {languageLabel(languageNames, language)}</p>
                    <p lang={language} className="text-[15px] leading-relaxed text-ink">
                      {line.regional_copy}
                    </p>
                  </div>
                  <div className="border-t border-border pt-2">
                    <p className="type-meta mb-1 font-medium text-ink-secondary">English back-translation</p>
                    <p className="text-[14px] leading-relaxed text-ink-body">{line.back_translation}</p>
                  </div>
                </div>
              </div>
              <div className="flex flex-wrap items-start gap-x-3 gap-y-1.5">
                {line.reasoning_type === "evidence_supported" ? (
                  <Tag className="border-info/25 bg-info-soft text-info" title="The adaptation cites claims that exist in this workspace.">
                    <Database aria-hidden />
                    Evidence supported
                  </Tag>
                ) : (
                  <Tag className="border-dashed border-ink-secondary/50 bg-surface text-ink-secondary" title="The reasoning is the model's own; no claim supports it.">
                    <MessageSquareText aria-hidden />
                    Model interpretation
                  </Tag>
                )}
                <p className="min-w-0 flex-1 text-[13px] text-ink-body">{line.explanation}</p>
              </div>
              <ClaimsDisclosure workspaceId={workspaceId} claimIds={line.claim_ids} />
              <Checks line={line} />
              {!line.passed && problems.length > 0 && (
                <ul className="list-disc space-y-0.5 pl-5 text-[13px] text-danger">
                  {problems.map((p) => (
                    <li key={p}>
                      <span className="text-ink">{p}</span>
                    </li>
                  ))}
                </ul>
              )}
            </article>
          );
        })}
      </div>
    </div>
  );
}
