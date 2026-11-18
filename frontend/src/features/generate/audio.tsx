"use client";

import { Pause, Play } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { useAssetObjectUrl } from "@/features/assets/asset-uploader";
import { cn } from "@/lib/utils";

import type { GenerateAssetRef } from "./api";
import { mmss } from "./parts";

export type Segment = { index: number; start: number; end: number; label: string };

const LIVE_SLICES = 64; // about three seconds of level history at 20 samples a second
const reduced = () => typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** Every audio element a player owns. Starting one pauses the rest, so two sounds never play over each other. */
const registry = new Set<HTMLAudioElement>();
const othersPlaying = (self: HTMLAudioElement) => [...registry].some((a) => a !== self && !a.paused && !a.ended);

export type Player = {
  src: string | null;
  /** Hand this to the `<audio>` element's ref (see PlayerAudio). */
  bind: (element: HTMLAudioElement | null) => void;
  playing: boolean;
  /** Seconds, updated while playing. Read it inside a draw loop, never during render. */
  timeRef: React.RefObject<number>;
  /** The most recent loudness readings (0 to 1) of what is actually playing. */
  levelsRef: React.RefObject<number[]>;
  /** The line (segment index) under the playhead, or -1. */
  active: number;
  /** A hover preview is running. The play button turns it into a full play instead of pausing it. */
  previewing: boolean;
  toggle: () => void;
  seek: (ms: number) => void;
  playRange: (startMs: number, endMs: number) => void;
  /** Play from the start (a hover preview) and stop again, without touching the Web Audio graph. It never interrupts other sound. */
  preview: (on: boolean) => void;
};

/**
 * One audio file behind a play button. The bytes are fetched with the API token into an object URL. While it plays, the
 * loudness of the real signal is read from a Web Audio analyser (created on the first press, which is a user gesture), so the
 * live strip shows what is being heard. `playRange` plays one line of a joined track and stops at its end.
 */
export function useAudioPlayer(asset: Pick<GenerateAssetRef, "asset_id" | "url"> | null, segments: Segment[] = [], options: { live?: boolean } = {}): Player {
  const live = options.live ?? true;
  const src = useAssetObjectUrl(asset ? { id: asset.asset_id, content_url: asset.url } : null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const bind = useCallback((element: HTMLAudioElement | null) => {
    if (audioRef.current) registry.delete(audioRef.current);
    audioRef.current = element;
    if (element) registry.add(element);
  }, []);
  const timeRef = useRef(0);
  const levelsRef = useRef<number[]>([]);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const contextRef = useRef<AudioContext | null>(null);
  const rangeEnd = useRef<number | null>(null);
  const segmentsRef = useRef(segments);
  const [playing, setPlaying] = useState(false);
  const [active, setActive] = useState(-1);
  const previewRef = useRef(false);
  const [previewing, setPreviewing] = useState(false);
  const markPreview = useCallback((on: boolean) => {
    previewRef.current = on;
    setPreviewing(on);
  }, []);

  useEffect(() => {
    segmentsRef.current = segments;
  });

  const connect = useCallback(() => {
    const audio = audioRef.current;
    if (!audio || contextRef.current || typeof AudioContext === "undefined") return;
    try {
      const context = new AudioContext();
      const analyser = context.createAnalyser();
      analyser.fftSize = 512;
      context.createMediaElementSource(audio).connect(analyser);
      analyser.connect(context.destination);
      contextRef.current = context;
      analyserRef.current = analyser;
    } catch {
      contextRef.current = null; // the file still plays; only the live strip is missing
    }
  }, []);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    const buffer = new Uint8Array(512);
    let frame = 0;
    let timer = 0;
    const tick = () => {
      timeRef.current = audio.currentTime;
      if (rangeEnd.current !== null && audio.currentTime >= rangeEnd.current) {
        rangeEnd.current = null;
        audio.pause();
      }
      const analyser = analyserRef.current;
      let level = 0;
      if (analyser) {
        analyser.getByteTimeDomainData(buffer);
        let sum = 0;
        for (const v of buffer) sum += ((v - 128) / 128) ** 2;
        level = Math.min(1, Math.sqrt(sum / buffer.length) * 3);
      }
      const levels = levelsRef.current;
      levels.push(level);
      if (levels.length > LIVE_SLICES) levels.shift();
      const ms = audio.currentTime * 1000;
      const line = segmentsRef.current.find((s) => ms >= s.start && ms < s.end)?.index ?? -1;
      setActive((previous) => (previous === line ? previous : line));
    };
    const loop = () => {
      tick();
      frame = requestAnimationFrame(loop);
    };
    const onPlay = () => {
      for (const other of registry) if (other !== audio) other.pause();
      setPlaying(true);
      if (reduced()) timer = window.setInterval(tick, 250);
      else frame = requestAnimationFrame(loop);
    };
    const onStop = () => {
      setPlaying(false);
      markPreview(false);
      cancelAnimationFrame(frame);
      window.clearInterval(timer);
      tick();
      levelsRef.current = [];
    };
    audio.addEventListener("play", onPlay);
    audio.addEventListener("pause", onStop);
    audio.addEventListener("ended", onStop);
    audio.addEventListener("seeked", tick);
    return () => {
      audio.removeEventListener("play", onPlay);
      audio.removeEventListener("pause", onStop);
      audio.removeEventListener("ended", onStop);
      audio.removeEventListener("seeked", tick);
      cancelAnimationFrame(frame);
      window.clearInterval(timer);
    };
  }, [src, markPreview]);

  useEffect(() => {
    const context = contextRef;
    return () => {
      void context.current?.close();
      context.current = null;
    };
  }, []);

  const start = useCallback(async () => {
    const audio = audioRef.current;
    if (!audio) return;
    if (live) connect(); // a preview made on hover has no user gesture, and a suspended context would mute the element
    try {
      await contextRef.current?.resume();
      await audio.play();
    } catch {
      /* a blocked or interrupted play leaves the button in its resting state */
    }
  }, [connect, live]);

  const toggle = useCallback(() => {
    const audio = audioRef.current;
    if (!audio) return;
    rangeEnd.current = null;
    const wasPreview = previewRef.current && !audio.paused;
    markPreview(false);
    if (wasPreview) return; // the button asked for sound: the preview that is playing carries on as a play
    if (audio.paused) void start();
    else audio.pause();
  }, [start, markPreview]);

  const seek = useCallback((ms: number) => {
    const audio = audioRef.current;
    if (!audio) return;
    audio.currentTime = Math.max(0, ms / 1000);
    timeRef.current = audio.currentTime;
  }, []);

  const playRange = useCallback(
    (startMs: number, endMs: number) => {
      const audio = audioRef.current;
      if (!audio) return;
      markPreview(false);
      audio.currentTime = startMs / 1000;
      rangeEnd.current = endMs / 1000;
      void start();
    },
    [start, markPreview],
  );

  const preview = useCallback(
    (on: boolean) => {
      const audio = audioRef.current;
      if (!audio) return;
      if (on) {
        if (!audio.paused || othersPlaying(audio)) return; // a hover never interrupts or doubles sound that is already playing
        rangeEnd.current = null;
        markPreview(true);
        audio.currentTime = 0;
        void start();
      } else if (previewRef.current) {
        // only a preview ends when the pointer leaves; a play the person asked for goes on
        markPreview(false);
        audio.pause();
        audio.currentTime = 0;
      }
    },
    [start, markPreview],
  );

  return { src, bind, playing, timeRef, levelsRef, active, previewing, toggle, seek, playRange, preview };
}

