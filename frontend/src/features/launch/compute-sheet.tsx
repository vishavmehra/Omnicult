"use client";

import { CircleDashed, Gauge, Info, LoaderCircle } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Verdict } from "@/components/workflow/verdict";
import { cn } from "@/lib/utils";

import { useCapabilities, useComputeReadiness, useRegions, useVersionOptions } from "./api";
import { NativeSelect, WIDE_SHEET } from "./bits";
import { useInputs } from "./inputs-store";
import { ObservationEditor } from "./observation-editor";
import { GROUP_LABEL, MISSING_EFFECT, missingGroups, toObservations, type GroupKey } from "./observations";
import { useRegionChoices } from "./region-choices";

export type ComputePreset = { regionCode?: string; versionId?: string };

/** Which readiness rule holds the verdict at Fix when this group is missing (readiness.py FX12 to FX14). */
const HOLD_RULE: Partial<Record<GroupKey, string>> = { quick_read: "FX13", risk_check: "FX14", evidence_meter: "FX12" };

function ComputeForm({ campaignId, preset, onDone }: { campaignId: string; preset: ComputePreset; onDone(): void }) {
  const versions = useVersionOptions();
  const regions = useRegions();
  const choices = useRegionChoices(regions.data);
  const caps = useCapabilities();
  const store = useInputs();
  const compute = useComputeReadiness(campaignId);
  const [regionCode, setRegionCode] = useState(preset.regionCode ?? "");
  const [versionId, setVersionId] = useState(preset.versionId ?? "");

  const option = versions.options.find((o) => o.id === versionId);
  const draft = store.get(versionId, regionCode);
  const { value, problems } = useMemo(() => toObservations(draft), [draft]);
  const problemList = Object.values(problems);
  const missing = missingGroups(draft);
  const holds = missing.map((g) => HOLD_RULE[g]).filter(Boolean);
  const ready = Boolean(option) && regionCode !== "" && problemList.length === 0 && caps.canCompute && !compute.isPending;

  function submit() {
    if (!option) return;
    compute.mutate(
      { region_code: regionCode, version_id: option.id, label: option.label.slice(0, 60), observations: value },
      {
        onSuccess: ({ verdict, created }) => {
          const name = regions.data?.find((r) => r.code === regionCode)?.name ?? regionCode;
          toast.success(
            created
              ? `New verdict stored for ${name}: ${verdict.verdict === "go" ? "Go" : verdict.verdict === "fix" ? "Fix" : "Rethink"}.`
              : `Same inputs and rules as the newest verdict for ${name}, so nothing new was stored.`,
          );
          onDone();
        },
      },
    );
  }

  if (versions.error) return <ErrorState error={versions.error} onRetry={() => void versions.refetch()} />;
  if (versions.isPending) return <LoadingState label="Reading this campaign’s versions…" />;

  return (
    <>
      <div className="min-h-0 flex-1 space-y-5 overflow-y-auto px-4 pb-4">
        {!caps.loading && caps.reason && !caps.canCompute && (
          <p role="status" className="flex items-start gap-2 rounded-lg border border-border bg-surface-muted/70 px-3.5 py-2.5 text-[13px] text-ink-body">
            <Info aria-hidden className="mt-0.5 size-4 shrink-0 text-ink-secondary" />
            {caps.reason}
          </p>
        )}
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1.5">
            <label htmlFor="compute-region" className="block text-[13px] font-medium text-ink">Region</label>
            <NativeSelect id="compute-region" value={regionCode} onChange={(e) => setRegionCode(e.target.value)} disabled={regions.isPending}>
              <option value="">{regions.isPending ? "Loading regions…" : "Choose a region"}</option>
              {choices.map((g) => (
                <optgroup key={g.label} label={g.label}>
                  {g.regions.map((r) => (
                    <option key={r.code} value={r.code}>{r.name} ({r.code})</option>
                  ))}
                </optgroup>
              ))}
            </NativeSelect>
          </div>
          <div className="space-y-1.5">
            <label htmlFor="compute-version" className="block text-[13px] font-medium text-ink">Version</label>
            <NativeSelect
              id="compute-version"
              value={versionId}
              onChange={(e) => {
                setVersionId(e.target.value);
                const picked = versions.options.find((o) => o.id === e.target.value);
                if (picked?.regionCode && !regionCode) setRegionCode(picked.regionCode);
              }}
            >
              <option value="">Choose a version</option>
              {versions.options.map((o) => (
                <option key={o.id} value={o.id}>{o.label}</option>
              ))}
            </NativeSelect>
          </div>
        </div>

        {option && regionCode ? (
          <>
            <ObservationEditor versionId={option.id} regionCode={regionCode} />
            <div aria-live="polite" className="space-y-1.5 rounded-card border border-border bg-surface px-4 py-3">
              <p className="text-[13.5px] font-semibold text-ink">If you compute now</p>
              {missing.length === 0 ? (
                <p className="text-[13px] text-ink-body">All six observation groups are present. The rules decide from what was supplied; they still report every limitation.</p>
              ) : (
                <>
                  <p className="text-[13px] text-ink-body">
                    {missing.length} of 6 observation groups are missing.
                    {holds.length > 0 && ` Rules ${holds.join(", ")} will hold the verdict at Fix at best until they are supplied.`}
                  </p>
                  <ul className="space-y-1 text-[12.5px] text-ink-secondary">
                    {missing.map((g) => (
                      <li key={g} className="flex items-start gap-1.5">
                        <CircleDashed aria-hidden className="mt-0.5 size-3.5 shrink-0 text-warning" />
                        <span>
                          <span className="font-medium text-ink-body">{GROUP_LABEL[g]}: </span>
                          {MISSING_EFFECT[g]}
                        </span>
                      </li>
                    ))}
                  </ul>
                </>
              )}
              <p className="text-[12.5px] text-ink-muted">Identical inputs under the same rules return the newest stored verdict instead of adding a duplicate.</p>
            </div>
          </>
        ) : (
          <p className="text-[13.5px] text-ink-secondary">Choose a region and a version to enter or gather the observations the rules read.</p>
        )}
        {compute.error && <ErrorState error={compute.error} onRetry={submit} />}
        {compute.data && !compute.isPending && (
          <p className="flex items-center gap-2 text-[13px] text-ink-body">
            <Verdict value={compute.data.verdict.verdict} />
            Latest result for these inputs.
          </p>
        )}
      </div>
      <SheetFooter className="border-t border-border">
        <Button disabled={!ready} onClick={submit}>
          {compute.isPending ? <LoaderCircle aria-hidden className="animate-spin motion-reduce:animate-none" /> : <Gauge aria-hidden />}
          {compute.isPending ? "Computing…" : "Compute verdict"}
        </Button>
        {problemList.length > 0 && <p role="alert" className="text-[12.5px] font-medium text-danger">Fix the highlighted inputs first.</p>}
      </SheetFooter>
    </>
  );
}

/** Compute and store a Go, Fix or Rethink recommendation for one version in one region. Needs the owner or editor role. */
export function ComputeSheet({ campaignId, open, onOpenChange, preset }: { campaignId: string; open: boolean; onOpenChange(open: boolean): void; preset: ComputePreset }) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className={cn("gap-0", WIDE_SHEET)}>
        <SheetHeader>
          <SheetTitle>Compute a verdict</SheetTitle>
          <SheetDescription>
            The rules read the observations below and return Go, Fix or Rethink with their reasons. The verdict is stored with its inputs and a history; it is a recommendation, never an approval.
          </SheetDescription>
        </SheetHeader>
        <ComputeForm campaignId={campaignId} preset={preset} onDone={() => onOpenChange(false)} />
      </SheetContent>
    </Sheet>
  );
}
