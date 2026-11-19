"use client";

import { ArrowLeft, ArrowRight, Fingerprint, Layers, type LucideIcon } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";

import { STAGES, WORKSPACES, type WorkspaceKey } from "@/components/shell/workspaces";
import { Verdict } from "@/components/workflow/verdict";
import { cn } from "@/lib/utils";

type Card = {
  key: string;
  title: string;
  where: string;
  icons: LucideIcon[];
  features: string[];
  roadmap: string[];
  tint: string;
  extra?: "verdicts" | "scripts";
};

const tier3 = (keys: WorkspaceKey[]) => keys.flatMap((k) => WORKSPACES[k].features.filter((f) => f.tier === 3).map((f) => f.name));

// Curated: the 3 to 5 features each stage is known by (tiers 1 and 2 of the scope plan); tier 3 is roadmap, one small line.
const PICKS: Record<string, string[]> = {
  plan: ["Campaign Brief", "Brand Kit", "Culture Atlas", "State Profile", "Evidence Meter"],
  create: ["Creative X-Ray", "Transcreate, with English back-translation", "Tweak Chips", "Lock and Edit", "Version Tree"],
  test: ["Quick Read", "Risk Check", "Audience Study", "Ask the Panel"],
  decide: ["Compare and Score, by visible rules", "Readiness Board"],
  track: ["Regional Dashboard by region and version"],
  prove: ["Proof Report", "Run History", "Evidence Map", "Search", "Data Health"],
};
const TINTS = ["tint-peach", "tint-sky", "tint-mint", "tint-butter", "tint-rose", "tint-peach", "tint-sky", "tint-mint"];

const CARDS: Card[] = [
  ...STAGES.map((s, i) => ({
    key: s.key,
    title: s.label,
    where: s.workspaces.map((k) => WORKSPACES[k].label).join(" · "),
    icons: s.workspaces.map((k) => WORKSPACES[k].Icon),
    features: PICKS[s.key] ?? [],
    roadmap: tier3(s.workspaces),
    tint: TINTS[i],
    extra: s.key === "decide" ? ("verdicts" as const) : undefined,
  })),
  {
    key: "trust",
    title: "Every claim has a receipt",
    where: "The trust layer",
    icons: [Fingerprint],
    features: ["Five tags: source, date, kind, scope, confidence", "Confidence by rule, never a percentage", "Conflict cards keep both values"],
    roadmap: [],
    tint: TINTS[6],
  },
  {
    key: "platform",
    title: "Under every workspace",
    where: "The platform",
    icons: [Layers],
    features: ["Teams and Roles", "Resumable Runs", "Model Gateway", "Country Packs: India"],
    roadmap: ["Usage and Credits"],
    tint: TINTS[7],
    extra: "scripts",
  },
];

const AUTONYMS = [
  { lang: "ta", name: "தமிழ்" },
  { lang: "ml", name: "മലയാളം" },
  { lang: "bn", name: "বাংলা" },
  { lang: "mr", name: "मराठी" },
  { lang: "te", name: "తెలుగు" },
];

/**
 * The workflow as a horizontal stack of clay cards. Native scroll with snap (touch swipes for free), arrow buttons, arrow
 * keys on the focused track, mouse drag, and a progress well. Reduced motion jumps instead of gliding.
 */
