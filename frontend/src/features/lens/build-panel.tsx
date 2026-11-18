"use client";

import { CircleAlert, CircleCheck, CircleX, Hammer, LoaderCircle, TriangleAlert, type LucideIcon } from "lucide-react";
import { useId, useState } from "react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { ApiError } from "@/lib/api/errors";
import { formatRelative } from "@/lib/format";
import { cn } from "@/lib/utils";

import { useBuild, type DataMode, type LensBuildView } from "./api";
import { sourceTypeLabel } from "./claim-entry";
import { nf } from "./parts";

const STATUS: Record<LensBuildView["status"], { label: string; Icon: LucideIcon; className: string }> = {
  completed: { label: "Completed", Icon: CircleCheck, className: "text-success" },
  partial: { label: "Completed with gaps", Icon: TriangleAlert, className: "text-warning" },
  failed: { label: "Failed", Icon: CircleX, className: "text-danger" },
};

export function BuildStatus({ status }: { status: LensBuildView["status"] }) {
  const { label, Icon, className } = STATUS[status];
  return (
    <span className={cn("inline-flex items-center gap-1 text-[12.5px] font-medium", className)}>
      <Icon aria-hidden className="size-3.5" />
      {label}
    </span>
  );
}

/** One finished build: what it stored, what is missing and every source call, with its errors. */
export function BuildSummary({ build }: { build: LensBuildView }) {
  return (
    <section aria-label={`Build ${build.version} of ${build.region_name}`} className="space-y-2.5 rounded-lg border border-border bg-surface-muted/60 px-3.5 py-3">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <p className="text-[14px] font-medium text-ink">
          {build.region_name} <span className="type-meta">build {build.version}</span>
        </p>
        <BuildStatus status={build.status} />
      </div>
      {build.error ? (
        <p className="text-[13px] text-ink">{build.error}</p>
      ) : (
        <p className="type-ledger text-[13px] text-ink-body">
          {nf.format(build.claim_count)} claims gathered: {nf.format(build.created_claims)} new, {nf.format(build.updated_claims)} already stored
          {build.conflicts_opened > 0 && `, ${build.conflicts_opened} new ${build.conflicts_opened === 1 ? "conflict" : "conflicts"}`}. Finished {formatRelative(build.finished_at)}.
        </p>
      )}
      {build.gaps.length > 0 && (
        <details className="text-[13px]">
          <summary className="cursor-pointer text-ink-secondary hover:text-ink">
            {build.gaps.length} {build.gaps.length === 1 ? "gap" : "gaps"} reported
          </summary>
          <ul className="mt-1.5 list-disc space-y-0.5 pl-5 text-ink-body">
            {build.gaps.map((g) => (
              <li key={g}>{g}</li>
            ))}
          </ul>
        </details>
      )}
      {build.calls.length > 0 && (
        <details className="text-[13px]">
          <summary className="cursor-pointer text-ink-secondary hover:text-ink">Source calls ({build.calls.length})</summary>
          <div className="mt-1.5 overflow-x-auto">
            <table className="type-ledger w-full min-w-[30rem] text-left text-[12.5px]">
              <thead className="text-ink-muted">
                <tr>
                  <th className="py-1 pr-3 font-normal">Source</th>
                  <th className="py-1 pr-3 font-normal">Operation</th>
                  <th className="py-1 pr-3 font-normal">Result</th>
                  <th className="py-1 pr-3 text-right font-normal">Claims</th>
                  <th className="py-1 text-right font-normal">Time</th>
                </tr>
              </thead>
              <tbody className="text-ink-body">
                {build.calls.map((c, i) => (
                  <tr key={i} className="border-t border-border">
                    <td className="py-1 pr-3">{sourceTypeLabel(c.source)}</td>
                    <td className="py-1 pr-3 font-mono text-[11.5px]">{c.operation}</td>
                    <td className="py-1 pr-3">
                      {c.status === "error" ? (
                        <span className="text-danger">Error: {c.error_type}</span>
                      ) : c.status === "empty" ? (
                        "Answered, nothing found"
                      ) : (
                        "Answered"
                      )}
                      {c.cached && <span className="text-ink-muted"> (from cache)</span>}
                    </td>
                    <td className="py-1 pr-3 text-right">{c.result_count}</td>
                    <td className="py-1 text-right">{c.duration_ms} ms</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {build.calls.some((c) => c.error) && (
              <ul className="mt-1.5 space-y-0.5 text-[12.5px] text-ink-secondary">
                {build.calls
                  .filter((c) => c.error)
                  .map((c, i) => (
                    <li key={i}>{c.error}</li>
                  ))}
              </ul>
            )}
          </div>
        </details>
      )}
    </section>
  );
}

/**
 * Builds the profile of one or more states. Inline, not a dialog: it states what the build will call, runs it, then shows
 * exactly what came back, including rate limits and sources that are not configured.
 */
export function BuildPanel({
  campaignId,
  mode,
  regionCodes,
  title,
  onDone,
  className,
}: {
  campaignId: string;
  mode: DataMode;
  regionCodes: string[];
  title: string;
  onDone?: () => void;
  className?: string;
}) {
  const build = useBuild(campaignId);
  const [trends, setTrends] = useState(true);
  const [grounding, setGrounding] = useState(false);
  const trendsId = useId();
  const groundingId = useId();
  const live = mode === "live";

  const run = () =>
    build.mutate(
      { region_codes: regionCodes, include_trends: trends, include_grounding: live && grounding },
      { onSuccess: () => onDone?.() },
    );
  const error = build.error instanceof ApiError ? build.error : build.error ? new ApiError(0, "NETWORK_ERROR", "The build could not be completed.") : null;

  return (
    <section aria-label={title} className={cn("space-y-3 rounded-card border border-border bg-surface px-4 py-3.5", className)}>
      <div className="space-y-1">
        <h3 className="text-[14px] font-semibold text-ink">{title}</h3>
        <p className="text-[13px] leading-snug text-ink-secondary">
          {live
            ? "Reads the offline datasets (curated references, Census 2011, public holidays) and calls the public sources (Wikidata, Wikipedia pageviews). A state can be rebuilt once every few minutes; a source that is rate limited or not configured is reported, not hidden."
            : "Reads labelled demo fixtures. No network call, no model, no cost. The claims are marked DEMO FIXTURE wherever they appear."}
        </p>
      </div>
      <div className="space-y-2 text-[13px]">
        <label htmlFor={trendsId} className="flex items-start gap-2 text-ink-body">
          <Checkbox id={trendsId} checked={trends} onCheckedChange={(v) => setTrends(v === true)} className="mt-0.5" />
          <span>
            Include public attention (Wikipedia pageviews for the festivals cited).{" "}
            <span className="text-ink-secondary">{live ? "Attention, not demand." : "Demo uses a synthetic series, labelled so."}</span>
          </span>
        </label>
        {live && (
          <label htmlFor={groundingId} className="flex items-start gap-2 text-ink-body">
            <Checkbox id={groundingId} checked={grounding} onCheckedChange={(v) => setGrounding(v === true)} className="mt-0.5" />
            <span>
              Add grounded research (Gemini with Google Search). <span className="text-ink-secondary">Costs credit; always shown as an interpretation.</span>
            </span>
          </label>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <Button type="button" variant="outline" onClick={run} disabled={build.isPending || regionCodes.length === 0}>
          {build.isPending ? <LoaderCircle aria-hidden className="animate-spin motion-reduce:animate-none" /> : <Hammer aria-hidden />}
          {build.isPending ? "Building…" : build.data ? "Build again" : "Build"}
        </Button>
        {build.isPending && (
          <p role="status" className="text-[12.5px] text-ink-secondary">
            {live ? "Calling the sources. This can take up to a minute." : "Reading the fixtures."}
          </p>
        )}
      </div>
      {error && (
        <p role="alert" className="flex items-start gap-2 rounded-lg border border-danger/35 bg-danger-soft/60 px-3 py-2 text-[13px] text-ink">
          <CircleAlert aria-hidden className="mt-0.5 size-4 shrink-0 text-danger" />
          <span>
            {error.message} {error.status === 0 ? "" : "Nothing was stored."}
            {error.details.map((d) => ` ${d.message}`).join("")}
          </span>
        </p>
      )}
      {build.data && (
        <div className="space-y-2">
          {build.data.builds.map((b) => (
            <BuildSummary key={b.id} build={b} />
          ))}
        </div>
      )}
    </section>
  );
}
