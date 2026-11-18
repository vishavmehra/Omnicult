"use client";

import { FilmStrip } from "@/components/creative";
import { humanize } from "@/lib/format";

import { useBlob, useObjectUrl, type Creative, type Scene } from "./api";
import { Block, EvidenceIds, Phrases, ProvenanceTag, clock, span } from "./parts";
import { plural } from "./media-file";

function FrameImg({ path, alt }: { path: string | null; alt: string }) {
  const blob = useBlob(path);
  const src = useObjectUrl(blob.data);
  return src ? (
    // eslint-disable-next-line @next/next/no-img-element -- authenticated blob
    <img src={src} alt={alt} draggable={false} className="size-full" />
  ) : (
    <span className="grid size-full place-items-center px-1 text-center text-[11px] text-ink-muted">{path ? "Loading" : "No picture"}</span>
  );
}

/**
 * The scene timeline as a film strip of the keyframes the server extracted: move along it to scrub the frames, click or
 * press Enter to select a scene (the stage and the player below follow the selection). The video is never seeked from
 * here; scenes are read from keyframes and thumbnails. Arrow keys move between scenes. Wide strips scroll inside their
 * own box, never the page.
 */
export function SceneStrip({ scenes, selectedId, onSelect }: { scenes: Scene[]; selectedId: string | null; onSelect: (id: string) => void }) {
  return (
    <div className="overflow-x-auto pb-1.5">
      <div style={{ minWidth: `${scenes.length * 5.25}rem` }}>
        <FilmStrip
          ariaLabel="Scenes in time order"
          preview={false}
          selectedId={selectedId}
          onSelect={onSelect}
          frames={scenes.map((s, i) => ({
            id: s.id,
            at: clock(s.start_ms),
            label: `Scene ${i + 1}`,
            media: <FrameImg path={s.keyframe_url} alt="" />,
          }))}
        />
      </div>
    </div>
  );
}

const SEEN: { key: "people" | "gestures" | "objects" | "colours"; label: string }[] = [
  { key: "people", label: "People" },
  { key: "gestures", label: "Gestures" },
  { key: "objects", label: "Objects" },
  { key: "colours", label: "Colours" },
];

