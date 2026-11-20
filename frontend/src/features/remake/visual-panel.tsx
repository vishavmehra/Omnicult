"use client";

import { Check, TriangleAlert } from "lucide-react";
import { useState } from "react";

import { CompareSlider } from "@/components/creative";
import { Field } from "@/components/forms/fields";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { formatDate } from "@/lib/format";
import { cn } from "@/lib/utils";

import {
  useActiveLocks,
  useProjectImages,
  useRemakeRun,
  useStartVisual,
  useVersion,
  type RemakeCapabilities,
  type RemakeOutput,
  type VersionSummary,
} from "./api";
import { AiTag, AuthImage, CostConfirm, LockChip, Notice, RunProgress, SELECT, usd } from "./parts";
import { planVisual, suggestAssets } from "./plan";
import { isVideoClip } from "./video-api";

const LOCK_SOURCE = { lock: "Locked in Studio", brand_kit_never_change: "Brand Kit never-change zone" } as const;

/** Setup for a regional scene: which version and scene, which creative the locked regions come from, then run. */
export function VisualPanel({
  campaignId,
  projectId,
  demo,
  caps,
  versions,
  outputs,
}: {
  campaignId: string;
  projectId: string;
  demo: boolean;
  caps: RemakeCapabilities;
  versions: VersionSummary[];
  outputs: RemakeOutput[];
}) {
  const visuals = outputs.filter((o) => o.kind === "visual");
  const [versionId, setVersionId] = useState<string | null>(null);
  const [plateId, setPlateId] = useState<string | null>(null);
  const [originalId, setOriginalId] = useState<string | null>(null);
  const [plateAssetId, setPlateAssetId] = useState<string | null>(null);
  const [referenceId, setReferenceId] = useState<string | null>(null);
  const [direction, setDirection] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [runId, setRunId] = useState<string | null>(null);
  const [viewId, setViewId] = useState<string | null>(null);

  // Open on the newest version that already has a finished result here (in the demo that is the Tamil Nadu remake), else the newest version.
  const ready = [...versions].reverse().find((v) => visuals.some((o) => o.source_version_id === v.id));
  const version = versions.find((v) => v.id === versionId) ?? ready ?? versions[versions.length - 1] ?? null;
  const detail = useVersion(campaignId, version?.id ?? null);
  const locks = useActiveLocks(campaignId);
  const images = useProjectImages(projectId);
  const start = useStartVisual(campaignId);
  const run = useRemakeRun(campaignId, runId);

  const plan = detail.data && locks.data ? planVisual(detail.data.elements, plateId, locks.data) : null;
  const guess = suggestAssets(images.data ?? []);
  const original = originalId ?? guess.original ?? "";
  const plateAsset = plateAssetId ?? guess.plate ?? "";
  const reference = referenceId ?? guess.reference ?? "";
  const working = start.isPending || (run.data !== undefined && (run.data.status === "queued" || run.data.status === "running"));
  const hasTarget = Boolean(version?.region_code && version?.language);
  const imageOff = !demo && !caps.image.configured;
  const blockedReason = !version
    ? "This campaign has no version yet."
    : !hasTarget
      ? "Choose a version that is already adapted to a region and language."
      : plan?.blocked ?? (!demo && !original ? "Choose the finished creative: locked regions are restored from it." : null);
  const canRun = !blockedReason && !imageOff && (demo || confirmed) && !working && Boolean(plan?.plate);

  const shown = visuals.find((o) => o.run_id === runId) ?? visuals.find((o) => o.id === viewId) ?? (runId ? undefined : visuals[0]);

  function submit() {
    if (!version || !plan?.plate || !version.region_code || !version.language) return;
    start.mutate(
      {
        version_id: version.id,
        region_code: version.region_code,
        language: version.language,
        plate_element_id: plan.plate.id,
        original_asset_id: original || null,
        plate_asset_id: plateAsset || null,
        reference_asset_id: reference || null,
        direction: direction.trim() || null,
        use_region_claims: true,
        confirm_cost: !demo && confirmed,
      },
      { onSuccess: (accepted) => { setRunId(accepted.run_id); setViewId(null); setConfirmed(false); } },
    );
  }

  if (!versions.length) {
    return <EmptyState title="No version to remake yet" description="Remake works on a version of the campaign. Create or open one in Creative Studio first." />;
  }

  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]">
      <form
        className="space-y-4 self-start rounded-card border border-border bg-surface p-4 shadow-card"
        onSubmit={(e) => { e.preventDefault(); submit(); }}
        aria-label="Remake: Visuals setup"
      >
        <Field label="Version" htmlFor="rv-version" required>
          <select id="rv-version" className={SELECT} value={version?.id ?? ""} onChange={(e) => { setVersionId(e.target.value); setPlateId(null); }}>
            {[...versions].reverse().map((v) => (
              <option key={v.id} value={v.id}>
                {v.label} · {v.region_code ?? "no region"} · {v.language ?? "no language"}
              </option>
            ))}
          </select>
        </Field>
        <p className="type-ledger text-[12.5px] text-ink-muted">
          Target <span className="text-ink-body">{version?.region_code ?? "none"}</span> in <span className="text-ink-body">{version?.language ?? "none"}</span>, taken from the version.
        </p>

        <Field label="Scene to replace" htmlFor="rv-scene" required>
          <select id="rv-scene" className={SELECT} value={plan?.plate?.id ?? ""} onChange={(e) => setPlateId(e.target.value)} disabled={!detail.data}>
            {(detail.data?.elements ?? []).filter((e) => e.kind === "scene" && !isVideoClip(e)).map((e) => (
              <option key={e.id} value={e.id}>
                {e.id}{locks.data?.has(e.id) ? " (locked)" : ""}
              </option>
            ))}
          </select>
        </Field>

        <Field label="Finished creative" htmlFor="rv-original" required={!demo} hint={demo ? "Left empty, the key visual is used." : "Locked regions are restored from this image."}>
          <select id="rv-original" className={SELECT} value={original} onChange={(e) => setOriginalId(e.target.value)}>
            <option value="">{demo ? "Key visual" : "Choose an image"}</option>
            {(images.data ?? []).map((a) => <option key={a.id} value={a.id}>{a.filename}</option>)}
          </select>
        </Field>
        <Field label="Clean plate" htmlFor="rv-plate" hint="The same image without text or product.">
          <select id="rv-plate" className={SELECT} value={plateAsset} onChange={(e) => setPlateAssetId(e.target.value)}>
            <option value="">None</option>
            {(images.data ?? []).map((a) => <option key={a.id} value={a.id}>{a.filename}</option>)}
          </select>
        </Field>
        <Field label="Product reference" htmlFor="rv-reference">
          <select id="rv-reference" className={SELECT} value={reference} onChange={(e) => setReferenceId(e.target.value)}>
            <option value="">None</option>
            {(images.data ?? []).map((a) => <option key={a.id} value={a.id}>{a.filename}</option>)}
          </select>
        </Field>
        <Field label="Art direction" htmlFor="rv-direction" hint="Your words, passed to the model as yours.">
          <Textarea id="rv-direction" rows={3} maxLength={400} value={direction} onChange={(e) => setDirection(e.target.value)} />
        </Field>

        {plan && plan.plate && (
          <div className="space-y-2 rounded-lg border border-border bg-surface-muted/60 px-3 py-2.5 text-[13px]">
            <p className="text-ink-body">
              Keeps <span className="font-medium text-ink">{plan.locked.length}</span> locked {plan.locked.length === 1 ? "region" : "regions"} exactly as they are,
              draws <span className="font-medium text-ink">{plan.texts.length}</span> text {plan.texts.length === 1 ? "element" : "elements"} in code.
            </p>
            {plan.locked.length > 0 && (
              <ul className="flex flex-wrap gap-1.5">
                {plan.locked.map((l) => <li key={l.element.id}><LockChip>{l.element.kind}</LockChip></li>)}
              </ul>
            )}
          </div>
        )}

        {imageOff && <Notice>No image model is configured on this server, so Remake: Visuals cannot run here.</Notice>}
        {blockedReason && !imageOff && <Notice tone="info">{blockedReason}</Notice>}
        <CostConfirm demo={demo} estimate={caps.image.estimated_cost_usd} what="one image generation" checked={confirmed} onChange={setConfirmed} />
        <Button type="submit" disabled={!canRun} className="w-full">
          {working ? "Working…" : demo ? "Show the remake" : "Generate regional scene"}
        </Button>
        {start.error && <ErrorState error={start.error} />}
      </form>

      <div className="min-w-0 space-y-4">
        {runId && <RunProgress run={run.data} onRetry={submit} />}
        {shown ? (
          <VisualResult output={shown} />
        ) : runId && working ? (
          <LoadingState label="Making the regional scene…" />
        ) : !runId ? (
          <EmptyState title="No visual remake yet" description="Choose a version and run it. The scene, the locked regions and the code-rendered text appear here side by side." />
        ) : null}
        {visuals.length > 1 && <History items={visuals} current={shown?.id} onPick={(id) => { setRunId(null); setViewId(id); }} />}
      </div>
    </div>
  );
}

