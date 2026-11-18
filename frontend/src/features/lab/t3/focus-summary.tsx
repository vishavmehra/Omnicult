"use client";

import { Panel, Disclosure, DistributionLedger } from "../lab-parts";
import { pluralise, REACTION_LABEL } from "../labels";
import type { FocusGroupResult } from "./focus-api";
import { jumpToTurn } from "./focus-transcript";

type Summary = FocusGroupResult["summary"];

function Jump({ index, children }: { index: number; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={() => jumpToTurn(index)}
      className="rounded-sm underline underline-offset-2 outline-none hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
    >
      {children}
    </button>
  );
}

const who = (ordinals: number[]) => ordinals.map((o) => `Participant ${o + 1}`).join(", ");

/**
 * What the saved transcript adds up to: themes, where the group split, who changed position and how each round went. All of it is
 * counted by the server from the saved turns and refreshes while the session runs. The labels it counts (stance, relation, theme)
 * are the participants' own.
 */
export function FocusSummary({ summary }: { summary: Summary }) {
  return (
    <div className="space-y-5">
      <div className="max-w-[68ch] space-y-1">
        <p className="type-meta">Counted from the saved transcript, not written by the model.</p>
        <Disclosure summary="How it is counted">
          <p className="text-xs text-ink-secondary">{summary.method}</p>
        </Disclosure>
      </div>

      <Panel id="fg-themes" title="Themes" meta={`${pluralise(summary.speakers_heard, "speaker")} heard`}>
        {summary.themes.length === 0 ? (
          <p className="text-[13px] text-ink-muted">No theme was labelled yet.</p>
        ) : (
          <ul className="ledger-rules type-ledger text-[13.5px]">
            {summary.themes.map((t) => (
              <li key={t.label} className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 py-1.5">
                <span className="text-ink">{t.label}</span>
                <span className="flex flex-wrap items-baseline gap-x-3 text-ink-body">
                  {t.participants} of {summary.speakers_heard} speakers
                  <span className="text-[12px] text-ink-secondary">
                    turn{t.turn_indices.length === 1 ? "" : "s"}{" "}
                    {t.turn_indices.map((i, k) => (
                      <span key={i}>
                        {k > 0 && ", "}
                        <Jump index={i}>{i + 1}</Jump>
                      </span>
                    ))}
                  </span>
                </span>
              </li>
            ))}
          </ul>
        )}
      </Panel>

      <Panel id="fg-disagree" title="Where they disagree">
        {summary.disagreements.length === 0 ? (
          <p className="text-[13px] text-ink-muted">No split and no direct challenge so far.</p>
        ) : (
          <ul className="ledger-rules">
            {summary.disagreements.map((d, i) => (
              <li key={i} className="space-y-1 py-2">
                <p className="type-meta">{d.kind === "stance_split" ? "A split" : "A direct challenge"} · round {d.round_index + 1}: {d.question}</p>
                <p className="text-[13.5px] text-ink">{d.description}</p>
                <ul className="flex flex-wrap gap-x-4 gap-y-0.5 text-[12.5px] text-ink-body">
                  {d.positions.map((p) => (
                    <li key={p.stance}>
                      {REACTION_LABEL[p.stance]}: {who(p.ordinals)}{" "}
                      <span className="text-ink-secondary">
                        (turn{p.turn_indices.length === 1 ? "" : "s"}{" "}
                        {p.turn_indices.map((t, k) => (
                          <span key={t}>
                            {k > 0 && ", "}
                            <Jump index={t}>{t + 1}</Jump>
                          </span>
                        ))}
                        )
                      </span>
                    </li>
                  ))}
                </ul>
                {d.from_turn_index != null && d.to_turn_index != null && (
                  <p className="text-[12.5px] text-ink-secondary">
                    Read <Jump index={d.from_turn_index}>the challenge</Jump> against <Jump index={d.to_turn_index}>the turn it answers</Jump>.
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}
      </Panel>

      <Panel id="fg-shifts" title="Who changed position" meta="First stance against last">
        {summary.shifts.length === 0 ? (
          <p className="text-[13px] text-ink-muted">Nobody has changed position so far.</p>
        ) : (
          <ul className="ledger-rules type-ledger text-[13.5px]">
            {summary.shifts.map((s) => (
              <li key={s.participant_id} className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5 py-1.5">
                <span className="text-ink">Participant {s.ordinal + 1}</span>
                <span className="text-ink-body">
                  <Jump index={s.from_turn_index}>{REACTION_LABEL[s.from_stance]}</Jump> to <Jump index={s.to_turn_index}>{REACTION_LABEL[s.to_stance]}</Jump>
                </span>
              </li>
            ))}
          </ul>
        )}
      </Panel>

      <Panel id="fg-rounds" title="Stance by round" meta="Participant turns, counted">
        <div className="space-y-3">
          {summary.rounds
            .filter((r) => r.answered > 0)
            .map((r) => (
              <Disclosure key={r.round_index} summary={`Round ${r.round_index + 1}${r.kind === "interjection" ? " (your question)" : ""}: ${r.question} (${pluralise(r.answered, "answer")})`}>
                <DistributionLedger dist={r.stance} noun="turns" />
              </Disclosure>
            ))}
          {summary.rounds.every((r) => r.answered === 0) && <p className="text-[13px] text-ink-muted">No round has been answered yet.</p>}
        </div>
      </Panel>
    </div>
  );
}