/** Everything the X-Ray found in one scene, each field labelled with what kind of thing it is. */
export function SceneDetail({ scene, index, total, creative }: { scene: Scene; index: number; total: number; creative: Creative }) {
  const analysis = creative.analysis;
  const visionRan = analysis?.vision.status === "analyzed";
  const transcribe = analysis?.transcribe;
  const titles: Record<string, string> = {};
  analysis?.frames.forEach((f) => (titles[f.id] = `Keyframe at ${clock(f.timestamp_ms)}`));
  analysis?.transcript.forEach((t) => (titles[t.id] = `Transcript line at ${clock(t.start_ms)}`));
  const seen = SEEN.filter((s) => scene[s.key].length > 0);
  const hasSeen = seen.length > 0 || Boolean(scene.setting);
  const lang = creative.language ?? undefined;
  const frames = visionRan ? (analysis?.frames ?? []).filter((f) => scene.frame_ms.includes(f.timestamp_ms)) : [];

  return (
    <div className="ledger-rules rounded-card border border-border bg-surface">
      <section className="space-y-1 px-4 py-3">
        <h3 className="text-[15px] font-semibold text-ink">
          {creative.kind === "image" ? "The image" : `Scene ${index + 1} of ${total}`}
        </h3>
        <p className="type-ledger text-[13px] text-ink-body">
          {scene.end_ms == null ? "One frame, no duration" : <>{span(scene.start_ms, scene.end_ms)} · {((scene.end_ms - scene.start_ms) / 1000).toFixed(1)} s</>}
        </p>
        {scene.frame_ms.length > 0 && (
          <p className="type-meta">
            Read from {plural(scene.frame_ms.length, "keyframe")} at {scene.frame_ms.map(clock).join(", ")}
          </p>
        )}
        {!visionRan && (
          <p className="text-[12.5px] text-warning">Timing and keyframe only: no vision model read this scene.</p>
        )}
      </section>

      <Block title="Transcript" tag={scene.transcript.length > 0 && <ProvenanceTag kind={scene.transcript.every((t) => t.source === "user_sidecar") ? "user_provided" : "transcribed"} />}>
        {scene.transcript.length > 0 ? (
          <ol className="space-y-1.5">
            {scene.transcript.map((t) => (
              <li key={t.id} className="grid grid-cols-[3.2rem_minmax(0,1fr)] gap-2 text-[14px]">
                <span className="type-ledger pt-0.5 text-[12px] text-ink-muted">{clock(t.start_ms)}</span>
                <span lang={t.language ?? lang} className="text-ink">
                  {t.text}
                  {t.source === "user_sidecar" && <span className="type-meta ml-2">from your sidecar</span>}
                </span>
              </li>
            ))}
          </ol>
        ) : (
          <p className="text-[13px] text-ink-secondary">
            {transcribe?.status === "unavailable" || transcribe?.status === "failed"
              ? "No transcript: speech was not transcribed for this creative."
              : transcribe?.status === "not_applicable"
                ? "An image has no speech."
                : "No spoken lines fall in this scene."}
          </p>
        )}
      </Block>

      <Block title="On-screen text" tag={scene.on_screen_text.length > 0 && <ProvenanceTag kind="observed" />}>
        {scene.on_screen_text.length > 0 ? (
          <ul className="space-y-1">
            {scene.on_screen_text.map((t, i) => (
              <li key={i} className="flex flex-wrap items-baseline gap-x-2 text-[14px] text-ink">
                <span>{t.text}</span>
                {t.frame_ms != null && <span className="type-meta">at {clock(t.frame_ms)}</span>}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-[13px] text-ink-secondary">{visionRan ? "No text was read from this scene's keyframes." : "Not read: no vision model ran."}</p>
        )}
      </Block>

      {scene.claims.length > 0 && (
        <Block title="Claims in the ad" tag={<ProvenanceTag kind="model_generated" />}>
          <ul className="space-y-1.5">
            {scene.claims.map((c, i) => (
              <li key={i} className="text-[14px] text-ink">
                &ldquo;{c.text}&rdquo; <span className="type-meta">quoted from {c.source === "on_screen_text" ? "on-screen text" : "the transcript"}</span>
              </li>
            ))}
          </ul>
        </Block>
      )}

      {visionRan && (
        <Block title="What the model saw" tag={hasSeen && <ProvenanceTag kind="model_generated" />}>
          {hasSeen ? (
            <dl className="space-y-2 text-[13px]">
              {scene.setting && (
                <div className="grid gap-1 sm:grid-cols-[5.5rem_minmax(0,1fr)] sm:gap-3">
                  <dt className="type-ledger text-ink-muted">Setting</dt>
                  <dd className="text-ink-body">{scene.setting}</dd>
                </div>
              )}
              {seen.map((s) => (
                <div key={s.key} className="grid gap-1 sm:grid-cols-[5.5rem_minmax(0,1fr)] sm:gap-3">
                  <dt className="type-ledger text-ink-muted">{s.label}</dt>
                  <dd>
                    <Phrases items={scene[s.key]} />
                  </dd>
                </div>
              ))}
            </dl>
          ) : (
            <p className="text-[13px] text-ink-secondary">The model reported nothing for this scene.</p>
          )}
        </Block>
      )}

      {scene.music_mood && (
        <Block title="Music mood" tag={<ProvenanceTag kind={scene.provenance.music_mood ?? "model_generated"} />}>
          <p className="text-[14px] text-ink">{scene.music_mood}</p>
        </Block>
      )}

      {visionRan && (
        <Block title="Cultural observations" tag={scene.cultural_observations.length > 0 && <ProvenanceTag kind="model_generated" />}>
          {scene.cultural_observations.length > 0 ? (
            <ul className="space-y-2.5">
              {scene.cultural_observations.map((o) => (
                <li key={o.id} className="space-y-0.5">
                  <p className="text-[14px] text-ink">
                    <code className="mr-2 font-mono text-[11.5px] text-ink-muted">{o.id}</code>
                    {o.text}
                  </p>
                  <p className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[12px]">
                    {o.category && <span className="text-ink-secondary">{humanize(o.category)}</span>}
                    <EvidenceIds ids={o.evidence} titles={titles} />
                    {o.claim_ids.length > 0 && <span className="type-meta">Linked to {plural(o.claim_ids.length, "regional claim")}</span>}
                  </p>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-[13px] text-ink-secondary">The model reported no cultural observations for this scene.</p>
          )}
        </Block>
      )}

      {scene.cultural_interpretations.length > 0 && (
        <Block title="Cultural references the model read" tag={<ProvenanceTag kind="interpretation" />} meta="Not observed facts">
          <ul className="space-y-3">
            {scene.cultural_interpretations.map((c) => (
              <li key={c.id} className="space-y-1 rounded-lg border border-dashed border-border-strong/50 px-3 py-2">
                <p className="text-[14px] text-ink">
                  <code className="mr-2 font-mono text-[11.5px] text-ink-muted">{c.id}</code>
                  {c.text}
                </p>
                <p className="flex flex-wrap items-center gap-x-3 text-[12px]">
                  {c.category && <span className="text-ink-secondary">{humanize(c.category)}</span>}
                  <EvidenceIds ids={c.based_on} titles={titles} />
                </p>
                {c.limitations.length > 0 && (
                  <ul className="list-disc space-y-0.5 pl-5 text-[12.5px] text-ink-secondary">
                    {c.limitations.map((l, i) => (
                      <li key={i}>{l}</li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ul>
        </Block>
      )}

      {frames.length > 0 && (
        <section className="px-4 py-3">
          <details>
            <summary className="cursor-pointer text-[13.5px] font-semibold text-ink">What the vision model said it saw in this scene&apos;s keyframes</summary>
            <div className="mt-2 space-y-3">
              <p className="text-[12.5px] text-ink-secondary">
                The raw observations the on-screen text and claims above were checked against. Positions are the model&apos;s own words, not measured boxes.
              </p>
              {frames.map((f) => (
                <div key={f.id} className="space-y-1">
                  <p className="type-ledger text-[12px] text-ink-muted">
                    <code className="font-mono">{f.id}</code> · keyframe at {clock(f.timestamp_ms)}
                  </p>
                  {f.observations.length > 0 ? (
                    <ul className="space-y-1">
                      {f.observations.map((o) => (
                        <li key={o.id} className="text-[13px] text-ink-body">
                          <span className="text-ink-muted">{humanize(o.kind)}{o.location ? `, ${o.location}` : ""}: </span>
                          {o.description}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-[12.5px] text-ink-secondary">No observations were kept for this frame.</p>
                  )}
                </div>
              ))}
            </div>
          </details>
        </section>
      )}

      {scene.limitations.length > 0 && (
        <Block title="Limits of this scene">
          <ul className="list-disc space-y-0.5 pl-5 text-[13px] text-ink-body marker:text-ink-secondary">
            {scene.limitations.map((l, i) => (
              <li key={i}>{l}</li>
            ))}
          </ul>
        </Block>
      )}
    </div>
  );
}
