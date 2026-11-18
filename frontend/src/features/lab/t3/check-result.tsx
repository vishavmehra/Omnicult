"use client";

import { useMemo, useState } from "react";

import { LimitationList } from "@/components/evidence/limitation-list";
import { cn } from "@/lib/utils";

import { Disclosure, Panel, RunBanner } from "../lab-parts";
import { langFor, pluralise } from "../labels";
import { Identity } from "../participants";
import { Provenance } from "../summary-parts";
import { isUsable } from "../types";
import type { MessageCheckParticipant, MessageCheckRates, MessageCheckRegion, MessageCheckResult } from "./check-api";

type Verdict = NonNullable<NonNullable<MessageCheckParticipant["response"]>["verdict"]>;

const VERDICT: Record<Verdict, string> = { understood: "Understood", partly: "Partly understood", missed: "Missed", misread: "Misread" };
const MARK = { yes: "carried", partly: "partly carried", no: "not carried" } as const;
const ROWS: { key: "understood" | "partly" | "missed" | "misread"; label: string }[] = [
  { key: "understood", label: "Understood" },
  { key: "partly", label: "Partly understood" },
  { key: "missed", label: "Missed" },
  { key: "misread", label: "Misread" },
];

/** A count and its denominator, always "x of n" and never a bare percentage. */
function Count({ n, of }: { n: number; of: number }) {
  return (
    <>
      {n} <span className="text-ink-muted">of {of}</span>
    </>
  );
}

function Bar({ parts }: { parts: { n: number; className: string }[] }) {
  const total = parts.reduce((a, p) => a + p.n, 0);
  return (
    <span aria-hidden className="clay-well flex h-2.5 overflow-hidden rounded-[4px] p-[2px]">
      {parts.map((p, i) => (
        <span key={i} className={cn("block h-full", p.className)} style={{ width: `${total ? (p.n / total) * 100 : 0}%` }} />
      ))}
    </span>
  );
}

function VerdictLedger({ rates }: { rates: MessageCheckRates }) {
  return (
    <div className="space-y-2">
      <ul className="ledger-rules type-ledger text-[13.5px]">
        {ROWS.map((r) => (
          <li key={r.key} className="grid grid-cols-[8.5rem_minmax(0,1fr)_4.5rem] items-center gap-3 py-1.5 sm:grid-cols-[10rem_minmax(0,1fr)_5rem]">
            <span className={rates[r.key] === 0 ? "text-ink-muted" : "text-ink"}>{r.label}</span>
            <Bar parts={[{ n: rates[r.key], className: "bg-ink-secondary" }, { n: Math.max(rates.denominator - rates[r.key], 0), className: "bg-transparent" }]} />
            <span className="text-right text-ink-body">
              <Count n={rates[r.key]} of={rates.denominator} />
            </span>
          </li>
        ))}
      </ul>
      {rates.failed > 0 && (
        <p className="type-meta">
          {pluralise(rates.failed, "participant")} left out: nothing usable came back for them, so they are not in these counts and are not guessed.
        </p>
      )}
    </div>
  );
}

function PointLedger({ region }: { region: MessageCheckRegion }) {
  return (
    <ul className="ledger-rules text-[13.5px]">
      {region.points.map((p) => (
        <li key={p.point_id} className="space-y-1 py-2">
          <p className="text-ink">
            <span className="type-ledger mr-2 text-[12px] text-ink-muted">{p.point_id}</span>
            {p.text}
          </p>
          <Bar
            parts={[
              { n: p.restated_yes, className: "bg-ink-secondary" },
              { n: p.restated_partly, className: "bg-border-strong" },
              { n: p.restated_no, className: "bg-transparent" },
            ]}
          />
          <p className="type-ledger flex flex-wrap gap-x-4 gap-y-0.5 text-[12.5px] text-ink-body">
            <span>
              Carried in the restatement: <Count n={p.restated_yes} of={p.denominator} />
            </span>
            <span>
              Partly: <Count n={p.restated_partly} of={p.denominator} />
            </span>
            <span>
              Not carried: <Count n={p.restated_no} of={p.denominator} />
            </span>
            <span>
              Recalled unprompted: <Count n={p.recalled} of={p.denominator} />
            </span>
          </p>
        </li>
      ))}
    </ul>
  );
}

