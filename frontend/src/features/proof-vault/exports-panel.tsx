"use client";

import { Check, Clock3, Copy, Download, Info, LoaderCircle, Link2 } from "lucide-react";
import { useState } from "react";

import { ErrorState } from "@/components/states";
import { Button, buttonVariants } from "@/components/ui/button";
import { useNow } from "@/hooks/use-now";
import { formatDateTime, formatElapsed } from "@/lib/format";
import { cn } from "@/lib/utils";

import { absoluteDownloadUrl, downloadReport, EXPORT_LABEL, useCreateStoredExport } from "./api";
import { SELECT_CLASS } from "./parts";
import type { ExportFormat, ProofExport, ProofReport } from "./types";

const FORMATS: ExportFormat[] = ["pdf", "json", "markdown"];

/** Unicode blocks of the Indic scripts the product handles, so the notice can name the ones in this snapshot. */
const SCRIPTS: [string, RegExp][] = [
  ["Devanagari", /[\u0900-\u097F]/],
  ["Bengali", /[\u0980-\u09FF]/],
  ["Gurmukhi", /[\u0A00-\u0A7F]/],
  ["Gujarati", /[\u0A80-\u0AFF]/],
  ["Odia", /[\u0B00-\u0B7F]/],
  ["Tamil", /[\u0B80-\u0BFF]/],
  ["Telugu", /[\u0C00-\u0C7F]/],
  ["Kannada", /[\u0C80-\u0CFF]/],
  ["Malayalam", /[\u0D00-\u0D7F]/],
];

