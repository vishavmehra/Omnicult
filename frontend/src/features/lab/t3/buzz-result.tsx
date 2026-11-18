"use client";

import { LimitationList } from "@/components/evidence/limitation-list";
import { cn } from "@/lib/utils";

import { Disclosure, Panel, RunBanner } from "../lab-parts";
import { REACTIONS, REACTION_LABEL, pluralise } from "../labels";
import { Provenance } from "../summary-parts";
import { isActive, isUsable } from "../types";
import type { BuzzCohort, BuzzResult, BuzzSummary } from "./buzz-api";
import { BuzzFeed, who } from "./buzz-feed";

type Reach = BuzzSummary["reach"];
type Dist = BuzzSummary["sentiment"];

/** One sentence from the counted reach: who saw it, who passed it on, and why it stopped. No score, no estimate. */
export function reachLine(r: Reach): string {
  const seen = `${r.exposed} of ${pluralise(r.population, "simulated account")} saw it`;
  const passed = r.resharers === 0 ? "none posted or reshared it" : `${r.resharers} posted or reshared it`;
  const end =
    r.ended === "no_new_exposure"
      ? `it stopped after round ${r.rounds_run}: nobody new was shown it`
      : r.ended === "rounds_used"
        ? `it was still being passed on when round ${r.rounds_run} ended`
        : `the run stopped early after round ${r.rounds_run}`;
  return `${seen}; ${passed}; ${end}.`;
}

/** Compact "3 positive, 1 mixed": only the stances that occur. */
function counts(d: Dist) {
  const parts = REACTIONS.filter(({ key }) => d.counts[key]).map(({ key }) => `${d.counts[key]} ${REACTION_LABEL[key].toLowerCase()}`);
  return parts.length ? parts.join(", ") : "Nothing written";
}

function SentimentLedger({ dist }: { dist: Dist }) {
  return (
    <div className="space-y-2">
      <ul className="ledger-rules type-ledger text-[13.5px]">
        {REACTIONS.map(({ key, label, Icon }) => {
          const n = dist.counts[key] ?? 0;
          return (
            <li key={key} className="grid grid-cols-[7.5rem_minmax(0,1fr)_4.5rem] items-center gap-3 py-1.5 sm:grid-cols-[9rem_minmax(0,1fr)_5rem]">
              <span className={cn("inline-flex items-center gap-1.5", n === 0 ? "text-ink-muted" : "text-ink")}>
                <Icon aria-hidden className="size-3.5 shrink-0" />
                {label}
              </span>
              <span aria-hidden className="clay-well h-2.5 rounded-[4px] p-[2px]">
                <span className="block h-full rounded-[2px] bg-ink-secondary" style={{ width: dist.denominator ? `${(n / dist.denominator) * 100}%` : 0 }} />
              </span>
              <span className="text-right text-ink-body">
                {n} <span className="text-ink-muted">of {dist.denominator}</span>
              </span>
            </li>
          );
        })}
      </ul>
      <p className="type-meta">Counted over the posts, replies and reshares that were written. Accounts that scrolled past are not counted here.</p>
    </div>
  );
}