function RegionSection({ region, languageCode }: { region: MessageCheckRegion; languageCode: Map<string, string> }) {
  const r = region.rates;
  const copy = [region.creative.headline, region.creative.body, region.creative.call_to_action].filter(Boolean).join(" / ");
  return (
    <Panel id={`mc-${region.region.code}`} title={region.region.name} meta={r.denominator ? `${pluralise(r.denominator, "synthetic participant")} compared` : "Nothing compared"}>
      <div className="space-y-5">
        <p className="text-[13px] text-ink-secondary">
          <span className="text-ink-muted">Copy read: </span>
          {copy || "No copy"}
        </p>

        {r.denominator > 0 ? (
          <>
            <VerdictLedger rates={r} />

            <section aria-label={`Key points in ${region.region.name}`} className="space-y-1">
              <p className="type-meta">Key points</p>
              <PointLedger region={region} />
            </section>

            {region.by_language.length > 1 && (
              <section aria-label={`By language in ${region.region.name}`} className="space-y-1">
                <p className="type-meta">By language</p>
                <ul className="ledger-rules type-ledger text-[13.5px]">
                  {region.by_language.map((l) => (
                    <li key={l.language} className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5 py-1.5">
                      <span lang={l.language} className="text-ink">{l.language_name}</span>
                      <span className="text-ink-body">
                        Understood <Count n={l.rates.understood} of={l.rates.denominator} />
                        <span className="text-ink-muted"> · partly {l.rates.partly} · missed {l.rates.missed} · misread {l.rates.misread}</span>
                      </span>
                    </li>
                  ))}
                </ul>
                <p className="type-meta">Slices hold a handful of synthetic participants each: read differences as questions to ask, not findings.</p>
              </section>
            )}

            <section aria-label={`Misreadings in ${region.region.name}`} className="space-y-1">
              <p className="type-meta">Misreadings</p>
              {region.misreadings.length === 0 ? (
                <p className="text-[13px] text-ink-muted">No restatement was marked as reading the message wrongly.</p>
              ) : (
                <ul className="ledger-rules">
                  {region.misreadings.map((g) => (
                    <li key={g.label} className="space-y-1.5 py-2">
                      <p className="text-[14px] text-ink">
                        {g.label} <span className="type-ledger text-[12.5px] text-ink-secondary">({pluralise(g.participants, "participant")})</span>
                      </p>
                      <ul className="space-y-1.5">
                        {g.examples.map((x) => (
                          <li key={x.participant_id} className="rounded-md bg-surface-muted/60 px-3 py-2 text-[13px]">
                            <p className="type-meta">Participant {x.ordinal + 1} · {x.language_name}</p>
                            <p lang={langFor(x.restated, languageCode.get(x.participant_id) ?? "")} className="text-ink-body">{x.restated}</p>
                            {x.restated_en !== x.restated && <p className="text-ink-secondary">In English: {x.restated_en}</p>}
                          </li>
                        ))}
                      </ul>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </>
        ) : (
          <p className="rounded-md border border-dashed border-border-strong/50 px-4 py-3 text-[13px] text-ink-secondary">
            No restatement from this region could be compared, so there is nothing to count. {r.failed > 0 && `${pluralise(r.failed, "participant")} came back with nothing usable.`}
          </p>
        )}

        {region.recommendations.length > 0 && (
          <section aria-label={`What to change in ${region.region.name}`} className="space-y-1">
            <p className="type-meta">What this suggests</p>
            <ul className="max-w-[68ch] list-disc space-y-1 pl-5 text-[13.5px] leading-snug text-ink-body marker:text-ink-muted">
              {region.recommendations.map((t, i) => (
                <li key={i}>{t}</li>
              ))}
            </ul>
          </section>
        )}
      </div>
    </Panel>
  );
}

const SHOWN = 12;

function ParticipantRow({ p, points }: { p: MessageCheckParticipant; points: Map<string, string> }) {
  const r = p.response;
  const carried = r ? r.points.reduce((a, x) => a + (x.restated === "yes" ? 1 : x.restated === "partly" ? 0.5 : 0), 0) : 0;
  return (
    <li className="space-y-2 py-3">
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-1">
        <Identity p={p} />
        <span className="text-[12.5px] font-medium text-ink">{r?.verdict ? VERDICT[r.verdict] : "Not compared"}</span>
      </div>
      {!r ? (
        <p className="text-[13px] text-ink-muted">No restatement was saved for this participant. They are left out of the counts.</p>
      ) : (
        <>
          <p lang={langFor(r.restated, p.language)} className="max-w-[68ch] text-[14px] leading-snug text-ink">{r.restated}</p>
          {r.restated_en !== r.restated && <p className="max-w-[68ch] text-[13px] text-ink-secondary">In English: {r.restated_en}</p>}
          {!r.verdict && <p className="text-[13px] text-ink-muted">Not compared: the comparison did not mark every key point, so this participant is left out of the counts.</p>}
          <Disclosure summary="Recall and marks">
            <div className="space-y-2.5 rounded-md bg-surface-muted/60 px-3 py-2.5">
              <div>
                <p className="type-meta">Remembered unprompted</p>
                {r.recall.length ? (
                  <ul className="list-disc pl-5 text-[13px] text-ink-body marker:text-ink-muted">
                    {r.recall.map((x, i) => (
                      <li key={i} lang={langFor(x, p.language)}>{x}</li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-[13px] text-ink-muted">Nothing.</p>
                )}
              </div>
              {r.points.length > 0 && (
                <ul className="type-ledger space-y-0.5 text-[12.5px]">
                  {r.points.map((x) => (
                    <li key={x.point_id} className="text-ink-body">
                      <span className="text-ink-muted">{x.point_id}</span> {points.get(x.point_id)}: {MARK[x.restated]}
                      {x.recalled ? ", recalled" : ", not recalled"}
                    </li>
                  ))}
                </ul>
              )}
              {r.misreading && (
                <p className="text-[13px] text-ink-body">
                  <span className="font-medium text-ink">Misreading: {r.misreading.label}.</span> {r.misreading.why}
                </p>
              )}
              {r.verdict && r.score !== null && (
                <p className="type-ledger text-[12.5px] text-ink-secondary">
                  Key points carried: {carried} of {r.points.length} (a partly carried point counts half).
                </p>
              )}
              {r.wording_overlap !== null && (
                <p className="type-ledger text-[12px] text-ink-muted">
                  Words in common with the message (a wording measure, not understanding): {Math.round(r.wording_overlap * 100)}%
                </p>
              )}
            </div>
          </Disclosure>
        </>
      )}
    </li>
  );
}

export function MessageCheckView({ result, onNewRun }: { result: MessageCheckResult; onNewRun(): void }) {
  const [all, setAll] = useState(false);
  const usable = isUsable(result.status);
  const summary = result.summary;
  const points = useMemo(() => new Map(result.key_points.map((k) => [k.id, k.text])), [result.key_points]);
  const languageCode = useMemo(() => new Map(result.participants.map((p) => [p.id, p.language])), [result.participants]);
  const rows = all ? result.participants : result.participants.slice(0, SHOWN);

  return (
    <div className="space-y-5">
      <RunBanner run={result} label="Message Check" onNewRun={onNewRun} />

      {usable && (
        <>
          <Panel id="mc-message" title="The message under test" meta={result.intended_message_source === "brief" ? "From the campaign brief" : "Entered for this run"}>
            <div className="space-y-3">
              <p className="max-w-[68ch] text-[15px] leading-snug text-ink">{result.intended_message}</p>
              <div>
                <p className="type-meta">
                  Key points · {result.key_points_source === "request" ? "entered for this run" : "split from the message by code"}
                </p>
                <ol className="type-ledger list-none space-y-0.5 text-[13.5px] text-ink-body">
                  {result.key_points.map((k) => (
                    <li key={k.id}>
                      <span className="mr-2 text-[12px] text-ink-muted">{k.id}</span>
                      {k.text}
                    </li>
                  ))}
                </ol>
              </div>
              {summary && (
                <div className="space-y-1.5">
                  <p className="type-meta">Verdicts follow the published rules ({summary.rules_version}).</p>
                  <Disclosure summary="Read the rules">
                    <ol className="max-w-[68ch] list-decimal space-y-1 pl-5 text-[13px] leading-snug text-ink-body marker:text-ink-muted">
                      {summary.rules.map((r, i) => (
                        <li key={i}>{r}</li>
                      ))}
                    </ol>
                  </Disclosure>
                </div>
              )}
            </div>
          </Panel>

          {summary ? (
            <>
              {summary.regions.length > 1 && (
                <p className="type-ledger text-[13px] text-ink-body">
                  Across {pluralise(summary.regions.length, "region")}: understood <Count n={summary.overall.understood} of={summary.overall.denominator} />
                  {summary.overall.failed > 0 && <span className="text-ink-muted"> · {summary.overall.failed} left out</span>}
                </p>
              )}
              {summary.regions.map((region) => (
                <RegionSection key={region.region.code} region={region} languageCode={languageCode} />
              ))}
            </>
          ) : (
            <p className="rounded-md border border-dashed border-border-strong/50 px-4 py-3 text-[13px] text-ink-secondary">
              No participant could be compared, so there are no counts. The restatements that were saved are listed below, and the limitations say why.
            </p>
          )}

          <Panel id="mc-participants" title="Participants" meta={`${result.participants.length} synthetic`}>
            <ul className="ledger-rules">
              {rows.map((p) => (
                <ParticipantRow key={p.id} p={p} points={points} />
              ))}
            </ul>
            {result.participants.length > SHOWN && (
              <button type="button" onClick={() => setAll((v) => !v)} className="mt-2 text-[12.5px] font-medium text-ink-secondary underline underline-offset-2 hover:text-ink">
                {all ? "Show fewer participants" : `Show all ${result.participants.length} participants`}
              </button>
            )}
          </Panel>
        </>
      )}

      <LimitationList items={result.limitations} />
      {usable && <Provenance meta={result.run_metadata} extra={[{ label: "Sampling version", value: result.panel.sampling_version }]} />}
    </div>
  );
}