/** The hidden element that carries the player's audio. Render it once next to the controls. */
export function PlayerAudio({ bind, src }: { bind: Player["bind"]; src: Player["src"] }) {
  return <audio ref={bind} src={src ?? undefined} preload="auto" className="hidden" />;
}

function color(element: HTMLElement, name: string, fallback: string) {
  return getComputedStyle(element).getPropertyValue(name).trim() || fallback;
}

/**
 * The track as 96 bars from the audio's own loudness (computed on the server from the samples), the played part in ember,
 * the lines of a voice-over as bands, a playhead you can drag or move with the arrow keys.
 */
export function Waveform({
  peaks,
  durationMs,
  player,
  segments = [],
  className,
  label,
}: {
  peaks: number[];
  durationMs: number;
  player: Player;
  segments?: Segment[];
  className?: string;
  label: string;
}) {
  const ref = useRef<HTMLCanvasElement>(null);
  const [width, setWidth] = useState(0);
  const [second, setSecond] = useState(0); // whole seconds, for assistive technology; the picture itself is drawn from timeRef
  const { timeRef, playing, seek } = player;

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const observer = new ResizeObserver(() => setWidth(canvas.clientWidth));
    observer.observe(canvas);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas || !width) return;
    const dpr = window.devicePixelRatio || 1;
    const height = canvas.clientHeight;
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    const g = canvas.getContext("2d");
    if (!g) return;
    const base = color(canvas, "--border-strong", "#888");
    const played = color(canvas, "--pop", "#e55");
    const band = color(canvas, "--ink", "#000");
    let frame = 0;
    const draw = () => {
      const t = (timeRef.current ?? 0) * 1000;
      const progress = durationMs > 0 ? Math.min(1, t / durationMs) : 0;
      const whole = Math.min(Math.round(durationMs / 1000), Math.floor(t / 1000));
      setSecond((previous) => (previous === whole ? previous : whole));
      g.setTransform(dpr, 0, 0, dpr, 0, 0);
      g.clearRect(0, 0, width, height);
      for (const s of segments) {
        g.globalAlpha = 0.07;
        g.fillStyle = band;
        g.fillRect((s.start / durationMs) * width, 0, ((s.end - s.start) / durationMs) * width, height);
      }
      const gap = 2;
      const barW = Math.max(1.5, width / peaks.length - gap);
      peaks.forEach((p, i) => {
        const x = (i / peaks.length) * width;
        const h = Math.max(3, (p / 100) * (height - 6));
        g.globalAlpha = 1;
        g.fillStyle = x / width <= progress ? played : base;
        g.beginPath();
        g.roundRect(x, (height - h) / 2, barW, h, Math.min(2, barW / 2));
        g.fill();
      });
      g.globalAlpha = 1;
      g.fillStyle = played;
      g.fillRect(Math.round(progress * width) - 1, 0, 2, height);
      if (playing && !reduced()) frame = requestAnimationFrame(draw);
    };
    draw();
    // Motion is reduced, not state: without animation frames the playhead and played bars still move four times a second, and a
    // seek while paused still moves the playhead.
    const still = !playing || reduced();
    const timer = still ? window.setInterval(draw, playing ? 250 : 400) : 0;
    return () => {
      cancelAnimationFrame(frame);
      window.clearInterval(timer);
    };
  }, [peaks, durationMs, segments, width, playing, timeRef]);

  const move = (clientX: number) => {
    const box = ref.current?.getBoundingClientRect();
    if (box) seek(Math.min(1, Math.max(0, (clientX - box.left) / box.width)) * durationMs);
  };
  return (
    <canvas
      ref={ref}
      role="slider"
      tabIndex={0}
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={Math.round(durationMs / 1000)}
      aria-valuenow={second}
      aria-valuetext={`${mmss(second * 1000)} of ${mmss(durationMs)}. Use the arrow keys to move.`}
      onPointerDown={(e) => {
        e.currentTarget.setPointerCapture(e.pointerId);
        move(e.clientX);
      }}
      onPointerMove={(e) => e.buttons === 1 && move(e.clientX)}
      onKeyDown={(e) => {
        const step = e.key === "ArrowRight" ? 1000 : e.key === "ArrowLeft" ? -1000 : 0;
        if (step) {
          e.preventDefault();
          seek(Math.min(durationMs, Math.max(0, (timeRef.current ?? 0) * 1000 + step)));
        }
      }}
      className={cn("block h-24 w-full cursor-pointer touch-pan-y rounded-lg", className)}
    />
  );
}