function CohortTable({ title, rows }: { title: string; rows: BuzzCohort[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="type-ledger w-full min-w-[40rem] text-left text-[13px]">
        <caption className="sr-only">{title}</caption>
        <thead className="text-[11.5px] text-ink-muted">
          <tr className="border-b border-border">
            <th scope="col" className="py-1.5 pr-3 font-medium">{title.replace("By ", "")}</th>
            <th scope="col" className="px-2 py-1.5 text-right font-medium">Accounts</th>
            <th scope="col" className="px-2 py-1.5 text-right font-medium">Saw it</th>
            <th scope="col" className="px-2 py-1.5 text-right font-medium">Wrote</th>
            <th scope="col" className="px-2 py-1.5 text-right font-medium">Posts</th>
            <th scope="col" className="px-2 py-1.5 text-right font-medium">Replies</th>
            <th scope="col" className="px-2 py-1.5 text-right font-medium">Reshares</th>
            <th scope="col" className="py-1.5 pl-3 font-medium">What they wrote</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {rows.map((r) => (
            <tr key={r.value}>
              <th scope="row" className="py-1.5 pr-3 text-left font-normal text-ink">{r.label}</th>
              {[r.participants, r.exposed, r.expressed, r.posts, r.replies, r.shares].map((n, i) => (
                <td key={i} className={cn("px-2 py-1.5 text-right", n ? "text-ink-body" : "text-ink-muted")}>{n || "·"}</td>
              ))}
              <td className="py-1.5 pl-3 text-ink-body">{counts(r.sentiment)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RoundLedger({ rows }: { rows: BuzzSummary["rounds"] }) {
  return (
    <div className="overflow-x-auto">
      <table className="type-ledger w-full min-w-[34rem] text-left text-[13px]">
        <caption className="sr-only">What happened in each round</caption>
        <thead className="text-[11.5px] text-ink-muted">
          <tr className="border-b border-border">
            <th scope="col" className="py-1.5 pr-3 font-medium">Round</th>
            <th scope="col" className="px-2 py-1.5 text-right font-medium">Saw it</th>
            <th scope="col" className="px-2 py-1.5 text-right font-medium">Posted</th>
            <th scope="col" className="px-2 py-1.5 text-right font-medium">Replied</th>
            <th scope="col" className="px-2 py-1.5 text-right font-medium">Reshared</th>
            <th scope="col" className="px-2 py-1.5 text-right font-medium">Scrolled past</th>
            <th scope="col" className="px-2 py-1.5 text-right font-medium">Newly shown it</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {rows.map((r) => (
            <tr key={r.round_index}>
              <th scope="row" className="py-1.5 pr-3 text-left font-normal text-ink">Round {r.round_index}</th>
              {[r.exposed, r.posts, r.replies, r.shares, r.ignored, r.newly_exposed].map((n, i) => (
                <td key={i} className={cn("px-2 py-1.5 text-right", n ? "text-ink-body" : "text-ink-muted")}>{n || "·"}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function BuzzView({ result, stateName, onNewRun }: { result: BuzzResult; stateName: (code: string) => string; onNewRun(): void }) {
  const { summary, panel, participants } = result;
  const usable = isUsable(result.status);
  const active = isActive(result.status);
  const byOrdinal = new Map(participants.map((p) => [p.id, p.ordinal]));
  const label = (id: string) => who(byOrdinal.get(id) ?? 0);
  const languages = Object.entries(panel.marginal_counts.languages ?? {}).map(([code, n]) => `${participants.find((p) => p.language === code)?.language_name ?? code} ${n}`);
  const confusedActs = summary ? result.acts.filter((a) => summary.confusion.act_ids.includes(a.id)) : [];
  const platform = result.platform.charAt(0).toUpperCase() + result.platform.slice(1);

  return (
    <div className="space-y-5">
      <RunBanner run={result} label="Buzz Simulator" onNewRun={onNewRun} />

      {(usable || active || result.acts.length > 0) && (
        <Panel id="buzz-setup" title="The simulation" meta={`${pluralise(panel.generated_size, "simulated account")}`}>
          <dl className="type-ledger grid gap-x-6 gap-y-1 text-[13px] sm:grid-cols-[9rem_minmax(0,1fr)]">
            <dt className="text-ink-muted">States</dt>
            <dd className="text-ink-body">{result.regions.map((r) => r.name).join(", ")}</dd>
            <dt className="text-ink-muted">Languages</dt>
            <dd className="text-ink-body">{languages.join(" · ")}</dd>
            <dt className="text-ink-muted">Platform voice</dt>
            <dd className="text-ink-body">{platform}</dd>
            <dt className="text-ink-muted">Saw it first</dt>
            <dd className="text-ink-body">{Math.round(result.initial_exposure * 100)}% of the accounts, set for this run</dd>
            <dt className="text-ink-muted">Rounds</dt>
            <dd className="text-ink-body">{result.rounds_requested} requested; each account acts once</dd>
            <dt className="text-ink-muted">Creative</dt>
            <dd className="min-w-0 text-ink-body">{[result.creative.headline, result.creative.body, result.creative.call_to_action].filter(Boolean).join(" / ") || "No copy"}</dd>
            <dt className="text-ink-muted">Intended message</dt>
            <dd className="text-ink-body">{result.intended_message ?? "None given: compared with the creative's own copy"}</dd>
          </dl>
          <p className="mt-2 max-w-[68ch] text-xs text-ink-secondary">{panel.method}</p>
        </Panel>
      )}

      {summary && (
        <>
          <p className="max-w-[68ch] text-[15px] leading-snug text-ink">{reachLine(summary.reach)}</p>
          <p className="type-meta -mt-3">
            {summary.reach.cascade_depth > 0 ? `The longest chain of reshares was ${pluralise(summary.reach.cascade_depth, "step")} long. ` : ""}
            {summary.network_method}
          </p>

          <Panel id="buzz-rounds" title="Round by round" meta="Counted from the saved acts">
            <RoundLedger rows={summary.rounds} />
          </Panel>

          <Panel id="buzz-sentiment" title="What was written" meta="Stance of posts, replies and reshares">
            {summary.sentiment.denominator > 0 ? <SentimentLedger dist={summary.sentiment} /> : <p className="text-[13px] text-ink-muted">Nobody wrote anything: every account scrolled past.</p>}
          </Panel>

          <Panel id="buzz-cohorts" title="By state and by language" meta="Who saw it and what they did">
            <div className="space-y-4">
              <CohortTable title="By state" rows={summary.by_state} />
              <CohortTable title="By language" rows={summary.by_language} />
            </div>
            <p className="mt-2 max-w-[68ch] text-xs text-ink-secondary">Cohorts hold a handful of simulated accounts each, so differences between them are noisy. Read them as questions to ask real people.</p>
          </Panel>

          <Panel id="buzz-influence" title="Who showed it to whom" meta="Reshares that put the creative in front of someone new">
            {summary.amplifiers.length === 0 ? (
              <p className="text-[13px] text-ink-muted">Nobody posted or reshared it to someone who had not seen it, so nobody was shown it by another account.</p>
            ) : (
              <>
                <ul className="ledger-rules">
                  {summary.amplifiers.map((a) => (
                    <li key={a.participant_id} className="flex flex-wrap items-baseline justify-between gap-x-4 py-1.5 text-[13.5px]">
                      <span className="text-ink">
                        {who(a.ordinal)} <span className="text-ink-secondary">({stateName(a.state_code)}, {a.language_name})</span>
                      </span>
                      <span className="type-ledger text-ink-body">showed it to {pluralise(a.exposed_others, "account")}</span>
                    </li>
                  ))}
                </ul>
                <div className="mt-2">
                  <Disclosure summary={`Every hand-off (${summary.influence.length})`}>
                    <ul className="type-ledger columns-1 gap-6 text-[13px] text-ink-body sm:columns-2">
                      {summary.influence.map((e) => (
                        <li key={`${e.from_participant_id}-${e.to_participant_id}`}>
                          {label(e.from_participant_id)} to {label(e.to_participant_id)} <span className="text-ink-muted">(round {e.round_index})</span>
                        </li>
                      ))}
                    </ul>
                  </Disclosure>
                </div>
              </>
            )}
          </Panel>

          {summary.themes.length > 0 && (
            <Panel id="buzz-themes" title="What they talked about" meta="Topics the accounts named, interpretation">
              <ul className="ledger-rules">
                {summary.themes.map((t) => (
                  <li key={t.label} className="flex items-baseline justify-between gap-4 py-1.5 text-[13.5px]">
                    <span className="text-ink">{t.label}</span>
                    <span className="type-ledger text-ink-secondary">{pluralise(t.participants, "account")}</span>
                  </li>
                ))}
              </ul>
            </Panel>
          )}

          <Panel id="buzz-misread" title="Where it was misunderstood" meta="Confusion and changed wording">
            <div className="space-y-4">
              <div className="space-y-1.5">
                <p className="text-[13.5px] text-ink">
                  {summary.confusion.count === 0 ? "No account wrote that it was confused." : `${pluralise(summary.confusion.count, "account")} wrote that they were confused.`}
                </p>
                {confusedActs.length > 0 && (
                  <ul className="ledger-rules">
                    {confusedActs.map((a) => (
                      <li key={a.id} className="py-1.5 text-[13px] text-ink-body">
                        <span className="font-medium text-ink">{who(a.ordinal)}</span>: {a.text_en ?? a.text}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              <div className="space-y-1.5">
                <p className="text-[13.5px] text-ink">
                  {summary.mutation.compared === 0
                    ? "No account said what message it was passing on, so there is nothing to compare."
                    : `${summary.mutation.changed} of ${summary.mutation.compared} passed-on messages share few words with the ${summary.mutation.reference_source === "intended_message" ? "intended message" : "creative's copy"}.`}
                </p>
                {summary.mutation.examples.length > 0 && (
                  <ul className="ledger-rules">
                    {summary.mutation.examples.map((e) => (
                      <li key={e.act_id} className="space-y-0.5 py-1.5 text-[13px]">
                        <p className="text-ink-body">
                          <span className="font-medium text-ink">{who(e.ordinal)}</span> passed on: {e.message_gloss}
                        </p>
                        <p className="text-ink-secondary">Reference: {summary.mutation.reference}</p>
                      </li>
                    ))}
                  </ul>
                )}
                <p className="type-meta">{summary.mutation.note}</p>
              </div>
            </div>
          </Panel>
        </>
      )}

      {(result.acts.length > 0 || active) && (
        <Panel id="buzz-feed" title={active ? "What accounts are doing" : "What each account did"} meta={`${pluralise(result.acts.length, "account")} acted so far`}>
          <BuzzFeed result={result} stateName={stateName} />
        </Panel>
      )}

      <LimitationList items={result.limitations} />
      {usable && <Provenance meta={result.run_metadata} extra={[{ label: "Sampling version", value: panel.sampling_version }]} />}
    </div>
  );
}
