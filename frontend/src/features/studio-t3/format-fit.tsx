"use client";

import { Clapperboard, Copy, Crop, ImageDown, Lock, Scissors } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button, buttonVariants } from "@/components/ui/button";
import { MutationError } from "@/features/studio/parts";
import type { VersionNode } from "@/features/studio/types";
import { FrameStage, type StageBox } from "@/features/xray/frame-stage";
import { useBlob, useCreatives, useObjectUrl } from "@/features/xray/api";
import { clock } from "@/features/xray/parts";
import { cn } from "@/lib/utils";

import { useApplyFormat, useFormatCatalogue, useFormatOutputs, useFormatPlans } from "./api";
import { plural, ToneTag } from "./parts";
import type { FitStrategy, FormatFitCutdown, FormatFitFormat, FormatFitIssue, FormatFitOutput, FormatFitPlans, FormatFitStrategyPlan } from "./types";

const STRATEGY_LABEL: Record<FitStrategy, { name: string; text: string }> = {
  crop: { name: "Crop", text: "Cut the picture to the frame. Anything outside it is lost." },
  pad: { name: "Pad", text: "Keep the whole picture and fill the rest of the frame with bars." },
  native: { name: "As it is", text: "The picture already has this ratio." },
};
const VERDICT: Record<FormatFitStrategyPlan["verdict"], { tone: "ok" | "review" | "problem"; label: string }> = {
  clean: { tone: "ok", label: "Fits cleanly" },
  review: { tone: "review", label: "Fits, with things to look at" },
  conflict: { tone: "problem", label: "Conflicts" },
};

const contentPath = (assetId: string) => `/api/v1/assets/${assetId}/content`;
const pct = (n: number) => `${(n * 100).toFixed(3)}%`;

// ---------- the preview ----------

/** The output frame as the plan makes it: the picture placed in it, the safe zone, and every element box coloured by what happens to it. */
function OutputFrame({ strategy, format, source, assetId }: { strategy: FormatFitStrategyPlan; format: FormatFitFormat; source: FormatFitPlans["source"]; assetId: string }) {
  const blob = useBlob(contentPath(assetId));
  const url = useObjectUrl(blob.data);
  const { window: w, place: p, scale: k } = strategy;
  const sw = source.width ?? w.width;
  const sh = source.height ?? w.height;
  const fw = format.width;
  const fh = format.height;
  const z = format.safe_zone;
  const maxH = "min(34rem, 62dvh)";
  return (
    <div className="space-y-1.5">
      <div
        role="img"
        aria-label={`Preview of the ${format.ratio} output, ${strategy.strategy}`}
        className="clay-well relative mx-auto overflow-hidden rounded-xl"
        style={{ aspectRatio: `${fw} / ${fh}`, width: `calc(${maxH} * ${fw / fh})`, maxWidth: "100%", background: strategy.background ?? "#202020" }}
      >
        {url && (
          // eslint-disable-next-line @next/next/no-img-element -- authenticated blob
          <img
            src={url}
            alt=""
            draggable={false}
            className="absolute max-w-none select-none"
            style={{ left: pct((p.x - w.x * k) / fw), top: pct((p.y - w.y * k) / fh), width: pct((sw * k) / fw), height: pct((sh * k) / fh) }}
          />
        )}
        <div
          aria-hidden
          className="pointer-events-none absolute border border-dashed border-white/80 shadow-[0_0_0_1px_rgb(0_0_0/0.5)]"
          style={{ left: pct(z.left), top: pct(z.top), right: pct(z.right), bottom: pct(z.bottom) }}
        />
        {strategy.elements.map((e) =>
          e.bbox_output ? (
            <div
              key={e.element_id}
              title={`${e.element_id}: ${e.placement}${e.in_safe_zone === false ? ", outside the safe zone" : ""}`}
              className={cn(
                "pointer-events-none absolute border-2 shadow-[0_0_0_1px_rgb(0_0_0/0.5)]",
                e.placement !== "kept" ? "border-dashed border-danger" : e.in_safe_zone === false ? "border-warning" : e.locked ? "border-dashed border-white" : "border-primary",
              )}
              style={{ left: pct(e.bbox_output[0]), top: pct(e.bbox_output[1]), width: pct(e.bbox_output[2]), height: pct(e.bbox_output[3]) }}
            />
          ) : null,
        )}
        {!url && (
          <div role="status" className="absolute inset-0 grid place-items-center px-3 text-center text-[13px] text-white/80">
            {blob.isError ? "The picture could not be loaded." : "Loading the picture…"}
          </div>
        )}
      </div>
      <p className="type-meta text-center">
        {fw} x {fh} px · dashed line: working safe zone · boxes: dashed white locked, amber outside the safe zone, red cut
      </p>
    </div>
  );
}

