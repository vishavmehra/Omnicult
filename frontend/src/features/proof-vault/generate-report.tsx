"use client";

import { FilePlus2, LoaderCircle, X } from "lucide-react";
import { useId, useState, type FormEvent } from "react";

import { ErrorState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

import { useCreateProofReport, useRegions } from "./api";
import { SELECT_CLASS } from "./parts";

const MAX_REGIONS = 10;

/**
 * Creates the campaign's next snapshot. The report is assembled from stored records by fixed rules; no model is called,
 * so it costs nothing and can be repeated. Regions default to the campaign's own target regions.
 */
export function GenerateReport({
  campaignId,
  suggestChoose,
  onCreated,
  onCancel,
}: {
  campaignId: string;
  /** True when the newest snapshot found no target regions on the campaign, so choosing regions is the useful default. */
  suggestChoose: boolean;
  onCreated: (reportId: string) => void;
  onCancel?: () => void;
}) {
  const uid = useId();
  const regions = useRegions();
  const create = useCreateProofReport(campaignId);
  const [title, setTitle] = useState("");
  const [choose, setChoose] = useState(suggestChoose);
  const [codes, setCodes] = useState<string[]>([]);
  const nameOf = (code: string) => regions.data?.find((r) => r.code === code)?.name ?? code;

  function submit(e: FormEvent) {
    e.preventDefault();
    create.mutate(
      { title: title.trim() || undefined, region_codes: choose ? codes : undefined },
      { onSuccess: (report) => onCreated(report.id) },
    );
  }

  return (
    <form onSubmit={submit} className="space-y-4 rounded-card border border-border bg-surface px-4 py-4" aria-label="Generate a Proof Report">
      <div className="max-w-prose space-y-1">
        <h3 className="text-[15px] font-semibold text-ink">Generate a Proof Report</h3>
        <p className="text-[13.5px] text-ink-secondary">
          This saves a new snapshot of the campaign&apos;s evidence, conflicts, runs and limitations. It is assembled from stored records by fixed rules: no model is
          called, nothing is estimated, and earlier snapshots stay as they were.
        </p>
      </div>

      <div className="space-y-1.5">
        <label htmlFor={`${uid}-title`} className="text-[13px] font-medium text-ink">
          Title <span className="font-normal text-ink-muted">(optional)</span>
        </label>
        <Input id={`${uid}-title`} value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} placeholder="Leave empty for the default title" className="max-w-md" />
      </div>

      <fieldset className="space-y-2">
        <legend className="text-[13px] font-medium text-ink">Regions to report on</legend>
        <label className="flex items-start gap-2 text-[13.5px] text-ink-body">
          <input type="radio" name={`${uid}-regions`} checked={!choose} onChange={() => setChoose(false)} className="mt-1 size-4 accent-[var(--primary)]" />
          <span>
            The campaign&apos;s target regions
            <span className="block text-[12.5px] text-ink-muted">If the campaign has none, the region sections are listed as missing and the report is partial.</span>
          </span>
        </label>
        <label className="flex items-start gap-2 text-[13.5px] text-ink-body">
          <input type="radio" name={`${uid}-regions`} checked={choose} onChange={() => setChoose(true)} className="mt-1 size-4 accent-[var(--primary)]" />
          <span>Regions I choose (up to {MAX_REGIONS})</span>
        </label>
        {choose && (
          <div className="space-y-2 pl-6">
            <div className="flex flex-wrap items-center gap-2">
              <label htmlFor={`${uid}-add`} className="sr-only">
                Add a region
              </label>
              <select
                id={`${uid}-add`}
                value=""
                disabled={regions.isPending || codes.length >= MAX_REGIONS}
                onChange={(e) => e.target.value && setCodes((c) => (c.includes(e.target.value) ? c : [...c, e.target.value]))}
                className={SELECT_CLASS}
              >
                <option value="">{regions.isPending ? "Loading regions…" : regions.isError ? "Regions could not be loaded" : "Add a region"}</option>
                {regions.data
                  ?.filter((r) => !codes.includes(r.code))
                  .map((r) => (
                    <option key={r.code} value={r.code}>
                      {r.name} ({r.code})
                    </option>
                  ))}
              </select>
            </div>
            {codes.length > 0 ? (
              <ul className="flex flex-wrap gap-1.5" aria-label="Chosen regions">
                {codes.map((c) => (
                  <li key={c} className="inline-flex items-center gap-1 rounded-md border border-border-strong/55 bg-surface-raised py-0.5 pr-0.5 pl-2 text-[13px] text-ink">
                    {nameOf(c)} <span className="font-mono text-[11px] text-ink-muted">{c}</span>
                    <button
                      type="button"
                      onClick={() => setCodes((list) => list.filter((x) => x !== c))}
                      className="flex size-6 items-center justify-center rounded-sm text-ink-muted hover:bg-surface-muted hover:text-ink"
                      aria-label={`Remove ${nameOf(c)}`}
                    >
                      <X aria-hidden className="size-3.5" />
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-[12.5px] text-ink-muted">No region chosen yet. With none chosen, the region sections are listed as missing.</p>
            )}
          </div>
        )}
      </fieldset>

      {create.error && <ErrorState error={create.error} onRetry={() => create.reset()} />}

      <div className="flex flex-wrap gap-2">
        <Button type="submit" disabled={create.isPending}>
          {create.isPending ? <LoaderCircle aria-hidden className="animate-spin motion-reduce:animate-none" /> : <FilePlus2 aria-hidden />}
          {create.isPending ? "Assembling…" : "Generate report"}
        </Button>
        {onCancel && (
          <Button type="button" variant="ghost" onClick={onCancel} disabled={create.isPending}>
            Cancel
          </Button>
        )}
      </div>
    </form>
  );
}
