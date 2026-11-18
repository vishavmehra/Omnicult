"use client";

import { useMutation } from "@tanstack/react-query";
import { CircleAlert, CircleCheck, LoaderCircle, Lock, Plus, Trash2, Type } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

import { ErrorState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Field } from "@/components/forms/fields";
import { cn } from "@/lib/utils";

import { renderTextPreview, useMediaCapabilities, type Creative, type RenderTextRequest, type Scene, type TextPreview as Preview } from "./api";
import { FrameStage, type Rect, type StageBox } from "./frame-stage";
import { LANGUAGES, SCRIPT_NAME } from "./languages";
import { NativeSelect } from "./native-select";

type Align = "left" | "center" | "right";
type Script = NonNullable<RenderTextRequest["boxes"]>[number]["script"];
type TextItem = { id: string; kind: "text"; text: string; language: string; align: Align; bold: boolean; shadow: boolean; color: string; bbox: Rect };
type LockItem = { id: string; kind: "locked"; label: string; bbox: Rect };
type Item = TextItem | LockItem;

const round = (n: number) => Math.round(n * 1000) / 1000;
/** Keeps a box inside the frame the way the API requires: x, y at least 0, width and height above 0, ending by 1. */
const inside = ([x, y, w, h]: Rect): Rect => {
  const cx = Math.min(Math.max(0, x), 0.98);
  const cy = Math.min(Math.max(0, y), 0.98);
  return [round(cx), round(cy), round(Math.min(Math.max(0.02, w), 1 - cx)), round(Math.min(Math.max(0.02, h), 1 - cy))];
};

/** x, y, width, height of the active box in percent: a keyboard-reachable alternative to dragging. */
function BoxFields({ bbox, onChange }: { bbox: Rect; onChange: (r: Rect) => void }) {
  const names = ["Left", "Top", "Width", "Height"];
  return (
    <div className="grid grid-cols-4 gap-2">
      {bbox.map((v, i) => (
        <Field key={names[i]} label={`${names[i]} %`} htmlFor={`box-${names[i]}`} required>
          <Input
            id={`box-${names[i]}`}
            type="number"
            inputMode="decimal"
            min={0}
            max={100}
            step={1}
            value={round(v * 100)}
            onChange={(e) => {
              const n = Number(e.target.value);
              if (Number.isFinite(n)) onChange(inside(bbox.map((old, j) => (j === i ? n / 100 : old)) as Rect));
            }}
          />
        </Field>
      ))}
    </div>
  );
}

/**
 * Indic text preview on a keyframe or key visual. The text is drawn by the server in code with a Noto face and the
 * Raqm shaping engine (never by an image model), then locked regions are restored pixel for pixel from the original. The
 * report below comes from the server's response headers, not from the picture. The page remounts this per frame, so
 * boxes and the preview never outlive the frame they were placed on.
 */
