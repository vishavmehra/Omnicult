"use client";

import { CircleAlert, CircleCheck, FileUp, Film, ImageIcon, LoaderCircle, Music, Play, RotateCw, Upload, X, type LucideIcon } from "lucide-react";
import { useId, useRef, useState, type DragEvent } from "react";

import { ErrorState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Field } from "@/components/forms/fields";
import { formatBytes } from "@/features/assets/asset-uploader";
import { cn } from "@/lib/utils";

import { useAssetStatus, useMediaCapabilities, useObjectUrl, useRegions, useStartXRay, useUploadAsset, type Asset, type AssetKind } from "./api";
import { LANGUAGES } from "./languages";
import { MEDIA_ACCEPT, SIDECAR_ACCEPT, SIDECAR_MAX_BYTES, readDuration, sniff } from "./media-file";
import { NativeSelect } from "./native-select";
import { clock } from "./parts";

export const KIND_ICON: Record<AssetKind, LucideIcon> = { image: ImageIcon, video: Film, audio: Music };
export const KIND_LABEL: Record<AssetKind, string> = { image: "Image", video: "Video", audio: "Audio" };

const FALLBACK_LIMITS = { max_image_bytes: 5 * 1024 * 1024, max_media_bytes: 50 * 1024 * 1024, max_media_seconds: 60 };

type Picked = { file: File; kind: AssetKind; format: string; durationMs: number | null };

