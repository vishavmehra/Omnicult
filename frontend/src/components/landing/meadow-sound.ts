"use client";

/*
 * The meadow's sounds, synthesised with the Web Audio API (no audio files): the grasshopper's stridulation, a "trrr" of
 * band-passed noise pulses in short irregular syllables, whenever it rubs a hind leg; the crackle of its wings on a long
 * leap; the bee's soft low buzz while it flies; the dragonfly's faint wing flutter on its darts. Each sound is cued by
 * the creature that makes it, so the timing is as sparse and irregular as their behaviour, and panned to where it is.
 *
 * Quiet by design: master gain 0.06, gentle attacks and releases. Browsers block autoplay, so no AudioContext exists
 * until the visitor's first click, tap or key press on the landing page; the header toggle turns the sounds off and on
 * and the choice is remembered. Suspended while the tab is hidden; closed when the landing unmounts.
 */

const KEY = "omnicult.meadow-sound";
const MASTER = 0.06;

type Voice = { gain: GainNode; pan: StereoPannerNode; level: number };
type Engine = { ctx: AudioContext; master: GainNode; noise: AudioBuffer; bee: Voice; dragonfly: Voice };

let enabled = true;
let loaded = false;
let engine: Engine | null = null;
let attached = 0;
const listeners = new Set<() => void>();

function load() {
  if (loaded) return;
  loaded = true;
  try {
    enabled = localStorage.getItem(KEY) !== "off";
  } catch {
    // Storage blocked: keep the default.
  }
}

export function soundOn() {
  load();
  return enabled;
}

export function subscribeSound(fn: () => void) {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

export function setSound(on: boolean) {
  load();
  enabled = on;
  try {
    localStorage.setItem(KEY, on ? "on" : "off");
  } catch {
    // Not remembered, still applied.
  }
  if (on) wake();
  else void engine?.ctx.suspend();
  listeners.forEach((fn) => fn());
}

/** Pan for a creature at viewport x. */
export const panAt = (x: number, w: number) => Math.max(-1, Math.min(1, (x / Math.max(1, w)) * 2 - 1)) * 0.7;

function voice(ctx: AudioContext, master: GainNode): Voice {
  const gain = ctx.createGain();
  gain.gain.value = 0;
  const pan = ctx.createStereoPanner();
  gain.connect(pan).connect(master);
  return { gain, pan, level: 0 };
}

function build(): Engine | null {
  const AC = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!AC) return null;
  const ctx = new AC();
  const master = ctx.createGain();
  master.gain.value = MASTER;
  master.connect(ctx.destination);
  const noise = ctx.createBuffer(1, ctx.sampleRate, ctx.sampleRate);
  const data = noise.getChannelData(0);
  for (let i = 0; i < data.length; i++) data[i] = Math.random() * 2 - 1;

  // Bee: two slightly detuned sawtooths with a slow pitch wobble, low-passed into a soft hum.
  const bee = voice(ctx, master);
  const hum = ctx.createBiquadFilter();
  hum.type = "lowpass";
  hum.frequency.value = 640;
  hum.connect(bee.gain);
  for (const f of [212, 217.5]) {
    const o = ctx.createOscillator();
    o.type = "sawtooth";
    o.frequency.value = f;
    const wobble = ctx.createOscillator();
    wobble.frequency.value = 5 + Math.random() * 2;
    const depth = ctx.createGain();
    depth.gain.value = 3;
    wobble.connect(depth).connect(o.frequency);
    o.connect(hum);
    o.start();
    wobble.start();
  }

  // Dragonfly: low band-passed noise, amplitude-modulated at its wingbeat (about 27 Hz).
  const dragonfly = voice(ctx, master);
  const air = ctx.createBufferSource();
  air.buffer = noise;
  air.loop = true;
  const band = ctx.createBiquadFilter();
  band.type = "bandpass";
  band.frequency.value = 380;
  band.Q.value = 0.9;
  const am = ctx.createGain();
  am.gain.value = 0.5;
  const beat = ctx.createOscillator();
  beat.frequency.value = 27;
  const beatDepth = ctx.createGain();
  beatDepth.gain.value = 0.5;
  beat.connect(beatDepth).connect(am.gain);
  air.connect(band).connect(am).connect(dragonfly.gain);
  air.start();
  beat.start();

  return { ctx, master, noise, bee, dragonfly };
}