// ---------- issues and elements ----------

const SEVERITY_ORDER = { conflict: 0, review: 1, info: 2 } as const;

function Issues({ issues }: { issues: FormatFitIssue[] }) {
  if (issues.length === 0) return <p className="text-[13.5px] text-ink-body">Nothing to report for this plan.</p>;
  return (
    <ul aria-label="What this plan does" className="space-y-1.5">
      {[...issues]
        .sort((a, b) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity])
        .map((i, n) => (
          <li key={n} className="flex items-baseline gap-2.5 text-[13px]">
            <ToneTag tone={i.severity === "conflict" ? "problem" : i.severity === "review" ? "review" : "info"} label={i.severity === "conflict" ? "Conflict" : i.severity === "review" ? "Review" : "Note"} className="shrink-0" />
            <span className="text-ink-body">{i.message}</span>
          </li>
        ))}
    </ul>
  );
}

function ElementTable({ strategy }: { strategy: FormatFitStrategyPlan }) {
  return (
    <details className="text-[13px]">
      <summary className="cursor-pointer font-medium text-ink-body select-none hover:text-ink">Every element ({strategy.elements.length})</summary>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full min-w-[34rem] text-left text-[12.5px]">
          <thead className="text-ink-secondary">
            <tr>
              <th className="py-1 pr-3 font-medium">Element</th>
              <th className="py-1 pr-3 font-medium">In the frame</th>
              <th className="py-1 pr-3 font-medium">Safe zone</th>
              <th className="py-1 font-medium">Text height</th>
            </tr>
          </thead>
          <tbody className="ledger-rules text-ink-body">
            {strategy.elements.map((e) => (
              <tr key={e.element_id}>
                <td className="py-1 pr-3 font-mono text-[11.5px]">
                  {e.locked && <Lock aria-label="Locked" className="mr-1 inline size-3" />}
                  {e.element_id}
                </td>
                <td className="py-1 pr-3">{e.placement === "unknown" ? "No position" : e.placement === "kept" ? "Whole" : `${Math.round(e.visible_share * 100)}% visible`}</td>
                <td className="py-1 pr-3">{e.in_safe_zone == null ? "n/a" : e.in_safe_zone ? "Inside" : `Reaches ${e.safe_overflow.join(", ")}`}</td>
                <td className="py-1">{e.text_height_px == null ? "n/a" : `${Math.round(e.text_height_px)} px (min ${Math.round(e.min_text_px ?? 0)})`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

// ---------- applying ----------

function ApplyBar({ campaignId, versionId, creativeId, format, strategy }: { campaignId: string; versionId: string; creativeId: string; format: FormatFitFormat; strategy: FormatFitStrategyPlan }) {
  const apply = useApplyFormat(campaignId);
  const [ack, setAck] = useState(false);
  const needsAck = strategy.issues.some((i) => i.severity === "conflict");
  return (
    <div className="space-y-2 border-t border-border pt-3">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <Button
          type="button"
          disabled={!strategy.applicable || apply.isPending || (needsAck && !ack)}
          onClick={() =>
            apply.mutate(
              { creativeId, versionId, formatId: format.id, strategy: strategy.strategy, background: strategy.strategy === "pad" ? strategy.background : null, acknowledge: ack },
              { onSuccess: (o) => toast.success(`Saved as a new asset: ${o.asset.filename}`) },
            )
          }
        >
          <ImageDown aria-hidden />
          {apply.isPending ? "Making the picture…" : `Make the ${format.ratio} picture`}
        </Button>
        {needsAck && strategy.applicable && (
          <label className="inline-flex cursor-pointer items-center gap-2 text-[13px] text-ink-body">
            <input type="checkbox" className="size-4" checked={ack} onChange={(e) => setAck(e.target.checked)} />I accept that text is cut in this plan
          </label>
        )}
      </div>
      {!strategy.applicable && <p className="text-[13px] text-danger">This plan would cut a locked element, so it cannot be made. Choose another plan, or unlock the element first.</p>}
      <p className="type-meta">Nothing is changed until you press the button. The picture is saved as a new asset; the original is never touched.</p>
      {apply.isError && <MutationError error={apply.error} />}
    </div>
  );
}

function Outputs({ campaignId, creativeId }: { campaignId: string; creativeId: string }) {
  const outputs = useFormatOutputs(campaignId);
  const mine = (outputs.data?.items ?? []).filter((o) => o.creative_id === creativeId);
  if (outputs.isPending || mine.length === 0) return null;
  return (
    <section aria-label="Pictures made by Format Fit" className="space-y-2">
      <h3 className="text-[14px] font-semibold text-ink">Made from this creative</h3>
      <ul className="ledger-rules overflow-hidden rounded-card border border-border bg-surface">
        {mine.map((o) => (
          <OutputRow key={o.id} output={o} />
        ))}
      </ul>
    </section>
  );
}

function OutputRow({ output }: { output: FormatFitOutput }) {
  const blob = useBlob(contentPath(output.asset.id));
  const url = useObjectUrl(blob.data);
  return (
    <li className="flex items-center gap-3 px-3 py-2.5">
      <span className="clay-well grid size-12 shrink-0 place-items-center overflow-hidden rounded-md">
        {url ? (
          // eslint-disable-next-line @next/next/no-img-element -- authenticated blob
          <img src={url} alt="" className="size-full object-cover" />
        ) : null}
      </span>
      <div className="min-w-0 flex-1">
        <p className="truncate text-[13.5px] font-medium text-ink">{output.asset.filename}</p>
        <p className="type-ledger text-[12px] text-ink-secondary">
          {output.format_id.replace("x", ":")} · {STRATEGY_LABEL[output.strategy].name.toLowerCase()} · {VERDICT[output.verdict].label.toLowerCase()}
        </p>
      </div>
      {url && (
        <a href={url} download={output.asset.filename} className={buttonVariants({ variant: "outline", size: "sm" })}>
          Download
        </a>
      )}
    </li>
  );
}

// ---------- picture creatives ----------

function PictureFit({ campaignId, version, creativeId, plans }: { campaignId: string; version: VersionNode; creativeId: string; plans: FormatFitPlans }) {
  const catalogue = useFormatCatalogue(campaignId);
  const [formatId, setFormatId] = useState<string>(() => plans.plans.find((p) => p.format.id === "9x16")?.format.id ?? plans.plans[0]?.format.id ?? "");
  const plan = plans.plans.find((p) => p.format.id === formatId) ?? plans.plans[0];
  const [chosen, setChosen] = useState<FitStrategy | null>(null);
  const strategy = plan?.strategies.find((s) => s.strategy === (chosen ?? plan.recommended)) ?? plan?.strategies[0];
  const channelsOf = (f: FormatFitFormat) => (catalogue.data?.channels ?? []).filter((c) => c.format_id === f.id).map((c) => c.name);
  const srcBoxes: StageBox[] = useMemo(() => {
    if (!strategy) return [];
    const boxes: StageBox[] = strategy.elements
      .filter((e) => e.bbox_source)
      .map((e) => ({ id: e.element_id, bbox: e.bbox_source!, label: e.element_id, tone: e.locked ? "locked" : e.text != null ? "text" : "anchor" }));
    const sw = plans.source.width ?? 1;
    const sh = plans.source.height ?? 1;
    if (strategy.strategy === "crop") boxes.push({ id: "window", bbox: [strategy.window.x / sw, strategy.window.y / sh, strategy.window.width / sw, strategy.window.height / sh], label: "Crop window", tone: "anchor", active: true });
    return boxes;
  }, [strategy, plans.source]);
  if (!plan || !strategy) return <EmptyState title="No format to plan for" description="The format list is empty." />;
  const format = plan.format;
  const verdict = VERDICT[strategy.verdict];
  return (
    <div className="space-y-5">
      <nav aria-label="Formats">
        <ul className="flex flex-wrap gap-2">
          {plans.plans.map((p) => {
            const f = p.format;
            const rec = p.strategies.find((s) => s.strategy === p.recommended) ?? p.strategies[0];
            const selected = f.id === formatId;
            const channels = channelsOf(f);
            return (
              <li key={f.id}>
                <button
                  type="button"
                  aria-current={selected ? "true" : undefined}
                  onClick={() => { setFormatId(f.id); setChosen(null); }}
                  className={cn("clay flex min-w-[10.5rem] flex-col items-start gap-0.5 rounded-xl border px-3 py-2 text-left", selected ? "border-primary" : "border-border hover:border-border-strong")}
                >
                  <span className="text-[14px] font-semibold text-ink">
                    {f.ratio} <span className="font-normal text-ink-secondary">{f.name}</span>
                  </span>
                  <span className="type-ledger text-[11.5px] text-ink-secondary">{channels.length ? channels.join(", ") : f.used_for}</span>
                  <ToneTag tone={VERDICT[rec.verdict].tone} label={VERDICT[rec.verdict].label} className="text-[11.5px]" />
                </button>
              </li>
            );
          })}
        </ul>
      </nav>

      <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
        <div role="radiogroup" aria-label="How to fit" className="inline-flex gap-1.5">
          {plan.strategies.map((s) => (
            <Button key={s.strategy} type="button" size="sm" role="radio" aria-checked={s.strategy === strategy.strategy} variant={s.strategy === strategy.strategy ? "default" : "outline"} title={STRATEGY_LABEL[s.strategy].text} onClick={() => setChosen(s.strategy)}>
              {s.strategy === "crop" ? <Crop aria-hidden /> : null}
              {STRATEGY_LABEL[s.strategy].name}
              {s.strategy === plan.recommended && plan.strategies.length > 1 ? " (suggested)" : ""}
            </Button>
          ))}
        </div>
        <ToneTag tone={verdict.tone} label={verdict.label} />
        <span className="type-ledger text-[12.5px] text-ink-secondary">
          {Math.round(strategy.retained_share * 100)}% of the picture shown · scale {strategy.scale.toFixed(2)}
        </span>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <figure className="min-w-0 space-y-1.5">
          <figcaption className="text-[12.5px] font-medium text-ink-secondary">The original ({plans.source.width} x {plans.source.height} px)</figcaption>
          <FrameStage path={contentPath(plans.source.asset_id)} aspect={plans.source.width && plans.source.height ? plans.source.width / plans.source.height : null} boxes={srcBoxes} alt="The original picture with the elements and the crop window marked" />
        </figure>
        <figure className="min-w-0 space-y-1.5">
          <figcaption className="text-[12.5px] font-medium text-ink-secondary">Output for {format.ratio}</figcaption>
          <OutputFrame strategy={strategy} format={format} source={plans.source} assetId={plans.source.asset_id} />
        </figure>
      </div>

      <div className="space-y-3">
        <Issues issues={strategy.issues} />
        <ElementTable strategy={strategy} />
        <ApplyBar key={`${format.id}-${strategy.strategy}`} campaignId={campaignId} versionId={version.id} creativeId={creativeId} format={format} strategy={strategy} />
      </div>
      <p className="type-meta">Source: planned in code ({plans.tool_version}) from the picture and the boxes of this version. Safe zones are working defaults; check the platform&apos;s current guidance.</p>
    </div>
  );
}

// ---------- video creatives ----------

function copyEditList(c: FormatFitCutdown) {
  const lines = c.segments.map((s, i) => `${i + 1}. ${clock(s.start_ms)} to ${clock(s.end_ms)}${s.trimmed ? " (shortened)" : ""}`);
  void navigator.clipboard
    ?.writeText(`Cut-down to ${clock(c.target_ms)} (${clock(c.duration_ms)} used)\n${lines.join("\n")}`)
    .then(() => toast.success("Edit list copied"))
    .catch(() => toast.error("The edit list could not be copied"));
}

function Cutdowns({ plans }: { plans: FormatFitPlans }) {
  const native = plans.plans[0];
  const strategy = native?.strategies[0];
  return (
    <div className="space-y-5">
      {strategy && (
        <section aria-label="This video in its own format" className="space-y-2">
          <h3 className="text-[14px] font-semibold text-ink">
            In its own format ({native.format.ratio}) <ToneTag tone={VERDICT[strategy.verdict].tone} label={VERDICT[strategy.verdict].label} className="ml-2 align-middle" />
          </h3>
          <Issues issues={strategy.issues} />
        </section>
      )}
      <section aria-label="Cut-down suggestions" className="space-y-3">
        <h3 className="flex items-center gap-2 text-[14px] font-semibold text-ink">
          <Scissors aria-hidden className="size-4" />
          Cut-down suggestions from the scene timings
        </h3>
        {plans.cutdowns.length === 0 ? (
          <p className="text-[13.5px] text-ink-secondary">This video has no scene timings yet, or is too short to cut down. Run Creative X-Ray on it first.</p>
        ) : (
          <div className="grid gap-4 xl:grid-cols-3">
            {plans.cutdowns.map((c) => (
              <article key={c.target_ms} className="clay space-y-2.5 rounded-card border border-border p-3.5">
                <header className="flex items-baseline justify-between gap-3">
                  <h4 className="text-[14px] font-semibold text-ink">{c.target_ms / 1000} second version</h4>
                  <span className="type-ledger text-[12px] text-ink-secondary">{clock(c.duration_ms)} used</span>
                </header>
                <ol className="space-y-2">
                  {c.segments.map((s) => (
                    <li key={s.scene_id} className="text-[13px]">
                      <p className="font-medium text-ink">
                        Scene {s.position}: <span className="type-ledger font-normal">{clock(s.start_ms)} to {clock(s.end_ms)}</span>
                        {s.trimmed && <span className="ml-1.5 text-warning">shortened</span>}
                      </p>
                      <p className="text-[12.5px] text-ink-secondary">{s.reasons.join(" · ")}</p>
                    </li>
                  ))}
                </ol>
                {c.dropped.length > 0 && <p className="type-meta">Dropped: {c.dropped.map((d) => `scene ${d.position} (${clock(d.duration_ms)})`).join(", ")}.</p>}
                {c.notes.map((n) => (
                  <p key={n} className="text-[12.5px] text-warning">
                    {n}
                  </p>
                ))}
                <Button type="button" size="sm" variant="outline" onClick={() => copyEditList(c)}>
                  <Copy aria-hidden />
                  Copy edit list
                </Button>
              </article>
            ))}
          </div>
        )}
      </section>
      <p className="type-meta">Source: scene timings from Creative X-Ray, scored in code ({plans.tool_version}). Suggestions only: no video is rendered.</p>
    </div>
  );
}

// ---------- the panel ----------

/**
 * Format Fit: how the creative sits in each channel format (1:1, 4:5, 9:16, 16:9). Pictures get a crop and a pad plan with
 * the safe zone, text size and locked-region conflicts reported per element; videos get cut-down suggestions from the
 * X-Ray scene timings. Planning changes nothing; a picture is made only when you press the button, as a new asset.
 */
export function FormatFitPanel({ campaignId, version }: { campaignId: string; version: VersionNode }) {
  const creatives = useCreatives(campaignId);
  const usable = useMemo(() => (creatives.data ?? []).filter((c) => c.kind !== "audio"), [creatives.data]);
  const [picked, setPicked] = useState<string | null>(null);
  const creative = usable.find((c) => c.id === picked) ?? usable.find((c) => c.kind === "image") ?? usable[0] ?? null;
  const plans = useFormatPlans(campaignId, creative?.id ?? null, version.id);

  if (creatives.isPending) return <LoadingState label="Loading the campaign's creatives…" />;
  if (creatives.isError) return <ErrorState error={creatives.error} onRetry={() => void creatives.refetch()} />;
  if (!creative) {
    return (
      <EmptyState
        title="No picture or video to fit yet"
        description="Format Fit plans a creative for each channel format. Upload an image or a video and run Creative X-Ray on it first."
        needs={[{ label: "An uploaded image or video registered as a creative", met: false }]}
        action={
          <Link href={`/app/c/${campaignId}/studio/xray`} className={buttonVariants({ variant: "outline" })}>
            <Clapperboard aria-hidden />
            Open Creative X-Ray
          </Link>
        }
      />
    );
  }
  return (
    <div className="space-y-5">
      {usable.length > 1 && (
        <nav aria-label="Creatives of this campaign">
          <ul className="flex flex-wrap gap-2">
            {usable.map((c) => (
              <li key={c.id}>
                <Button type="button" size="sm" variant={c.id === creative.id ? "default" : "outline"} aria-pressed={c.id === creative.id} onClick={() => setPicked(c.id)}>
                  {c.label}
                </Button>
              </li>
            ))}
          </ul>
        </nav>
      )}
      {plans.isPending && <LoadingState label="Planning the formats…" />}
      {plans.isError && <ErrorState error={plans.error} onRetry={() => void plans.refetch()} />}
      {plans.data && (creative.kind === "video" ? <Cutdowns plans={plans.data} /> : <PictureFit key={creative.id} campaignId={campaignId} version={version} creativeId={creative.id} plans={plans.data} />)}
      {plans.data && creative.kind === "image" && <Outputs campaignId={campaignId} creativeId={creative.id} />}
      {plans.data && plans.data.notes.length > 0 && creative.kind === "video" && <p className="type-meta">{plans.data.notes.join(" ")}</p>}
      {plans.data && <p className="sr-only">{plural(plans.data.plans.length, "format")} planned.</p>}
    </div>
  );
}
