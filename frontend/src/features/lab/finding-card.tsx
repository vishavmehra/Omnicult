"use client";

import { ExternalLink, OctagonAlert, Sigma } from "lucide-react";
import { useState } from "react";

import { Tag } from "@/components/evidence/badges";
import { ConfidenceIndicator } from "@/components/evidence/confidence";
import { KindTag } from "@/components/evidence/evidence-row";
import { ErrorState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { formatRelative } from "@/lib/format";
import { cn } from "@/lib/utils";

import { useUpdateFinding } from "./api";
import { Disclosure } from "./lab-parts";
import { CATEGORY_LABEL, FINDING_STATUS, SEVERITY, describeAnchor } from "./labels";
import type { AdCodeEntry, CreativeElement, FindingStatus, GroundingClaim, RiskCheckFinding } from "./types";

const SUPPORT = {
  moderate: { label: "Moderate", filled: 2, rule: "A cited ASCI clause fits the category and an observed or calculated region claim at moderate confidence or better also backs it." },
  limited: { label: "Limited", filled: 1, rule: "Either a cited ASCI clause fits the category or an observed or calculated region claim backs it, not both." },
  insufficient: { label: "Insufficient", filled: 0, rule: "Neither a fitting ASCI clause nor a backing region claim was found. The finding rests on a model's reading alone." },
} as const;

/** How much code-checkable support a finding has. A label with its rule, never a probability. */
function SupportLabel({ value }: { value: RiskCheckFinding["confidence_label"] }) {
  const s = SUPPORT[value];
  return (
    <Tooltip>
      <TooltipTrigger className="inline-flex cursor-help items-center gap-1.5 rounded-sm text-[12.5px] leading-none whitespace-nowrap" aria-label={`Evidence support: ${s.label}. ${s.rule} A label, not a probability.`}>
        <span aria-hidden className="clay-well inline-flex gap-[3px] rounded-[4px] p-[3px]">
          {[0, 1].map((i) => (
            <span key={i} className={cn("h-2.5 w-[7px] rounded-[2px]", i < s.filled ? "bg-ink-secondary" : "bg-transparent")} />
          ))}
        </span>
        <span className="text-ink-secondary">Evidence support:</span>
        <span className="font-medium text-ink">{s.label}</span>
      </TooltipTrigger>
      <TooltipContent className="max-w-72 flex-col items-start gap-1 text-left">
        <span className="font-medium">Evidence support: {s.label}</span>
        <span>{s.rule}</span>
        <span className="opacity-80">A label computed from what code could check. Not a probability, and not a legal conclusion.</span>
      </TooltipContent>
    </Tooltip>
  );
}

/** The element's text with the verified quote marked, trimmed to the words around it. */
function QuoteInContext({ finding, element }: { finding: RiskCheckFinding; element: CreativeElement | undefined }) {
  const text = typeof element?.value === "string" ? element.value : null;
  const q = finding.quote;
  if (!q) return null;
  const lang = element?.language ?? undefined;
  const { quote_start: a, quote_end: b } = finding;
  if (text && a != null && b != null && text.slice(a, b) === q) {
    const before = text.slice(Math.max(0, a - 70), a);
    const after = text.slice(b, b + 70);
    return (
      <blockquote lang={lang} className="rounded-md border border-border bg-surface-muted/60 px-3 py-2 text-[14px] leading-relaxed text-ink">
        {a > 70 && "… "}
        {before}
        <mark className="rounded-[3px] bg-warning-soft px-0.5 font-medium text-ink underline decoration-warning decoration-2 underline-offset-2">{q}</mark>
        {after}
        {b + 70 < text.length && " …"}
      </blockquote>
    );
  }
  return (
    <blockquote lang={lang} className="rounded-md border border-border bg-surface-muted/60 px-3 py-2 text-[14px] leading-relaxed text-ink">
      {q}
    </blockquote>
  );
}

function AdCodeCited({ ad, index }: { ad: RiskCheckFinding["ad_codes"][number]; index: AdCodeEntry | undefined }) {
  const [full, setFull] = useState(false);
  return (
    <li className="space-y-1.5 rounded-md border border-border bg-surface-muted/50 px-3 py-2.5">
      <p className="text-[13px] font-medium text-ink">
        ASCI Code, clause {ad.clause} <span className="font-normal text-ink-secondary">· {ad.title}</span>
      </p>
      <p className="type-meta">{index?.chapter ?? ad.document}</p>
      <blockquote className={cn("max-w-[68ch] text-[13px] leading-relaxed text-ink-body", !full && "line-clamp-3")}>{ad.excerpt}</blockquote>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        {ad.excerpt.length > 220 && (
          <button type="button" onClick={() => setFull((v) => !v)} className="text-[12px] font-medium text-ink-secondary underline underline-offset-2 hover:text-ink">
            {full ? "Show less" : "Show the full clause"}
          </button>
        )}
        <a href={ad.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-[12.5px] text-rose underline-offset-2 hover:underline">
          ASCI Codes and Guidelines{index ? `, PDF page ${index.pdf_page}` : ""}
          <ExternalLink aria-hidden className="size-3" />
          <span className="sr-only">(opens the ASCI document in a new tab)</span>
        </a>
      </div>
    </li>
  );
}

function StatusControls({ finding, campaignId, runId }: { finding: RiskCheckFinding; campaignId: string; runId: string }) {
  const update = useUpdateFinding(campaignId, runId);
  const [dismissing, setDismissing] = useState(false);
  const [reason, setReason] = useState("");
  const [touched, setTouched] = useState(false);
  const set = (status: FindingStatus, why?: string) => update.mutate({ id: finding.id, status, reason: why }, { onSuccess: () => { setDismissing(false); setReason(""); setTouched(false); } });
  const s = finding.status;
  const missing = touched && reason.trim().length === 0;
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Decide on this finding">
        {s === "open" && (
          <Button size="sm" variant="outline" disabled={update.isPending} onClick={() => set("accepted")} title="You agree it is a real problem. It still counts toward Go until it is resolved.">
            Accept finding
          </Button>
        )}
        {(s === "open" || s === "accepted") && (
          <>
            <Button size="sm" variant="outline" disabled={update.isPending} onClick={() => set("fixed")} title="The creative was changed to address it.">
              Mark resolved
            </Button>
            <Button size="sm" variant="outline" disabled={update.isPending || dismissing} onClick={() => setDismissing(true)} title="You decide it is not a problem, and say why.">
              Dismiss with a reason
            </Button>
          </>
        )}
        {(s === "accepted" || s === "dismissed" || s === "fixed") && (
          <Button size="sm" variant="ghost" disabled={update.isPending} onClick={() => set("open")}>
            Reopen
          </Button>
        )}
      </div>
      {dismissing && (
        <div className="space-y-2 rounded-md border border-border bg-surface-muted/50 px-3 py-2.5">
          <label htmlFor={`dismiss-${finding.id}`} className="block text-[13px] font-medium text-ink">
            Why is this not a problem?
          </label>
          <Textarea
            id={`dismiss-${finding.id}`}
            value={reason}
            rows={2}
            maxLength={1000}
            aria-invalid={missing}
            aria-describedby={missing ? `dismiss-${finding.id}-err` : undefined}
            onChange={(e) => setReason(e.target.value)}
          />
          {missing && (
            <p id={`dismiss-${finding.id}-err`} role="alert" className="text-xs font-medium text-danger">
              A dismissal needs a reason; it is kept with the finding.
            </p>
          )}
          <div className="flex gap-2">
            <Button
              size="sm"
              variant="outline"
              disabled={update.isPending}
              onClick={() => {
                setTouched(true);
                if (reason.trim()) set("dismissed", reason);
              }}
            >
              Dismiss finding
            </Button>
            <Button size="sm" variant="ghost" onClick={() => { setDismissing(false); setTouched(false); }}>
              Cancel
            </Button>
          </div>
        </div>
      )}
      {update.error != null && <ErrorState error={update.error} onRetry={() => update.reset()} />}
    </div>
  );
}

export function FindingCard({
  finding,
  elements,
  claims,
  adCodes,
  campaignId,
  runId,
}: {
  finding: RiskCheckFinding;
  elements: CreativeElement[];
  claims: GroundingClaim[];
  adCodes: Map<string, AdCodeEntry>;
  campaignId: string;
  runId: string;
}) {
  const sev = SEVERITY[finding.severity];
  const st = FINDING_STATUS[finding.status];
  const element = elements.find((e) => e.id === finding.element_id);
  const anchor = describeAnchor(finding.anchor);
  const counts = finding.status === "open" || finding.status === "accepted";
  const deterministic = finding.source === "deterministic_check";
  const cited = finding.claim_ids.map((id) => claims.find((c) => c.id === id));
  const closed = !counts;

  return (
    <article aria-labelledby={`f-${finding.id}`} className={cn("receipt-corner rounded-card border border-border bg-surface", closed && "opacity-90")}>
      <header className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-border px-4 py-2.5">
        <Tag className={sev.className}>
          <sev.Icon aria-hidden />
          {sev.label} severity
        </Tag>
        <h4 id={`f-${finding.id}`} className="min-w-0 flex-1 text-[14.5px] font-semibold text-ink">
          {CATEGORY_LABEL[finding.category]}
        </h4>
        {finding.blocks_go && (
          <Tag
            className={cn("font-semibold", counts ? "border-danger/60 bg-danger-soft text-danger" : "border-border-strong/50 bg-surface-muted text-ink-muted")}
            title="Computed by risk-rules-v1: a high-severity finding in a category that can block a Go verdict. It counts while open or accepted."
          >
            <OctagonAlert aria-hidden />
            {counts ? "Blocks Go" : "Would block Go, now closed"}
          </Tag>
        )}
        <span className={cn("inline-flex items-center gap-1 text-[12.5px] font-medium", st.className)} title={st.meaning}>
          <st.Icon aria-hidden className="size-3.5" />
          {st.label}
        </span>
      </header>

      <div className="space-y-4 px-4 py-3.5">
        <dl className="type-ledger grid gap-x-6 gap-y-1 text-[13px] sm:grid-cols-[6.5rem_minmax(0,1fr)]">
          <dt className="text-ink-muted">Element</dt>
          <dd className="min-w-0 text-ink-body">
            <span className="font-mono text-[12px] text-ink">{finding.element_id}</span>
            {element && <span className="text-ink-secondary"> ({element.kind})</span>}
          </dd>
          <dt className="text-ink-muted">Scene</dt>
          <dd className="text-ink-body">{anchor.scene ? <span className="font-mono text-[12px]">{anchor.scene}</span> : "Not tied to a scene"}</dd>
          <dt className="text-ink-muted">Time</dt>
          <dd className="text-ink-body">{anchor.time ?? "No time range"}</dd>
          <dt className="text-ink-muted">Place in frame</dt>
          <dd className="text-ink-body">{anchor.box ?? "Not placed in the frame"}</dd>
        </dl>

        {finding.quote && (
          <div className="space-y-1">
            <p className="type-meta">{finding.verification === "quote_verified" ? "Quoted text, found in the element by code" : "Quoted text"}</p>
            <QuoteInContext finding={finding} element={element} />
          </div>
        )}

        <div className="grid gap-4 md:grid-cols-2">
          <div className="space-y-1">
            <p className="type-meta">Observation: what is there</p>
            <p className="max-w-[68ch] text-[14px] leading-snug text-ink">{finding.observation}</p>
          </div>
          <div className="space-y-1">
            <p className="type-meta flex flex-wrap items-center gap-2">
              Interpretation: why it may matter here
              {deterministic ? (
                <Tag className="border-border bg-surface-muted text-ink" title="Produced by a code rule, not a model.">
                  <Sigma aria-hidden />
                  Rule check
                </Tag>
              ) : (
                <Tag className="border-dashed border-ink-secondary/50 bg-surface text-ink-secondary" title="A model's reading. Not an established fact or a violation.">
                  Model interpretation
                </Tag>
              )}
            </p>
            <p className="max-w-[68ch] text-[14px] leading-snug text-ink">{finding.interpretation}</p>
          </div>
        </div>

        {finding.suggested_fix && (
          <div className="space-y-1">
            <p className="type-meta">Suggested fix</p>
            <p className="max-w-[68ch] text-[14px] leading-snug text-ink">{finding.suggested_fix}</p>
          </div>
        )}

        <div className="space-y-2">
          <p className="type-meta">ASCI references {finding.ad_codes.length === 0 && "(none cited)"}</p>
          {finding.ad_codes.length > 0 && (
            <ul className="space-y-2">
              {finding.ad_codes.map((ad) => (
                <AdCodeCited key={ad.id} ad={ad} index={adCodes.get(ad.id)} />
              ))}
            </ul>
          )}
        </div>

        {finding.claim_ids.length > 0 && (
          <div className="space-y-1.5">
            <p className="type-meta">Region claims it rests on</p>
            <ul className="space-y-1.5">
              {cited.map((c, i) => (
                <li key={finding.claim_ids[i]} className="rounded-md bg-surface-muted/60 px-3 py-2 text-[13px]">
                  {c ? (
                    <>
                      <p className="text-ink">{c.value_text}</p>
                      <p className="type-ledger mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-ink-secondary">
                        <KindTag kind={c.kind} />
                        <ConfidenceIndicator level={c.confidence} />
                      </p>
                    </>
                  ) : (
                    <p className="text-ink-secondary">
                      Claim <span className="font-mono text-[11.5px]">{finding.claim_ids[i].slice(0, 8)}</span> is not in the set this run was given.
                    </p>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2">
          <SupportLabel value={finding.confidence_label} />
          <Disclosure summary="How severity was computed">
            <div className="space-y-2">
              <ol className="ledger-rules type-ledger rounded-md border border-border text-[12.5px]">
                {finding.severity_rules.map((r, i) => (
                  <li key={i} className="grid gap-x-3 px-3 py-1.5 sm:grid-cols-[8rem_3.5rem_minmax(0,1fr)]">
                    <span className="font-mono text-[11.5px] text-ink">{r.rule}</span>
                    <span className="text-ink-secondary">{r.effect}</span>
                    <span className="text-ink-body">{r.reason}</span>
                  </li>
                ))}
              </ol>
              <p className="max-w-[68ch] text-xs text-ink-secondary">
                Rules {finding.rules_version}, applied by code. Severity is not a probability and not a legal conclusion. {finding.source === "model_assessment" ? "A model proposed the finding; code verified its quote and set its severity." : "A fixed code rule raised the finding."}
              </p>
              {finding.limitations.length > 0 && (
                <ul className="list-disc space-y-0.5 pl-5 text-[12.5px] text-ink-body marker:text-ink-muted">
                  {finding.limitations.map((l, i) => (
                    <li key={i}>{l}</li>
                  ))}
                </ul>
              )}
            </div>
          </Disclosure>
        </div>

        <div className="space-y-2 border-t border-border pt-3">
          {finding.status_reason && (
            <p className="text-[13px] text-ink-body">
              <span className="text-ink-muted">Reason recorded:</span> {finding.status_reason}
            </p>
          )}
          {finding.status_at && finding.status !== "open" && <p className="type-meta">{st.label} {formatRelative(finding.status_at)}</p>}
          <StatusControls finding={finding} campaignId={campaignId} runId={runId} />
        </div>
      </div>
    </article>
  );
}