/** What is playing right now, as a scrolling strip of loudness read from the real signal. Flat when nothing plays. */
export function LiveStrip({ player, className }: { player: Player; className?: string }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const { playing, levelsRef } = player;

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
    const g = canvas.getContext("2d");
    if (!g) return;
    const ink = color(canvas, "--pink", "#d36");
    const rest = color(canvas, "--border-strong", "#888");
    let frame = 0;
    const draw = () => {
      g.setTransform(dpr, 0, 0, dpr, 0, 0);
      g.clearRect(0, 0, w, h);
      const levels = levelsRef.current ?? [];
      const slot = w / LIVE_SLICES;
      g.globalAlpha = 0.45;
      g.fillStyle = rest;
      g.fillRect(0, h / 2 - 0.5, w, 1); // the flat line a silent strip rests on
      for (let i = 0; i < LIVE_SLICES; i++) {
        const level = playing ? (levels[levels.length - LIVE_SLICES + i] ?? 0) : 0;
        if (level <= 0.02) continue;
        g.fillStyle = ink;
        g.globalAlpha = 0.4 + 0.6 * (i / LIVE_SLICES);
        g.fillRect(i * slot, (h - Math.max(3, level * h)) / 2, Math.max(1.5, slot - 2), Math.max(3, level * h));
      }
      if (playing && !reduced()) frame = requestAnimationFrame(draw);
    };
    draw();
    return () => cancelAnimationFrame(frame);
  }, [playing, levelsRef]);

  return <canvas ref={ref} aria-hidden className={cn("block h-8 w-full", className)} />;
}

/** Play or pause, the position and the length. */
export function PlayButton({ player, durationMs, label }: { player: Player; durationMs: number; label: string }) {
  const [now, setNow] = useState(0);
  const { playing, timeRef, src } = player;
  useEffect(() => {
    // the position is read whether or not it is playing, so a pause, a line that ended or a seek shows where the next Play resumes
    if (!src) return;
    const id = window.setInterval(() => setNow(timeRef.current ?? 0), 250);
    return () => window.clearInterval(id);
  }, [src, timeRef]);
  return (
    <button
      type="button"
      onClick={player.toggle}
      disabled={!player.src}
      aria-label={`${playing ? "Pause" : "Play"} ${label}`}
      className="inline-flex h-11 min-w-11 items-center justify-center gap-2 rounded-full bg-primary px-4 text-primary-foreground shadow-clay outline-none hover:bg-accent-hover focus-visible:ring-3 focus-visible:ring-ring/30 active:shadow-clay-pressed disabled:opacity-50"
    >
      {playing ? <Pause aria-hidden className="size-4" /> : <Play aria-hidden className="size-4" />}
      <span aria-hidden className="type-meta tabular-nums text-inherit">
        {mmss(now * 1000)} / {mmss(durationMs)}
      </span>
    </button>
  );
}