function formatBytes(n: number) {
  return n < 1024 ? `${n} B` : n < 1024 * 1024 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1024 / 1024).toFixed(1)} MB`;
}

/** The transliteration notice comes first, before any export button is pressed. */
function TransliterationNotice({ report }: { report: ProofReport }) {
  const text = JSON.stringify(report.sections);
  const found = SCRIPTS.filter(([, re]) => re.test(text)).map(([name]) => name);
  return (
    <p className="flex max-w-[72ch] items-start gap-2 text-[13px] text-ink-body">
      <Info aria-hidden className="mt-0.5 size-4 shrink-0 text-info" />
      <span>
        <span className="font-medium text-ink">Before you export a PDF. </span>
        The PDF shows regional-script text as an approximate Latin transliteration and says so on the page.
        {found.length > 0 ? ` This snapshot contains ${found.join(", ")} text, so its PDF will show that text transliterated.` : " This snapshot has no regional-script text, so its PDF shows nothing transliterated."}{" "}
        JSON and Markdown keep the original script, so use them when exact wording matters.
      </span>
    </p>
  );
}

function StoredExport({ exported, onNew }: { exported: ProofExport; onNew: () => void }) {
  const now = useNow(true, 1000);
  const [copied, setCopied] = useState(false);
  const remaining = Date.parse(exported.expires_at) - now;
  const expired = remaining <= 0;
  const url = absoluteDownloadUrl(exported.download_url);

  async function copy() {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  }

  return (
    <div className="space-y-2.5 rounded-card border border-border bg-surface-muted/50 px-4 py-3">
      <p className="type-ledger flex flex-wrap items-baseline gap-x-3 gap-y-0.5 text-[13px] text-ink-body">
        <span className="font-medium text-ink">{exported.filename}</span>
        <span className="text-ink-muted">
          {EXPORT_LABEL[exported.format]} · {formatBytes(exported.byte_size)}
        </span>
        <span className="font-mono text-[11.5px] text-ink-muted" title={`SHA-256 ${exported.sha256}`}>
          sha256 {exported.sha256.slice(0, 12)}
        </span>
      </p>
      <p className={cn("flex items-center gap-1.5 text-[13px]", expired ? "text-warning" : "text-ink-body")} role="status">
        <Clock3 aria-hidden className="size-4 shrink-0" />
        {expired ? (
          <>This link expired at {formatDateTime(exported.expires_at)}. Create a new one.</>
        ) : (
          <>
            Link expires at {formatDateTime(exported.expires_at)}, in <span className="tabular-nums">{formatElapsed(remaining)}</span>.
          </>
        )}
      </p>
      <p className="max-w-[72ch] text-[12.5px] text-ink-muted">Anyone who has this link can download the file until it expires. It needs no sign-in, so share it with care.</p>
      <div className="flex flex-wrap gap-2">
        {expired ? (
          <span aria-disabled className={cn(buttonVariants({ variant: "outline" }), "pointer-events-none opacity-50")}>
            <Download aria-hidden />
            Download
          </span>
        ) : (
          <a href={url} download={exported.filename} className={buttonVariants({ variant: "outline" })}>
            <Download aria-hidden />
            Download
          </a>
        )}
        <Button variant="outline" onClick={() => void copy()} disabled={expired}>
          {copied ? <Check aria-hidden /> : <Copy aria-hidden />}
          {copied ? "Link copied" : "Copy link"}
        </Button>
        <Button variant="ghost" onClick={onNew}>
          Create another link
        </Button>
      </div>
      {exported.notices.length > 0 && (
        <ul className="list-disc space-y-0.5 pl-5 text-[12.5px] text-ink-secondary marker:text-ink-muted">
          {exported.notices.map((n, i) => (
            <li key={i}>{n}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Direct downloads (through the signed-in request) and a stored export with a short-lived link. */
export function ExportsPanel({ report }: { report: ProofReport }) {
  const [busy, setBusy] = useState<ExportFormat | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [format, setFormat] = useState<ExportFormat>("pdf");
  const [exported, setExported] = useState<ProofExport | null>(null);
  const stored = useCreateStoredExport(report.id);

  async function download(f: ExportFormat) {
    setBusy(f);
    setError(null);
    try {
      await downloadReport(report, f);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(null);
    }
  }

  return (
    <section aria-labelledby="exports" className="space-y-3 rounded-card border border-border bg-surface px-4 py-4">
      <h3 id="exports" className="text-[15px] font-semibold text-ink">
        Export this snapshot
      </h3>
      <TransliterationNotice report={report} />
      <div className="flex flex-wrap gap-2" role="group" aria-label="Download now">
        {FORMATS.map((f) => (
          <Button key={f} variant="outline" onClick={() => void download(f)} disabled={busy !== null}>
            {busy === f ? <LoaderCircle aria-hidden className="animate-spin motion-reduce:animate-none" /> : <Download aria-hidden />}
            {busy === f ? `Preparing ${EXPORT_LABEL[f]}…` : EXPORT_LABEL[f]}
          </Button>
        ))}
      </div>
      {error != null && <ErrorState error={error} onRetry={() => setError(null)} />}

      <div className="space-y-2.5 border-t border-border pt-3">
        <h4 className="text-[13.5px] font-semibold text-ink">Keep a copy with a link</h4>
        <p className="max-w-[72ch] text-[12.5px] text-ink-secondary">
          A stored export is saved by the API and shared through a short-lived link that works without signing in. Its expiry is shown once the link exists.
        </p>
        {exported ? (
          <StoredExport exported={exported} onNew={() => setExported(null)} />
        ) : (
          <div className="flex flex-wrap items-center gap-2">
            <label htmlFor="stored-format" className="sr-only">
              Format of the stored export
            </label>
            <select id="stored-format" value={format} onChange={(e) => setFormat(e.target.value as ExportFormat)} className={SELECT_CLASS}>
              {FORMATS.map((f) => (
                <option key={f} value={f}>
                  {EXPORT_LABEL[f]}
                </option>
              ))}
            </select>
            <Button
              variant="outline"
              disabled={stored.isPending}
              onClick={() => stored.mutate(format, { onSuccess: setExported })}
            >
              {stored.isPending ? <LoaderCircle aria-hidden className="animate-spin motion-reduce:animate-none" /> : <Link2 aria-hidden />}
              {stored.isPending ? "Storing…" : "Create download link"}
            </Button>
          </div>
        )}
        {stored.error && <ErrorState error={stored.error} onRetry={() => stored.reset()} />}
      </div>
    </section>
  );
}
