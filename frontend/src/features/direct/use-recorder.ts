"use client";

import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";

/** The longest clip: the API refuses more than 60 seconds, and an instruction is a sentence, not a meeting. */
export const MAX_SECONDS = 60;
/** Shorter than this is a bump of the key, not speech. */
const MIN_MS = 500;
/** What MediaRecorder produces: WebM/Opus in Chrome and Edge, Ogg/Opus in Firefox, MP4 in Safari. The API accepts all of them. */
const MIME_TYPES = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"];

export type RecorderState = "idle" | "requesting" | "recording" | "denied" | "error";

const noop = () => () => {};
function detect() {
  return window.isSecureContext && Boolean(navigator.mediaDevices?.getUserMedia) && typeof MediaRecorder !== "undefined";
}

/** Whether this browser and page can record at all. The server render assumes it can, so nothing flickers when it can. */
export function useRecordingSupport() {
  return useSyncExternalStore(noop, detect, () => true);
}

export const extensionOf = (mime: string) => (mime.includes("ogg") ? "ogg" : mime.includes("mp4") ? "m4a" : "webm");

const explain = (name: string) =>
  name === "NotFoundError"
    ? "No microphone was found on this device."
    : name === "NotReadableError"
      ? "The microphone is being used by another application."
      : "The microphone could not be started.";

/**
 * Push-to-talk recording with MediaRecorder. The microphone is asked for only when `start` is called (a press of the
 * button), never on load. `stop` ends the clip and hands it to `onClip`; releasing before the permission prompt is answered
 * records nothing. The stream is always released, so the browser's recording indicator goes out as soon as the clip ends.
 */
export function useRecorder(onClip: (clip: Blob, mime: string) => void) {
  const supported = useRecordingSupport();
  const [state, setState] = useState<RecorderState>("idle");
  const [seconds, setSeconds] = useState(0);
  const [message, setMessage] = useState<string | null>(null);
  const live = useRef({ recorder: null as MediaRecorder | null, stream: null as MediaStream | null, timer: 0, busy: false, released: false, unmounted: false });
  const clipHandler = useRef(onClip);
  useEffect(() => {
    clipHandler.current = onClip;
  });

  const release = useCallback(() => {
    const s = live.current;
    window.clearInterval(s.timer);
    s.stream?.getTracks().forEach((t) => t.stop());
    s.stream = null;
    s.recorder = null;
    s.busy = false;
  }, []);

  const stop = useCallback(() => {
    const s = live.current;
    s.released = true;
    if (s.recorder?.state === "recording") s.recorder.stop();
  }, []);

  const start = useCallback(async () => {
    const s = live.current;
    if (!supported || s.busy) return;
    s.busy = true;
    s.released = false;
    setMessage(null);
    setState("requesting");
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
    } catch (error) {
      s.busy = false;
      const name = error instanceof DOMException ? error.name : "";
      if (name === "NotAllowedError" || name === "SecurityError") setState("denied");
      else {
        setState("error");
        setMessage(explain(name));
      }
      return;
    }
    if (s.released || s.unmounted) {
      // Let go before the prompt was answered: nothing was said, so nothing is recorded.
      stream.getTracks().forEach((t) => t.stop());
      s.busy = false;
      if (!s.unmounted) {
        setState("idle");
        setMessage("Hold the button while you speak.");
      }
      return;
    }
    const mime = MIME_TYPES.find((t) => MediaRecorder.isTypeSupported?.(t));
    const chunks: Blob[] = [];
    let recorder: MediaRecorder;
    try {
      recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
    } catch {
      stream.getTracks().forEach((t) => t.stop());
      s.busy = false;
      setState("error");
      setMessage("This browser could not start a recording.");
      return;
    }
    const startedAt = Date.now();
    recorder.ondataavailable = (e) => {
      if (e.data.size > 0) chunks.push(e.data);
    };
    recorder.onerror = () => {
      release();
      setState("error");
      setMessage("The recording failed. Try again, or type the instruction.");
    };
    recorder.onstop = () => {
      const type = recorder.mimeType || mime || "audio/webm";
      const long = Date.now() - startedAt >= MIN_MS;
      release();
      if (s.unmounted) return;
      setState("idle");
      if (!long || chunks.length === 0) setMessage("That was too short. Hold the button while you speak.");
      else clipHandler.current(new Blob(chunks, { type }), type);
    };
    s.stream = stream;
    s.recorder = recorder;
    recorder.start();
    setSeconds(0);
    setState("recording");
    s.timer = window.setInterval(() => {
      const elapsed = Math.floor((Date.now() - startedAt) / 1000);
      setSeconds(elapsed);
      if (elapsed >= MAX_SECONDS) stop();
    }, 250);
    if (s.released) stop(); // let go while the recorder was starting
  }, [supported, release, stop]);

  useEffect(() => {
    const s = live.current;
    s.unmounted = false;
    return () => {
      s.unmounted = true;
      s.released = true;
      if (s.recorder?.state === "recording") s.recorder.stop();
      release();
    };
  }, [release]);

  return { supported, state, seconds, message, start, stop };
}
