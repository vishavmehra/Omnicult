"use client";

import { Disclosure } from "../lab-parts";
import { langFor } from "../labels";
import { ReactionTag } from "../participants";
import type { BuzzAct, BuzzResult } from "./buzz-api";

export const ACTION_LABEL: Record<BuzzAct["action"], string> = { post: "Posted", reply: "Replied", share: "Reshared", ignore: "Scrolled past" };

export const who = (ordinal: number) => `Participant ${ordinal + 1}`;

function ActRow({ act, byId, acts, stateName }: { act: BuzzAct; byId: Map<string, BuzzResult["participants"][number]>; acts: Map<string, BuzzAct>; stateName: (code: string) => string }) {
  const reached = act.exposed_by_participant_id ? byId.get(act.exposed_by_participant_id) : null;
  const parent = act.parent_act_id ? acts.get(act.parent_act_id) : null;
  const target = parent ? `a post by ${who(parent.ordinal)}` : "the brand's post";
  const marker = act.action === "reply" ? `Replying to ${target}` : act.action === "share" ? `Reshared ${target}` : null;
  const quiet = act.action === "ignore";
  return (
    <li className="space-y-1 py-2.5">
      <p className="type-ledger flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[12.5px] text-ink-secondary">
        <span className="font-semibold text-ink">{who(act.ordinal)}</span>
        <span>{stateName(act.state_code)}</span>
        <span>{act.language_name}</span>
        <span className="font-medium text-ink-body">{ACTION_LABEL[act.action]}</span>
        <span className="text-ink-muted">{reached ? `shown it by ${who(reached.ordinal)}` : "saw it first"}</span>
        {!quiet && <ReactionTag value={act.stance} />}
      </p>
      {marker && <p className="text-[12px] text-ink-muted">{marker}</p>}
      {act.text && (
        <p lang={langFor(act.text, act.language)} className="max-w-[68ch] text-[14px] leading-snug text-ink">
          {act.text}
        </p>
      )}
      {act.text_en && act.text_en !== act.text && <p className="max-w-[68ch] text-[12.5px] text-ink-secondary">In English: {act.text_en}</p>}
      {act.message_gloss && (
        <p className="max-w-[68ch] text-[12.5px] text-ink-secondary">
          Passing on: {act.message_gloss}
          {act.changed_message && <span className="text-warning"> (few words in common with the original message)</span>}
        </p>
      )}
      {act.topics.length > 0 && <p className="text-[12px] text-ink-muted">About: {act.topics.join(", ")}</p>}
    </li>
  );
}

/** What each account did, round by round. Shows what has arrived while the run is still going. */
export function BuzzFeed({ result, stateName }: { result: BuzzResult; stateName: (code: string) => string }) {
  const byId = new Map(result.participants.map((p) => [p.id, p]));
  const acts = new Map(result.acts.map((a) => [a.id, a]));
  const rounds = [...new Set(result.acts.map((a) => a.round_index))].sort((a, b) => a - b);
  const last = rounds[rounds.length - 1];
  if (rounds.length === 0) return <p className="text-[13px] text-ink-muted">No account has acted yet.</p>;
  return (
    <div className="space-y-3">
      {rounds.map((r) => {
        const mine = result.acts.filter((a) => a.round_index === r);
        const spoke = mine.filter((a) => a.action !== "ignore").length;
        return (
          <Disclosure key={r} defaultOpen={r === last || result.acts.length <= 30} summary={`Round ${r}: ${mine.length} accounts saw it, ${spoke} wrote something`}>
            <ul className="ledger-rules">
              {mine.map((a) => (
                <ActRow key={a.id} act={a} byId={byId} acts={acts} stateName={stateName} />
              ))}
            </ul>
          </Disclosure>
        );
      })}
    </div>
  );
}
