"use client";

import { toast } from "sonner";

import { ErrorState, LoadingState } from "@/components/states";
import { Verdict } from "@/components/workflow/verdict";
import { useCapabilities } from "@/features/launch/api";
import { SelectField } from "@/features/pulse/ui";
import { ApiError } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";

import { useSetVersionLink, useVersionLinks } from "./api";

type Slot = components["schemas"]["PvaLinkSlot"];
type Candidate = components["schemas"]["PvaCandidate"];

const optionLabel = (c: Candidate) => `${c.studio_label} · ${c.verdict.toUpperCase()}${c.overall_score === null ? "" : ` ${c.overall_score.toFixed(1)}`}`;

function options(slot: Slot, candidates: Candidate[]) {
  const mine = candidates.filter((c) => c.region_code === slot.region_code).map((c) => ({ value: c.version_id, label: optionLabel(c) }));
  if (slot.version_id && !mine.some((o) => o.value === slot.version_id)) {
    mine.push({ value: slot.version_id, label: `${slot.studio_label ?? "Studio version"} · no verdict stored` });
  }
  return [{ value: "", label: "Not linked" }, ...mine];
}

/** Which Creative Studio version each Pulse version stood for, per region. A slot with no link is never compared. */
export function VersionLinks({ campaignId }: { campaignId: string }) {
  const board = useVersionLinks(campaignId);
  const set = useSetVersionLink(campaignId);
  const caps = useCapabilities();
  if (board.error) return <ErrorState error={board.error} onRetry={() => void board.refetch()} />;
  if (!board.data) return <LoadingState label="Reading the version links…" />;
  const { slots, candidates } = board.data;
  const linked = slots.filter((s) => s.version_id).length;

  const change = (slot: Slot, value: string) =>
    set.mutate(
      { region_code: slot.region_code, pulse_version: slot.pulse_version, version_id: value || null },
      { onError: (e) => toast.error(e instanceof ApiError ? e.message : "Could not change the link.") },
    );

  return (
    <div className="space-y-3">
      <p className="max-w-[78ch] text-[13px] leading-snug text-ink-body">
        {linked} of {slots.length} Pulse versions are linked to a Creative Studio version. A version here is what ran in a region; its prediction is the stored Launch Room verdict of the Studio version you link it to.
        {candidates.length === 0 && " No Studio version has a stored verdict yet: compute one in Launch Room first."}
        {!caps.canCompute && caps.reason ? ` ${caps.reason}` : ""}
      </p>
      <div className="overflow-x-auto rounded-card border border-border bg-surface">
        <table className="type-ledger w-full min-w-[42rem] text-left text-[12.5px]">
          <caption className="sr-only">Each Pulse version in each region and the Creative Studio version it is linked to.</caption>
          <thead className="bg-surface-muted text-ink-secondary">
            <tr>
              <th scope="col" className="px-3 py-2 font-medium">Region</th>
              <th scope="col" className="px-3 py-2 font-medium">Pulse version</th>
              <th scope="col" className="px-3 py-2 font-medium">Studio version</th>
              <th scope="col" className="px-3 py-2 font-medium">Stored prediction</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {slots.map((s) => (
              <tr key={`${s.region_code}|${s.pulse_version}`} className="align-middle">
                <th scope="row" className="px-3 py-2 font-medium text-ink">{s.region_name}</th>
                <td className="px-3 py-2 text-ink-body">{s.pulse_version}</td>
                <td className="w-72 px-3 py-2">
                  <SelectField
                    hideLabel
                    label={`Studio version for ${s.pulse_version} in ${s.region_name}`}
                    value={s.version_id ?? ""}
                    onChange={(v) => change(s, v)}
                    options={options(s, candidates)}
                  />
                </td>
                <td className="px-3 py-2">
                  {s.verdict ? (
                    <span className="inline-flex items-center gap-2">
                      <Verdict value={s.verdict} />
                      <span className="font-semibold text-ink tabular-nums">{s.overall_score === null ? "n/a" : s.overall_score.toFixed(1)}</span>
                    </span>
                  ) : (
                    <span className="text-ink-muted">{s.version_id ? "No verdict stored" : "Not linked: not compared"}</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