/** Step one: choose a file, say you hold the rights, optionally add your own transcript or notes, and upload. */
export function UploadForm({ projectId, onUploaded }: { projectId: string; onUploaded: (asset: Asset) => void }) {
  const id = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const caps = useMediaCapabilities();
  const upload = useUploadAsset(projectId);
  const limits = caps.data?.limits ?? FALLBACK_LIMITS;
  const [picked, setPicked] = useState<Picked | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [sidecar, setSidecar] = useState<File | null>(null);
  const [sidecarProblem, setSidecarProblem] = useState<string | null>(null);
  const [rights, setRights] = useState(false);
  const [dragging, setDragging] = useState(false);
  const preview = useObjectUrl(picked?.kind === "image" ? picked.file : null);

  async function choose(next: File | undefined) {
    upload.reset();
    setProblem(null);
    setPicked(null);
    setSidecar(null);
    setSidecarProblem(null);
    if (!next) return;
    if (next.size === 0) return setProblem("The file is empty.");
    const found = await sniff(next, next.name);
    if (!found) return setProblem("This is not a PNG, JPEG, WebP, MP4, MOV, WebM, MP3, WAV or M4A file. Renaming a file does not change its format.");
    const max = found.kind === "image" ? limits.max_image_bytes : limits.max_media_bytes;
    if (next.size > max) return setProblem(`The ${found.kind} is ${formatBytes(next.size)}; the limit is ${formatBytes(max)}.`);
    if (found.kind !== "image" && caps.data && !caps.data.ffmpeg.available) {
      return setProblem(`Video and audio need ffmpeg, which this server does not have.${caps.data.ffmpeg.message ? ` ${caps.data.ffmpeg.message}` : ""}`);
    }
    const durationMs = await readDuration(next, found.kind);
    if (durationMs != null && durationMs > limits.max_media_seconds * 1000) {
      return setProblem(`The ${found.kind} runs ${clock(durationMs)}; the limit is ${limits.max_media_seconds} seconds.`);
    }
    setPicked({ file: next, ...found, durationMs });
  }

  function chooseSidecar(next: File | undefined) {
    setSidecarProblem(null);
    setSidecar(null);
    if (!next) return;
    if (next.size > SIDECAR_MAX_BYTES) return setSidecarProblem(`The sidecar is ${formatBytes(next.size)}; the limit is ${formatBytes(SIDECAR_MAX_BYTES)}.`);
    setSidecar(next);
  }

  function clear() {
    setPicked(null);
    setProblem(null);
    setSidecar(null);
    setRights(false);
    upload.reset();
    if (inputRef.current) inputRef.current.value = "";
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setDragging(false);
    void choose(e.dataTransfer.files[0]);
  }

  const isMedia = picked && picked.kind !== "image";
  const Icon = picked ? KIND_ICON[picked.kind] : FileUp;

  return (
    <form
      className="space-y-4"
      onSubmit={(e) => {
        e.preventDefault();
        if (picked && rights) upload.mutate({ file: picked.file, kind: picked.kind, rightsConfirmed: rights, sidecar: isMedia ? sidecar : null }, { onSuccess: onUploaded });
      }}
    >
      <input ref={inputRef} id={`${id}-file`} type="file" accept={MEDIA_ACCEPT} className="sr-only" tabIndex={-1} onChange={(e) => void choose(e.target.files?.[0])} />

      {!picked ? (
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          aria-describedby={`${id}-rules`}
          className={cn(
            "flex w-full flex-col items-center gap-2 rounded-card border border-dashed border-border-strong/60 bg-surface-muted/50 px-4 py-7 text-center transition-colors hover:bg-surface-muted",
            dragging && "border-primary bg-surface-muted",
          )}
        >
          <FileUp aria-hidden className="size-6 text-ink-secondary" />
          <span className="text-[14px] font-medium text-ink">Choose an image, video or audio file, or drop it here</span>
          <span id={`${id}-rules`} className="max-w-[52ch] text-[12.5px] text-ink-secondary">
            Image: PNG, JPEG or WebP, up to {formatBytes(limits.max_image_bytes)}. Video: MP4, MOV or WebM. Audio: MP3, WAV or M4A. Video and audio up to{" "}
            {formatBytes(limits.max_media_bytes)} and {limits.max_media_seconds} seconds.
          </span>
        </button>
      ) : (
        <div className="flex items-start gap-3 rounded-card border border-border bg-surface-muted/50 p-3">
          {preview ? (
            // eslint-disable-next-line @next/next/no-img-element -- local object URL preview
            <img src={preview} alt={`Preview of ${picked.file.name}`} className="h-20 w-20 shrink-0 rounded-lg border border-border object-cover" />
          ) : (
            <span className="clay-well grid size-20 shrink-0 place-items-center rounded-lg">
              <Icon aria-hidden className="size-7 text-ink-secondary" />
            </span>
          )}
          <div className="min-w-0 flex-1 space-y-0.5 text-[13px]">
            <p className="truncate font-medium text-ink">{picked.file.name}</p>
            <p className="type-ledger text-ink-secondary">
              {KIND_LABEL[picked.kind]} · {picked.format} · {formatBytes(picked.file.size)}
              {picked.durationMs != null && <> · {clock(picked.durationMs)}</>}
            </p>
            <p className="text-ink-muted">The file type was read from its contents. The server checks it again.</p>
          </div>
          <Button type="button" size="icon-sm" variant="ghost" onClick={clear} disabled={upload.isPending} aria-label="Remove this file">
            <X aria-hidden />
          </Button>
        </div>
      )}
      {problem && (
        <p role="alert" className="flex items-start gap-2 rounded-lg border border-danger/30 bg-danger-soft/60 px-3 py-2 text-[13px] text-ink">
          <CircleAlert aria-hidden className="mt-0.5 size-4 shrink-0 text-danger" />
          {problem}
        </p>
      )}

      {isMedia && (
        <Field
          label="Sidecar file"
          htmlFor={`${id}-sidecar`}
          hint={
            <>
              Your own transcript (SRT or WebVTT) or plain notes, up to {formatBytes(SIDECAR_MAX_BYTES)}. An SRT or WebVTT file becomes the transcript and is labelled as yours, not as a transcription. Notes are context only.
              Emails and phone numbers are removed before any model reads it.
            </>
          }
          error={sidecarProblem}
        >
          <Input id={`${id}-sidecar`} type="file" accept={SIDECAR_ACCEPT} onChange={(e) => chooseSidecar(e.target.files?.[0])} />
        </Field>
      )}

      {picked && (
        <Label className="items-start gap-2.5 text-[13.5px] leading-snug font-normal">
          <Checkbox checked={rights} onCheckedChange={(checked) => setRights(Boolean(checked))} className="mt-0.5" />
          <span>
            <span className="font-medium text-ink">I hold the rights to use this file.</span>{" "}
            <span className="text-ink-secondary">It will be analysed in Omnicult, and this confirmation is stored with it.</span>
          </span>
        </Label>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" disabled={!picked || !rights || upload.isPending}>
          {upload.isPending ? <LoaderCircle aria-hidden className="animate-spin motion-reduce:animate-none" /> : <Upload aria-hidden />}
          {upload.isPending ? "Uploading…" : "Upload"}
        </Button>
        {picked && !rights && <span className="text-[12.5px] text-ink-muted">Confirm the rights to upload.</span>}
      </div>
      {upload.error && <ErrorState error={upload.error} onRetry={() => picked && rights && upload.mutate({ file: picked.file, kind: picked.kind, rightsConfirmed: rights, sidecar: isMedia ? sidecar : null }, { onSuccess: onUploaded })} />}
    </form>
  );
}

/** What the server did with an upload: stored, being processed, ready, or failed (with its reason). */
function ProcessingLine({ asset }: { asset: Asset }) {
  const status = useAssetStatus(asset.id);
  const processing = status.data?.processing_status ?? asset.processing_status;
  const error = status.data?.processing_error ?? asset.processing_error;
  if (asset.upload_status === "failed" || processing === "failed") {
    return (
      <p role="alert" className="flex items-start gap-1.5 text-[13px] font-medium text-danger">
        <CircleAlert aria-hidden className="mt-0.5 size-4 shrink-0" />
        <span>
          Processing failed.
          {error && <span className="font-normal text-ink"> {error}</span>}
        </span>
      </p>
    );
  }
  if (processing === "processing") {
    return (
      <p role="status" className="flex items-center gap-1.5 text-[13px] font-medium text-info">
        <LoaderCircle aria-hidden className="size-4 animate-spin motion-reduce:animate-none" />
        Processing the file…
      </p>
    );
  }
  return (
    <p className="flex items-center gap-1.5 text-[13px] font-medium text-success">
      <CircleCheck aria-hidden className="size-4" />
      {processing === "ready" ? "Stored and processed" : "Stored"}
      {processing === "pending" && <span className="font-normal text-ink-secondary"> · frames and audio are extracted when the X-Ray runs</span>}
    </p>
  );
}

/** Step two: read the uploaded file as a creative. The label, spoken language and market are optional hints. */
export function RunForm({
  asset,
  campaignId,
  demo,
  onStarted,
  onBack,
}: {
  asset: Asset;
  campaignId: string;
  demo: boolean;
  onStarted: (assetId: string) => void;
  onBack: () => void;
}) {
  const id = useId();
  const status = useAssetStatus(asset.id);
  const regions = useRegions();
  const start = useStartXRay(campaignId);
  const [label, setLabel] = useState("");
  const [language, setLanguage] = useState("");
  const [region, setRegion] = useState("");
  const Icon = KIND_ICON[asset.kind];
  const processing = status.data?.processing_status ?? asset.processing_status;
  const blocked = asset.upload_status === "failed" || processing === "failed" || processing === "processing";
  const sidecar = status.data?.sidecar;
  const removed = Object.values({ ...(sidecar?.redacted ?? {}), ...(status.data?.metadata_redacted ?? {}) }).reduce((a, b) => a + b, 0);
  const media = asset.kind !== "image";

  const run = () => start.mutate({ assetId: asset.id, label: label.trim() || null, language: language || null, regionCode: region || null }, { onSuccess: () => onStarted(asset.id) });

  return (
    <form
      className="space-y-4"
      onSubmit={(e) => {
        e.preventDefault();
        if (!blocked) run();
      }}
    >
      <div className="flex items-start gap-3 rounded-card border border-border bg-surface-muted/50 p-3">
        <span className="clay-well grid size-12 shrink-0 place-items-center rounded-lg">
          <Icon aria-hidden className="size-5 text-ink-secondary" />
        </span>
        <div className="min-w-0 flex-1 space-y-1">
          <p className="truncate text-[13.5px] font-medium text-ink">{asset.filename}</p>
          <p className="type-ledger text-[12.5px] text-ink-secondary">
            {KIND_LABEL[asset.kind]} · {formatBytes(asset.size_bytes)}
            {asset.duration_ms != null && <> · {clock(asset.duration_ms)}</>}
            {asset.width && asset.height && <> · {asset.width} x {asset.height}</>}
            {" · "}
            {asset.rights_confirmed ? "Rights confirmed" : "Rights not confirmed"}
          </p>
          <ProcessingLine asset={asset} />
          {media && (
            <p className="text-[12.5px] text-ink-secondary">
              {sidecar?.present
                ? `Sidecar attached (${sidecar.format?.toUpperCase()}).${removed ? ` ${removed} email or phone number${removed === 1 ? " was" : "s were"} removed before any model use.` : ""}`
                : "No sidecar. Without one, the transcript is only available if the server has a transcription model; otherwise the run completes with gaps and says so."}
            </p>
          )}
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <Field label="Label" htmlFor={`${id}-label`}>
          <Input id={`${id}-label`} value={label} maxLength={120} placeholder={asset.filename} onChange={(e) => setLabel(e.target.value)} />
        </Field>
        {media && (
          <Field label="Spoken language" htmlFor={`${id}-lang`} hint="Helps transcription.">
            <NativeSelect id={`${id}-lang`} value={language} onChange={(e) => setLanguage(e.target.value)}>
              <option value="">Not set</option>
              {LANGUAGES.map((l) => (
                <option key={l.code} value={l.code}>
                  {l.name}
                </option>
              ))}
            </NativeSelect>
          </Field>
        )}
        <Field label="Market" htmlFor={`${id}-region`} hint="The state the creative is read for.">
          <NativeSelect id={`${id}-region`} value={region} onChange={(e) => setRegion(e.target.value)}>
            <option value="">Not set</option>
            {(regions.data ?? []).map((r) => (
              <option key={r.code} value={r.code}>
                {r.name}
              </option>
            ))}
          </NativeSelect>
        </Field>
      </div>

      {demo ? null : (
        <p className="text-[12.5px] text-ink-secondary">
          A live run sends the creative&apos;s keyframes to a vision model, one call per frame, and costs model usage. Run it once, then read the result.
        </p>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <Button type="submit" disabled={blocked || start.isPending}>
          {start.isPending ? <LoaderCircle aria-hidden className="animate-spin motion-reduce:animate-none" /> : <Play aria-hidden />}
          {start.isPending ? "Starting…" : "Run Creative X-Ray"}
        </Button>
        <Button type="button" variant="ghost" onClick={onBack} disabled={start.isPending}>
          <RotateCw aria-hidden />
          Choose another file
        </Button>
      </div>
      {start.error && <ErrorState error={start.error} onRetry={run} />}
    </form>
  );
}