export function TextPreviewTool({ creative, scene }: { creative: Creative; scene: Scene }) {
  const id = useId();
  const caps = useMediaCapabilities();
  const supported = caps.data ? LANGUAGES.filter((l) => (caps.data.scripts as string[]).includes(l.script)) : LANGUAGES;
  const shapingBasic = caps.data?.text_shaping === "basic";
  const available = shapingBasic ? supported.filter((l) => l.script === "Latn") : supported;
  const [items, setItems] = useState<Item[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const counter = useRef(0);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [staleAfter, setStaleAfter] = useState(false);

  const frameAsset = scene.keyframe_asset_id ?? creative.asset_id;
  const framePath = scene.keyframe_url;
  const aspect = creative.asset.width && creative.asset.height ? creative.asset.width / creative.asset.height : null;
  const active = items.find((i) => i.id === activeId) ?? null;
  const texts = items.filter((i): i is TextItem => i.kind === "text");
  const locks = items.filter((i): i is LockItem => i.kind === "locked");

  useEffect(() => () => void (preview && URL.revokeObjectURL(preview.url)), [preview]);

  const defaultLanguage = available.find((l) => l.code === creative.language) ?? available[0];

  function add(kind: Item["kind"]) {
    const n = ++counter.current;
    const item: Item =
      kind === "text"
        ? { id: `t${n}`, kind, text: "", language: defaultLanguage?.code ?? "en", align: "center", bold: true, shadow: true, color: "#ffffff", bbox: [0.08, 0.72, 0.84, 0.16] }
        : { id: `l${n}`, kind, label: "Logo", bbox: [0.3, 0.04, 0.4, 0.12] };
    setItems((all) => [...all, item]);
    setActiveId(item.id);
    setStaleAfter(Boolean(preview));
  }

  function patch(itemId: string, change: Partial<TextItem> & Partial<LockItem>) {
    setItems((all) => all.map((i) => (i.id === itemId ? ({ ...i, ...change } as Item) : i)));
    setStaleAfter(Boolean(preview));
  }

  function remove(itemId: string) {
    setItems((all) => all.filter((i) => i.id !== itemId));
    if (activeId === itemId) setActiveId(null);
    setStaleAfter(Boolean(preview));
  }

  const render = useMutation({
    mutationFn: () =>
      renderTextPreview(creative.project_id, {
        original_asset_id: frameAsset,
        base_asset_id: frameAsset,
        background: "#202020", // unused: the keyframe is the base
        boxes: texts.map((t) => {
          const lang = LANGUAGES.find((l) => l.code === t.language) ?? LANGUAGES[0];
          return {
            text: t.text,
            script: lang.script as Script,
            language: lang.code,
            bbox: t.bbox,
            align: t.align,
            valign: "middle" as const,
            color: t.color,
            bold: t.bold,
            min_size_px: 10,
            max_size_px: 96,
            line_spacing: 1,
            shadow: t.shadow ? { dx: 2, dy: 2, blur: 4, color: "#000000aa" } : null,
          };
        }),
        locked_regions: locks.map((l) => ({ label: l.label.trim() || "Locked", bbox: l.bbox })),
      }),
    onSuccess: (result) => {
      setPreview(result);
      setStaleAfter(false);
    },
  });

  const ready = texts.length > 0 && texts.every((t) => t.text.trim().length > 0) && locks.every((l) => l.label.trim().length > 0);

  const boxes: StageBox[] = [
    ...(scene.anchor.bbox ? [{ id: "anchor", bbox: scene.anchor.bbox, label: "Scene anchor", tone: "anchor" as const }] : []),
    ...items.map((i) => ({
      id: i.id,
      bbox: i.bbox,
      label: i.kind === "text" ? `Text ${texts.indexOf(i) + 1}` : `Locked: ${i.label || "region"}`,
      tone: i.kind === "text" ? ("text" as const) : ("locked" as const),
      active: i.id === activeId,
    })),
  ];

  return (
    <div className="space-y-4">
      {shapingBasic && (
        <p role="status" className="flex items-start gap-2 rounded-lg border border-warning/30 bg-warning-soft/70 px-3 py-2 text-[13px] text-ink">
          <CircleAlert aria-hidden className="mt-0.5 size-4 shrink-0 text-warning" />
          This server has no complex-script shaping engine, so only Latin text can be previewed. Indic text is refused rather than drawn unshaped.
        </p>
      )}
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <div className="space-y-2">
          <p className="text-[13px] font-medium text-ink">Place the boxes</p>
          <p className="type-meta">Drag on the frame to set the active box, or type its position below.</p>
          <FrameStage
            path={framePath}
            aspect={aspect}
            boxes={boxes}
            alt={`Keyframe of ${creative.label} where the text boxes are placed`}
            empty="This creative has no picture to place text on."
            onDraw={framePath ? (rect) => (active ? patch(active.id, { bbox: inside(rect) }) : null) : undefined}
          />
          {!active && items.length === 0 && <p className="text-[12.5px] text-ink-secondary">Add a text box to begin.</p>}
        </div>

        <div className="space-y-2">
          <p className="text-[13px] font-medium text-ink">Preview</p>
          {preview ? (
            <div className="space-y-1.5">
              {/* eslint-disable-next-line @next/next/no-img-element -- object URL of the rendered PNG */}
              <img src={preview.url} alt="Keyframe with the regional text drawn on it" className={cn("clay-well mx-auto block max-h-[min(36rem,70dvh)] w-auto max-w-full rounded-xl", staleAfter && "opacity-60")} />
              {staleAfter && <p className="text-center text-[12.5px] font-medium text-warning">The boxes changed after this preview. Render again to update it.</p>}
            </div>
          ) : (
            <div className="clay-well grid min-h-40 place-items-center rounded-xl px-4 py-8 text-center text-[13px] text-ink-muted">
              {render.isPending ? "Rendering…" : "The rendered frame appears here. Nothing is stored."}
            </div>
          )}
        </div>
      </div>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <div className="space-y-3">
          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="outline" size="sm" onClick={() => add("text")} disabled={texts.length >= 12 || !defaultLanguage}>
              <Plus aria-hidden />
              <Type aria-hidden />
              Text box
            </Button>
            <Button type="button" variant="outline" size="sm" onClick={() => add("locked")} disabled={locks.length >= 8}>
              <Plus aria-hidden />
              <Lock aria-hidden />
              Locked region
            </Button>
          </div>

          {items.length > 0 && (
            <ul className="ledger-rules rounded-card border border-border bg-surface" aria-label="Boxes">
              {items.map((i) => {
                const lang = i.kind === "text" ? LANGUAGES.find((l) => l.code === i.language) : null;
                return (
                  <li key={i.id} className={cn("flex items-center gap-2 px-3 py-1.5", i.id === activeId && "bg-surface-muted")}>
                    <button
                      type="button"
                      onClick={() => setActiveId(i.id)}
                      aria-current={i.id === activeId ? "true" : undefined}
                      className="flex min-w-0 flex-1 items-center gap-2 py-1 text-left text-[13px] text-ink"
                    >
                      {i.kind === "text" ? <Type aria-hidden className="size-3.5 shrink-0 text-ink-secondary" /> : <Lock aria-hidden className="size-3.5 shrink-0 text-warning" />}
                      <span className="min-w-0 flex-1 truncate" lang={i.kind === "text" ? i.language : undefined}>
                        {i.kind === "text" ? i.text || "Empty text box" : `Locked: ${i.label}`}
                      </span>
                      <span className="type-meta shrink-0">{i.kind === "text" ? lang?.name : "Locked"}</span>
                    </button>
                    <Button type="button" variant="ghost" size="icon-xs" onClick={() => remove(i.id)} aria-label={`Remove ${i.kind === "text" ? "text box" : "locked region"}`}>
                      <Trash2 aria-hidden />
                    </Button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        <div className="space-y-3">
          {active?.kind === "text" && (
            <div className="space-y-3 rounded-card border border-border bg-surface p-4">
              <Field label="Text" htmlFor={`${id}-text`} required hint={`Typed or pasted in the language you choose. Set in ${SCRIPT_NAME[LANGUAGES.find((l) => l.code === active.language)?.script ?? "Latn"]}.`}>
                <Textarea
                  id={`${id}-text`}
                  lang={active.language}
                  value={active.text}
                  maxLength={400}
                  rows={2}
                  onChange={(e) => patch(active.id, { text: e.target.value })}
                  className="text-[16px] leading-[1.6]"
                />
              </Field>
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="Language" htmlFor={`${id}-lang`} required>
                  <NativeSelect id={`${id}-lang`} value={active.language} onChange={(e) => patch(active.id, { language: e.target.value })}>
                    {available.map((l) => (
                      <option key={l.code} value={l.code}>
                        {l.name} ({SCRIPT_NAME[l.script]})
                      </option>
                    ))}
                  </NativeSelect>
                </Field>
                <Field label="Alignment" htmlFor={`${id}-align`} required>
                  <NativeSelect id={`${id}-align`} value={active.align} onChange={(e) => patch(active.id, { align: e.target.value as Align })}>
                    <option value="left">Left</option>
                    <option value="center">Centre</option>
                    <option value="right">Right</option>
                  </NativeSelect>
                </Field>
              </div>
              <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
                <Label className="font-normal">
                  <Checkbox checked={active.bold} onCheckedChange={(c) => patch(active.id, { bold: Boolean(c) })} />
                  Bold
                </Label>
                <Label className="font-normal">
                  <Checkbox checked={active.shadow} onCheckedChange={(c) => patch(active.id, { shadow: Boolean(c) })} />
                  Soft shadow
                </Label>
                <Label className="font-normal">
                  Colour
                  <input
                    type="color"
                    value={active.color}
                    onChange={(e) => patch(active.id, { color: e.target.value })}
                    aria-label="Text colour"
                    className="h-7 w-10 cursor-pointer rounded-md border border-border-strong/55 bg-surface-raised p-0.5"
                  />
                </Label>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => patch(active.id, { text: LANGUAGES.find((l) => l.code === active.language)?.sample ?? "" })}
                >
                  Use a sample line
                </Button>
                <span className="type-meta">A common greeting for checking layout. Not campaign copy and not reviewed by a native speaker.</span>
              </div>
              <BoxFields bbox={active.bbox} onChange={(bbox) => patch(active.id, { bbox })} />
            </div>
          )}
          {active?.kind === "locked" && (
            <div className="space-y-3 rounded-card border border-border bg-surface p-4">
              <Field label="Name" htmlFor={`${id}-lock`} required hint="Logo, product, tagline. Locked pixels are restored from the original after the text is drawn, so text can never alter them.">
                <Input id={`${id}-lock`} value={active.label} maxLength={40} onChange={(e) => patch(active.id, { label: e.target.value })} />
              </Field>
              <BoxFields bbox={active.bbox} onChange={(bbox) => patch(active.id, { bbox })} />
            </div>
          )}
          {!active && items.length > 0 && <p className="text-[13px] text-ink-secondary">Choose a box in the list to edit it.</p>}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <Button type="button" onClick={() => render.mutate()} disabled={!ready || render.isPending || !framePath}>
          {render.isPending && <LoaderCircle aria-hidden className="animate-spin motion-reduce:animate-none" />}
          {render.isPending ? "Rendering…" : "Render preview"}
        </Button>
        {!ready && <span className="text-[12.5px] text-ink-muted">{texts.length === 0 ? "Add a text box with some text." : "Fill in every box."}</span>}
      </div>
      {render.error && <ErrorState error={render.error} onRetry={() => render.mutate()} />}

      {preview && !render.isPending && <Report preview={preview} texts={texts} hasLocks={locks.length > 0} />}
    </div>
  );
}

function Verdict({ ok, children }: { ok: boolean; children: React.ReactNode }) {
  return (
    <span className={cn("inline-flex items-start gap-1.5 font-medium", ok ? "text-success" : "text-warning")}>
      {ok ? <CircleCheck aria-hidden className="mt-0.5 size-3.5 shrink-0" /> : <CircleAlert aria-hidden className="mt-0.5 size-3.5 shrink-0" />}
      <span>{children}</span>
    </span>
  );
}

/** What the server reported about this render: shaping engine, fit and overlap per text box, locked regions restored. */
function Report({ preview, texts, hasLocks }: { preview: Preview; texts: TextItem[]; hasLocks: boolean }) {
  return (
    <section aria-label="Preview report" className="space-y-2">
      <h3 className="text-[15px] font-semibold text-ink">What the server reported</h3>
      <dl className="ledger-rules rounded-card border border-border bg-surface text-[13.5px]">
        <div className="grid gap-1 px-4 py-2.5 sm:grid-cols-[11rem_minmax(0,1fr)] sm:gap-4">
          <dt className="type-ledger text-[12.5px] text-ink-muted">Text shaping</dt>
          <dd>
            <Verdict ok={preview.shaping === "raqm"}>
              {preview.shaping === "raqm" ? "Complex-script shaping (Raqm)" : preview.shaping === "basic" ? "Basic layout, Latin only" : humanizeEngine(preview.shaping)}
            </Verdict>
            <span className="block text-ink-secondary">The script&apos;s own Noto face is used. Conjuncts and vowel signs are laid out by the shaping engine, not by an image model.</span>
          </dd>
        </div>
        {texts.map((t, i) => (
          <div key={t.id} className="grid gap-1 px-4 py-2.5 sm:grid-cols-[11rem_minmax(0,1fr)] sm:gap-4">
            <dt className="type-ledger text-[12.5px] text-ink-muted">
              Text {i + 1}
              <span className="block max-w-full truncate text-ink-secondary" lang={t.language}>
                {t.text}
              </span>
            </dt>
            <dd className="space-y-1">
              {preview.fits[i] === undefined ? (
                <span className="text-ink-secondary">No report for this box.</span>
              ) : (
                <>
                  <Verdict ok={preview.fits[i]}>{preview.fits[i] ? "Fits its box" : "Does not fit its box"}</Verdict>
                  {!preview.fits[i] && <span className="block text-ink-secondary">Even at the smallest size allowed the text is clipped to the box. Enlarge the box or shorten the line.</span>}
                  {hasLocks && (
                    <span className="block">
                      <Verdict ok={!preview.overlapsLocked[i]}>{preview.overlapsLocked[i] ? "Overlaps a locked region" : "Clear of locked regions"}</Verdict>
                      {preview.overlapsLocked[i] && <span className="block text-ink-secondary">Where they overlap, the locked pixels are restored over the text, so that part of the text is hidden. Move the box.</span>}
                    </span>
                  )}
                </>
              )}
            </dd>
          </div>
        ))}
        {hasLocks && (
          <div className="grid gap-1 px-4 py-2.5 sm:grid-cols-[11rem_minmax(0,1fr)] sm:gap-4">
            <dt className="type-ledger text-[12.5px] text-ink-muted">Locked regions</dt>
            <dd className="text-ink-body">{preview.lockedRestored} restored pixel for pixel from the original</dd>
          </div>
        )}
      </dl>
    </section>
  );
}

const humanizeEngine = (e: string) => (e ? e.charAt(0).toUpperCase() + e.slice(1) : "Unknown engine");