/** Starts or resumes audio. Only ever called from a click or key press, as browsers require. */
function wake() {
  if (!enabled || !attached || document.hidden) return;
  if (!engine) engine = build();
  if (engine?.ctx.state === "suspended") void engine.ctx.resume();
}

const live = () => (engine && engine.ctx.state === "running" ? engine : null);

function drive(v: Voice, level: number, pan: number) {
  const e = live();
  if (!e) return;
  const now = e.ctx.currentTime;
  if (Math.abs(level - v.level) > 0.02) {
    v.gain.gain.setTargetAtTime(level, now, level > v.level ? 0.09 : 0.3);
    v.level = level;
  }
  if (Math.abs(pan - v.pan.pan.value) > 0.04) v.pan.pan.setTargetAtTime(pan, now, 0.15);
}

/** The bee's buzz: 0 silent (feeding), 1 darting. */
export function buzz(level: number, pan: number) {
  if (engine) drive(engine.bee, level * 0.45, pan);
}

/** The dragonfly's wing flutter: 0 perched, 1 darting. */
export function flutter(level: number, pan: number) {
  if (engine) drive(engine.dragonfly, level * 0.55, pan);
}

/** A train of short band-passed noise pulses; `gap` gives the time to the next pulse. */
function train(pan: number, seconds: number, freq: number, q: number, peak: number, gap: () => number) {
  const e = live();
  if (!e) return;
  const { ctx } = e;
  const src = ctx.createBufferSource();
  src.buffer = e.noise;
  src.loop = true;
  const filter = ctx.createBiquadFilter();
  filter.type = "bandpass";
  filter.frequency.value = freq;
  filter.Q.value = q;
  const g = ctx.createGain();
  g.gain.value = 0;
  const p = ctx.createStereoPanner();
  p.pan.value = pan;
  src.connect(filter).connect(g).connect(p).connect(e.master);
  const t0 = ctx.currentTime + 0.03;
  const end = t0 + seconds;
  // Pulses swell in over the first fifth and fade over the last, so the bout never starts or stops hard.
  for (let t = t0; t < end; t += gap()) {
    const k = (t - t0) / seconds;
    const swell = Math.min(1, k * 5, (1 - k) * 5);
    g.gain.setValueAtTime(0, t);
    g.gain.linearRampToValueAtTime(peak * swell * (0.7 + Math.random() * 0.3) + 0.002, t + 0.004);
    g.gain.exponentialRampToValueAtTime(0.001, t + 0.02);
  }
  g.gain.setValueAtTime(0, end + 0.03);
  src.start(t0);
  src.stop(end + 0.06);
  src.onended = () => p.disconnect();
}

/** The grasshopper's "trrr": pulses about 30 a second in syllables of 3 to 8, with irregular gaps. */
export function stridulate(pan: number, seconds: number) {
  const period = 1 / (26 + Math.random() * 10);
  let left = 0;
  train(pan, seconds, 4800 + Math.random() * 1600, 6, 0.6, () => {
    if (left-- > 0) return period * (0.85 + Math.random() * 0.3);
    left = 2 + Math.floor(Math.random() * 6);
    return period + 0.04 + Math.random() * 0.1;
  });
}

/** The dry crackle of a band-winged grasshopper's wings in flight. */
export function crackle(pan: number, seconds: number) {
  train(pan, seconds, 2400 + Math.random() * 800, 1.4, 0.3, () => 0.014 + Math.random() * 0.04);
}

/**
 * Wires the meadow's audio to the landing page for as long as it is mounted: the first click or key press starts it
 * (not a click on the sound toggle, which decides for itself), a hidden tab suspends it, unmounting closes it.
 */
export function attachSound() {
  load();
  attached++;
  const onGesture = (e: Event) => {
    if (!(e.target instanceof Element && e.target.closest("[data-sound-toggle]"))) wake();
  };
  const onVisibility = () => {
    if (!engine) return;
    if (document.hidden) void engine.ctx.suspend();
    else if (enabled) void engine.ctx.resume();
  };
  window.addEventListener("click", onGesture, true);
  window.addEventListener("keydown", onGesture, true);
  document.addEventListener("visibilitychange", onVisibility);
  return () => {
    attached--;
    window.removeEventListener("click", onGesture, true);
    window.removeEventListener("keydown", onGesture, true);
    document.removeEventListener("visibilitychange", onVisibility);
    if (!attached && engine) {
      void engine.ctx.close();
      engine = null;
    }
  };
}