export function StageCarousel() {
  const track = useRef<HTMLDivElement>(null);
  const [index, setIndex] = useState(0);
  const [progress, setProgress] = useState(0);
  const [atEnd, setAtEnd] = useState(false);
  const drag = useRef<{ x: number; left: number; moved: boolean } | null>(null);

  const step = useCallback(() => {
    const el = track.current;
    const first = el?.firstElementChild as HTMLElement | null;
    if (!el || !first) return 320;
    return first.offsetWidth + parseFloat(getComputedStyle(el).columnGap || "0");
  }, []);

  const go = useCallback(
    (to: number) => {
      const el = track.current;
      if (!el) return;
      const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      el.scrollTo({ left: Math.max(0, to) * step(), behavior: reduce ? "auto" : "smooth" });
    },
    [step],
  );

  useEffect(() => {
    const el = track.current;
    if (!el) return;
    const onScroll = () => {
      const max = el.scrollWidth - el.clientWidth;
      setProgress(max > 0 ? el.scrollLeft / max : 0);
      setAtEnd(el.scrollLeft >= max - 4);
      setIndex(Math.min(CARDS.length - 1, Math.round(el.scrollLeft / step())));
    };
    onScroll();
    el.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    return () => {
      el.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
    };
  }, [step]);

  function onKey(e: KeyboardEvent<HTMLDivElement>) {
    if (e.key === "ArrowRight") go(index + 1);
    else if (e.key === "ArrowLeft") go(index - 1);
    else if (e.key === "Home") go(0);
    else if (e.key === "End") go(CARDS.length - 1);
    else return;
    e.preventDefault();
  }

  // Mouse drag (touch and pen already scroll natively).
  function onPointerDown(e: PointerEvent<HTMLDivElement>) {
    if (e.pointerType !== "mouse" || e.button !== 0 || !track.current) return;
    drag.current = { x: e.clientX, left: track.current.scrollLeft, moved: false };
  }
  function onPointerMove(e: PointerEvent<HTMLDivElement>) {
    const el = track.current;
    const d = drag.current;
    if (!el || !d) return;
    const dx = e.clientX - d.x;
    if (!d.moved && Math.abs(dx) > 4) {
      d.moved = true;
      el.dataset.dragging = "true";
      el.setPointerCapture(e.pointerId);
    }
    if (d.moved) el.scrollLeft = d.left - dx;
  }
  function onPointerUp() {
    const el = track.current;
    const d = drag.current;
    drag.current = null;
    if (!el || !d?.moved) return;
    delete el.dataset.dragging;
    go(Math.round(el.scrollLeft / step()));
  }

  return (
    <section data-carousel aria-roledescription="carousel" aria-labelledby="stages-title" className="mx-auto w-full max-w-[1240px] pb-8">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-4 px-5 sm:px-8">
        <h2 id="stages-title" className="type-title text-[clamp(22px,2.2vw,30px)] text-ink">
          Six stages, one record.
        </h2>
        <div className="flex items-center gap-2">
          <span className="type-meta mr-1 tabular-nums" aria-live="polite">
            {index + 1} / {CARDS.length}
          </span>
          <button
            type="button"
            onClick={() => go(index - 1)}
            disabled={index === 0}
            aria-controls="stage-track"
            aria-label="Previous card"
            className="clay inline-flex size-10 items-center justify-center rounded-full text-ink disabled:opacity-40 disabled:shadow-none"
          >
            <ArrowLeft aria-hidden className="size-4" />
          </button>
          <button
            type="button"
            onClick={() => go(index + 1)}
            disabled={atEnd}
            aria-controls="stage-track"
            aria-label="Next card"
            className="clay inline-flex size-10 items-center justify-center rounded-full text-ink disabled:opacity-40 disabled:shadow-none"
          >
            <ArrowRight aria-hidden className="size-4" />
          </button>
        </div>
      </div>

      <div
        id="stage-track"
        ref={track}
        tabIndex={0}
        role="group"
        aria-label="Workflow stages. Use the arrow keys to move between cards."
        onKeyDown={onKey}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onClickCapture={(e) => drag.current?.moved && e.preventDefault()}
        className="carousel-track gap-4 scroll-px-5 px-5 pt-2 pb-6 focus-visible:outline-offset-[-2px] sm:scroll-px-8 sm:px-8"
      >
        {CARDS.map((c, i) => (
          <article
            key={c.key}
            data-card
            role="group"
            aria-roledescription="slide"
            aria-label={`${i + 1} of ${CARDS.length}: ${c.title}`}
            className={cn(
              "flex w-[min(82vw,320px)] shrink-0 flex-col rounded-[22px] border border-border/50 p-6 shadow-clay select-none",
              c.tint,
            )}
          >
            <div className="flex items-center justify-between gap-3">
              <span className="font-mono text-[12px] text-ink-muted tabular-nums">{String(i + 1).padStart(2, "0")}</span>
              <span className="flex gap-1.5">
                {c.icons.map((Icon, j) => (
                  <span key={j} className="clay inline-flex size-9 items-center justify-center rounded-xl text-ink">
                    <Icon aria-hidden className="size-[18px]" />
                  </span>
                ))}
              </span>
            </div>
            <h3 className="type-title mt-5 text-[25px] text-ink">{c.title}</h3>
            <p className="mt-1 text-[13px] text-ink-secondary">{c.where}</p>
            <ul className="mt-5 space-y-2.5">
              {c.features.map((f) => (
                <li key={f} className="flex gap-2.5 text-[14.5px] leading-snug text-ink-body">
                  <span aria-hidden className="mt-[7px] size-1.5 shrink-0 rounded-full bg-ink-muted" />
                  {f}
                </li>
              ))}
            </ul>
            {c.extra === "verdicts" && (
              <div className="mt-5 flex flex-wrap gap-2" aria-label="Verdicts">
                <Verdict value="go" />
                <Verdict value="fix" />
                <Verdict value="rethink" />
              </div>
            )}
            {c.extra === "scripts" && (
              <p className="mt-5 flex flex-wrap gap-x-3 gap-y-1 text-[15px] text-ink-secondary" aria-label="Languages set in their own scripts">
                {AUTONYMS.map((a) => (
                  <span key={a.lang} lang={a.lang}>
                    {a.name}
                  </span>
                ))}
              </p>
            )}
            <p className="mt-auto pt-5 text-[12px] leading-relaxed text-ink-muted">
              {" "}
            </p>
          </article>
        ))}
      </div>

      <div className="px-5 sm:px-8" aria-hidden>
        <div className="clay-well h-2 w-full max-w-[240px] overflow-hidden rounded-full p-[2px]">
          <div
            className="h-full rounded-full bg-pop transition-[width] duration-200"
            style={{ width: `${Math.max(12, Math.round(progress * 100))}%` }}
          />
        </div>
      </div>
    </section>
  );
}