function History({ items, current, onPick }: { items: RemakeOutput[]; current?: string; onPick: (id: string) => void }) {
  return (
    <section aria-label="Earlier visual remakes" className="space-y-1.5">
      <h3 className="text-[13px] font-semibold text-ink-secondary">Earlier remakes</h3>
      <ul className="divide-y divide-border rounded-card border border-border bg-surface">
        {items.map((o) => (
          <li key={o.id}>
            <button
              type="button"
              onClick={() => onPick(o.id)}
              aria-current={o.id === current ? "true" : undefined}
              className={cn("flex w-full items-center justify-between gap-3 px-3.5 py-2 text-left text-[13px] hover:bg-surface-muted", o.id === current && "bg-surface-muted")}
            >
              <span className="text-ink-body">{o.region_code} · {o.language} · {formatDate(o.created_at)}</span>
              <span className="type-meta">{o.passed ? "checks passed" : "checks flagged"} · {usd(o.estimated_cost_usd)}</span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** Source, generated scene and finished creative side by side, then every code check. */
function VisualResult({ output }: { output: RemakeOutput }) {
  const v = output.visual;
  const [outlines, setOutlines] = useState(false);
  if (!v) return <Notice>This remake has no visual result.</Notice>;
  const flagged = v.texts.filter((t) => !t.passed);
  return (
    <section aria-label="Visual remake result" className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
        <h2 className="flex items-center gap-2 text-[17px] font-semibold text-ink">Regional scene <AiTag /></h2>
      </div>

      {v.original_url && (
        <div className="max-w-md space-y-1.5">
          <p className="type-meta">Drag, or use the arrow keys on the handle, to compare the source with the finished creative.</p>
          <CompareSlider
            beforeLabel="Source creative"
            afterLabel="Finished creative"
            before={<AuthImage url={v.original_url} alt="The source creative" className="rounded-none border-0" />}
            after={<AuthImage url={v.output_url} alt="The finished creative: generated scene, locked regions and text rendered in code" className="rounded-none border-0" />}
          />
        </div>
      )}

      <div className={cn("grid gap-3", v.original_url ? "sm:grid-cols-3" : "sm:grid-cols-2")}>
        {v.original_url && <Figure label="Source creative"><AuthImage url={v.original_url} alt="The source creative" /></Figure>}
        <Figure label="Generated scene"><AuthImage url={v.plate_url} alt="The generated regional scene, without text" /></Figure>
        <Figure
          label="Finished creative"
          action={<button type="button" aria-pressed={outlines} onClick={() => setOutlines((o) => !o)} className="text-[12px] font-medium text-primary underline underline-offset-2">{outlines ? "Hide" : "Show"} locked regions</button>}
        >
          <AuthImage url={v.output_url} alt="The finished creative: generated scene, locked regions and text rendered in code">
            {outlines && v.locked_regions.map((r) => (
              <span
                key={r.element_id}
                aria-hidden
                className="pointer-events-none absolute border-2 border-dashed border-primary"
                style={{ left: `${r.bbox[0] * 100}%`, top: `${r.bbox[1] * 100}%`, width: `${r.bbox[2] * 100}%`, height: `${r.bbox[3] * 100}%` }}
              />
            ))}
          </AuthImage>
        </Figure>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <section aria-label="Locked regions" className="rounded-card border border-border bg-surface">
          <h3 className="border-b border-border px-3.5 py-2.5 text-[13.5px] font-semibold text-ink">Locked regions</h3>
          <ul className="divide-y divide-border">
            {v.locked_regions.length === 0 && <li className="px-3.5 py-2.5 text-[13px] text-ink-muted">This scene has no locked region.</li>}
            {v.locked_regions.map((r) => (
              <li key={r.element_id} className="flex items-center justify-between gap-3 px-3.5 py-2 text-[13px]">
                <span className="min-w-0">
                  <span className="text-ink">{r.kind}</span> <span className="type-meta">{r.element_id}</span>
                  <span className="block type-meta">{LOCK_SOURCE[r.source]}</span>
                </span>
                <span className={cn("inline-flex shrink-0 items-center gap-1 text-[12.5px]", r.identical ? "text-success" : "text-danger")}>
                  <Check aria-hidden className="size-3.5" />
                  {r.identical ? "Identical to the original" : "Differs"}
                </span>
              </li>
            ))}
          </ul>
        </section>

        <section aria-label="Text rendered in code" className="rounded-card border border-border bg-surface">
          <h3 className="border-b border-border px-3.5 py-2.5 text-[13.5px] font-semibold text-ink">
            Text rendered in code <span className="type-meta font-normal">{v.shaping_engine === "raqm" ? "shaped with HarfBuzz" : "unshaped"}</span>
          </h3>
          <ul className="divide-y divide-border">
            {v.texts.length === 0 && <li className="px-3.5 py-2.5 text-[13px] text-ink-muted">No text element in this scene.</li>}
            {v.texts.map((t) => (
              <li key={t.element_id} className="space-y-0.5 px-3.5 py-2">
                <p lang={t.language ?? undefined} className="text-[14px] text-ink">{t.text}</p>
                <p className="type-meta flex flex-wrap gap-x-3">
                  <span>{t.element_id}</span>
                  <span>{t.font_size}px</span>
                  <span>{t.fits ? "fits" : "clipped"}</span>
                  <span>contrast {t.contrast_ratio}:1</span>
                  <span>{t.script_ok ? "script ok" : "wrong script"}</span>
                </p>
                {t.problems.map((p) => (
                  <p key={p} className="flex items-start gap-1.5 text-[12.5px] text-warning"><TriangleAlert aria-hidden className="mt-0.5 size-3.5 shrink-0" />{p}</p>
                ))}
              </li>
            ))}
          </ul>
        </section>
      </div>

      {flagged.length > 0 && <Notice>{flagged.length} of {v.texts.length} text elements were flagged. The version was still created; fix the text or its box in Creative Studio and remake.</Notice>}

      <details className="rounded-card border border-border bg-surface px-3.5 py-2.5 text-[13px] text-ink-body">
        <summary className="cursor-pointer font-medium text-ink">Prompt and provenance</summary>
        <dl className="mt-2.5 grid gap-1.5 sm:grid-cols-[9rem_minmax(0,1fr)]">
          <dt className="type-meta">Prompt version</dt><dd className="font-mono text-[12.5px]">{v.prompt_version}</dd>
          <dt className="type-meta">Version created</dt><dd className="font-mono text-[12.5px]">{output.result_version_id}</dd>
          <dt className="type-meta">Run</dt><dd className="font-mono text-[12.5px]">{output.run_id ?? "none"}</dd>
          {v.direction && (<><dt className="type-meta">Art direction</dt><dd>{v.direction}</dd></>)}
          {v.prompt && (<><dt className="type-meta">Sent to the model</dt><dd className="whitespace-pre-wrap">{v.prompt}</dd></>)}
          {output.limitations.length > 0 && (<><dt className="type-meta">Notes</dt><dd><ul className="list-disc space-y-1 pl-4">{output.limitations.map((n) => <li key={n}>{n}</li>)}</ul></dd></>)}
        </dl>
      </details>
    </section>
  );
}

function Figure({ label, action, children }: { label: string; action?: React.ReactNode; children: React.ReactNode }) {
  return (
    <figure className="min-w-0 space-y-1.5">
      <div className="flex items-baseline justify-between gap-2">
        <figcaption className="text-[12.5px] font-medium text-ink-secondary">{label}</figcaption>
        {action}
      </div>
      {children}
    </figure>
  );
}
