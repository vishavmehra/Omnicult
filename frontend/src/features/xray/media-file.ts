import type { AssetKind } from "./api";

export const SIDECAR_MAX_BYTES = 200 * 1024;
export const SIDECAR_ACCEPT = ".srt,.vtt,.txt,text/plain,text/vtt,application/x-subrip";
export const MEDIA_ACCEPT =
  "image/png,image/jpeg,image/webp,video/mp4,video/quicktime,video/webm,audio/mpeg,audio/wav,audio/x-wav,audio/mp4,audio/x-m4a,.png,.jpg,.jpeg,.webp,.mp4,.mov,.webm,.mp3,.wav,.m4a";

export type Sniffed = { kind: AssetKind; format: string };

/**
 * The file's kind from its first bytes, as the server does it: a renamed file keeps its real type. This only picks the
 * `kind` field and gives early feedback; the server re-checks the bytes and is the authority.
 */
export async function sniff(file: Blob, filename: string): Promise<Sniffed | null> {
  const b = new Uint8Array(await file.slice(0, 16).arrayBuffer());
  const ascii = (from: number, to: number) => String.fromCharCode(...b.slice(from, to));
  if (b[0] === 0x89 && ascii(1, 4) === "PNG") return { kind: "image", format: "PNG" };
  if (b[0] === 0xff && b[1] === 0xd8 && b[2] === 0xff) return { kind: "image", format: "JPEG" };
  if (ascii(0, 4) === "RIFF" && ascii(8, 12) === "WEBP") return { kind: "image", format: "WebP" };
  if (ascii(0, 4) === "RIFF" && ascii(8, 12) === "WAVE") return { kind: "audio", format: "WAV" };
  if (ascii(4, 8) === "ftyp") {
    const brand = ascii(8, 12);
    if (brand === "M4A " || /\.m4a$/i.test(filename)) return { kind: "audio", format: "M4A" };
    return { kind: "video", format: brand === "qt  " ? "MOV" : "MP4" };
  }
  if (b[0] === 0x1a && b[1] === 0x45 && b[2] === 0xdf && b[3] === 0xa3) return { kind: "video", format: "WebM" };
  if (ascii(0, 3) === "ID3" || (b[0] === 0xff && (b[1] & 0xe0) === 0xe0)) return { kind: "audio", format: "MP3" };
  return null;
}

/** Length of a video or audio file from its own metadata, in ms; null when the browser cannot read it in time. */
export function readDuration(file: Blob, kind: AssetKind): Promise<number | null> {
  if (kind === "image") return Promise.resolve(null);
  return new Promise((resolve) => {
    const el = document.createElement(kind === "video" ? "video" : "audio");
    const url = URL.createObjectURL(file);
    const done = (value: number | null) => {
      clearTimeout(timer);
      URL.revokeObjectURL(url);
      el.removeAttribute("src");
      resolve(value);
    };
    const timer = setTimeout(() => done(null), 5000);
    el.preload = "metadata";
    el.onloadedmetadata = () => done(Number.isFinite(el.duration) ? Math.round(el.duration * 1000) : null);
    el.onerror = () => done(null);
    el.src = url;
  });
}

export function plural(n: number, word: string) {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}
