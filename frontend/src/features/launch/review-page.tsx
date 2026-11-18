"use client";

import { useQuery } from "@tanstack/react-query";
import { CircleCheck, Clock3, LoaderCircle, MessageSquareText, Send, ShieldCheck } from "lucide-react";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { Tag } from "@/components/evidence/badges";
import { ThemeToggle } from "@/components/shell/theme-toggle";
import { Wordmark } from "@/components/shell/wordmark";
import { ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Textarea } from "@/components/ui/textarea";
import { ApiError } from "@/lib/api/errors";
import { formatDateTime } from "@/lib/format";

import { fetchReviewCreative, useReviewPage, useSubmitReview, type ReviewDecision, type ReviewItemView, type ReviewReceipt } from "./delivery-api";

const KIND_LABEL: Record<string, string> = { headline: "Headline", body: "Body", cta: "Call to action", tagline: "Tagline", voiceover: "Voice-over", caption: "Caption" };

const CHOICES: { value: ReviewDecision; label: string; help: string }[] = [
  { value: "approve", label: "Approve", help: "This is right for the region as it stands." },
  { value: "request_changes", label: "Ask for changes", help: "Tell the team what to change before it goes out." },
  { value: "reject", label: "Reject", help: "This should not go out in this region." },
  { value: "comment", label: "Comment only", help: "A note, without a decision." },
];

const RECEIPT_WORD: Record<ReviewDecision, string> = { approve: "Approve", request_changes: "Changes requested", reject: "Reject", comment: "Comment" };

/** One creative file, fetched with the secret in a header and shown from an object URL (the file's own address never carries the secret). */
function Creative({ secret, creative }: { secret: string; creative: ReviewItemView["creatives"][number] }) {
  const file = useQuery({ queryKey: ["review", "creative", creative.id], queryFn: () => fetchReviewCreative(secret, creative.id), retry: false, staleTime: Infinity });
  useEffect(() => {
    const url = file.data;
    return () => {
      if (url) URL.revokeObjectURL(url);
    };
  }, [file.data]);
  return (
    <figure className="space-y-1.5">
      <div className="overflow-hidden rounded-lg border border-border bg-surface-muted">
        {file.isPending ? (
          <LoadingState label={`Loading ${creative.label}…`} className="py-10" />
        ) : file.error || !file.data ? (
          <p className="px-4 py-8 text-[13px] text-ink-secondary">This file could not be loaded.</p>
        ) : creative.kind === "image" ? (
          // eslint-disable-next-line @next/next/no-img-element -- a blob URL of a private file: next/image cannot optimise it
          <img src={file.data} alt={creative.label} className="mx-auto max-h-[28rem] w-auto max-w-full" />
        ) : creative.kind === "video" ? (
          <video src={file.data} controls preload="metadata" className="mx-auto max-h-[28rem] max-w-full" aria-label={creative.label} />
        ) : (
          <audio src={file.data} controls className="w-full" aria-label={creative.label} />
        )}
      </div>
      <figcaption className="type-meta">
        {creative.label}
        {creative.width && creative.height ? ` · ${creative.width} by ${creative.height}` : ""}
      </figcaption>
    </figure>
  );
}

function ResponseForm({ secret, item, region }: { secret: string; item: ReviewItemView; region: string }) {
  const submit = useSubmitReview(secret);
  const [decision, setDecision] = useState<ReviewDecision>("approve");
  const [comment, setComment] = useState("");
  const [name, setName] = useState("");
  const [receipts, setReceipts] = useState<ReviewReceipt[]>([]);
  const needsComment = decision !== "approve";
  const ready = !submit.isPending && (!needsComment || comment.trim().length > 0);
  const id = `${item.version_id}-${region}`;

  function send() {
    submit.mutate(
      { version_id: item.version_id, region_code: region, decision, comment: comment.trim() || null, reviewer_name: name.trim() || null },
      {
        onSuccess: (receipt) => {
          setReceipts((r) => [receipt, ...r]);
          setComment("");
          setDecision("approve");
        },
      },
    );
  }

  return (
    <div className="space-y-4 border-t border-border pt-4">
      {receipts.length > 0 && (
        <ul className="space-y-1.5" aria-label="What you have sent" aria-live="polite">
          {receipts.map((r) => (
            <li key={r.id} className="flex items-start gap-2 rounded-lg border border-success/40 bg-success-soft/40 px-3 py-2 text-[13.5px] text-ink">
              <CircleCheck aria-hidden className="mt-0.5 size-4 shrink-0 text-success" />
              <span>
                Recorded: {RECEIPT_WORD[r.decision]}, {r.reviewer_kind === "named" ? "with the name you typed" : "anonymously"}, at {formatDateTime(r.recorded_at)}. Thank you.
              </span>
            </li>
          ))}
        </ul>
      )}
      <fieldset className="space-y-2">
        <legend className="text-[13.5px] font-semibold text-ink">{receipts.length > 0 ? "Add another response" : "Your response"}</legend>
        <RadioGroup value={decision} onValueChange={(v) => setDecision(v as ReviewDecision)} aria-label={`Response to ${item.version_label}`} className="grid gap-2 sm:grid-cols-2">
          {CHOICES.map((c) => (
            <label key={c.value} className="flex cursor-pointer items-start gap-2.5 rounded-lg border border-border px-3 py-2 has-[[data-checked]]:border-border-strong has-[[data-checked]]:bg-surface-raised">
              <RadioGroupItem value={c.value} className="mt-0.5" />
              <span className="min-w-0">
                <span className="block text-[14px] font-medium text-ink">{c.label}</span>
                <span className="block text-[12.5px] text-ink-secondary">{c.help}</span>
              </span>
            </label>
          ))}
        </RadioGroup>
      </fieldset>
      <div className="space-y-1.5">
        <label htmlFor={`comment-${id}`} className="block text-[13px] font-medium text-ink">
          {needsComment ? "What would you change, or why?" : "A note"} {needsComment ? <span className="text-danger">*</span> : <span className="font-normal text-ink-secondary">(optional)</span>}
        </label>
        <Textarea id={`comment-${id}`} value={comment} maxLength={1000} onChange={(e) => setComment(e.target.value)} lang="en" />
      </div>
      <div className="space-y-1.5">
        <label htmlFor={`name-${id}`} className="block text-[13px] font-medium text-ink">
          Your name <span className="font-normal text-ink-secondary">(optional)</span>
        </label>
        <Input id={`name-${id}`} value={name} maxLength={80} autoComplete="name" onChange={(e) => setName(e.target.value)} className="max-w-xs" />
        <p className="text-[12px] text-ink-muted">Shown to the sender as you type it. It is not checked. Leave it empty to respond anonymously.</p>
      </div>
      {submit.error && <ErrorState error={submit.error} onRetry={send} />}
      <Button disabled={!ready} onClick={send}>
        {submit.isPending ? <LoaderCircle aria-hidden className="animate-spin motion-reduce:animate-none" /> : <Send aria-hidden />}
        {submit.isPending ? "Sending…" : "Send response"}
      </Button>
    </div>
  );
}

function ItemCard({ secret, item }: { secret: string; item: ReviewItemView }) {
  const titleId = `item-${item.version_id}-${item.region_code}`;
  return (
    <article aria-labelledby={titleId} className="clay overflow-hidden rounded-card border border-border">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-b border-border px-5 py-3.5">
        <h2 id={titleId} className="type-title text-[21px] text-ink">
          {item.version_label}
        </h2>
        <Tag className="border-border text-ink-secondary">{item.region_name}</Tag>
        {item.language && <Tag className="border-border font-mono text-ink-secondary">{item.language}</Tag>}
      </header>
      <div className="space-y-5 px-5 py-5">
        {item.creatives.length > 0 && (
          <div className="grid gap-4 sm:grid-cols-2" aria-label="Creative files">
            {item.creatives.map((c) => (
              <Creative key={c.id} secret={secret} creative={c} />
            ))}
          </div>
        )}
        {item.elements.length === 0 ? (
          <p className="text-[13.5px] text-ink-secondary">This version has no text to show.</p>
        ) : (
          <dl className="ledger-rules rounded-card border border-border bg-surface" aria-label={`Text of ${item.version_label}`}>
            {item.elements.map((e) => (
              <div key={e.id} className="grid gap-1 px-4 py-2.5 sm:grid-cols-[8rem_minmax(0,1fr)] sm:gap-4">
                <dt className="type-ledger text-[12.5px] text-ink-muted">{KIND_LABEL[e.kind] ?? e.kind}</dt>
                <dd lang={e.language ?? undefined} className="min-w-0 text-[15px] whitespace-pre-line text-ink">
                  {e.text}
                </dd>
              </div>
            ))}
          </dl>
        )}
        <ResponseForm secret={secret} item={item} region={item.region_code} />
      </div>
    </article>
  );
}

function Unavailable({ error }: { error: unknown }) {
  const gone = error instanceof ApiError && error.status === 404;
  const limited = error instanceof ApiError && error.status === 429;
  return (
    <div className="space-y-3 rounded-card border border-border bg-surface px-5 py-6" role="alert">
      <p className="text-[16px] font-semibold text-ink">{gone ? "This review link is not valid" : limited ? "Too many requests" : "The review could not be opened"}</p>
      <p className="max-w-[60ch] text-[14px] text-ink-secondary">
        {gone
          ? "It may have expired or been revoked. Ask the person who sent it to you for a new link."
          : limited
            ? "Wait a minute and open the link again."
            : error instanceof ApiError
              ? error.message
              : "Something went wrong while opening this link."}
      </p>
    </div>
  );
}

/**
 * The page a reviewer opens from a review link, with no account. It shows exactly the versions the sender chose, as text, and takes a
 * decision or a comment on each. The secret is read from the address once, then sent only in a request header.
 */
export function ReviewPageView() {
  const params = useParams<{ token: string }>();
  const secret = decodeURIComponent(params.token ?? "");
  const page = useReviewPage(secret);

  return (
    <main id="main" className="relative mx-auto min-h-dvh w-full max-w-3xl space-y-7 px-4 py-8 text-ink sm:py-12">
      <div className="flex items-center justify-between gap-4">
        <Wordmark href="/" />
        <ThemeToggle />
      </div>

      {page.isPending ? (
        <LoadingState label="Opening the review…" />
      ) : page.error ? (
        <Unavailable error={page.error} />
      ) : (
        <>
          <header className="space-y-2.5 border-b border-border pb-5">
            <p className="type-meta">
              {page.data.brand_name} · review for {page.data.link_label}
            </p>
            <h1 className="type-title text-[30px] text-ink sm:text-[34px]">{page.data.campaign_name}</h1>
            {page.data.note && (
              <p className="flex max-w-[64ch] items-start gap-2 rounded-lg border border-border bg-surface-muted/60 px-3.5 py-2.5 text-[14px] text-ink-body">
                <MessageSquareText aria-hidden className="mt-0.5 size-4 shrink-0 text-ink-secondary" />
                <span>
                  <span className="font-medium text-ink">From the sender: </span>
                  <span className="whitespace-pre-line">{page.data.note}</span>
                </span>
              </p>
            )}
            <p className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[12.5px] text-ink-secondary">
              <span className="inline-flex items-center gap-1.5">
                <Clock3 aria-hidden className="size-3.5" />
                This link works until {formatDateTime(page.data.expires_at)}
              </span>
              <span className="inline-flex items-center gap-1.5">
                <ShieldCheck aria-hidden className="size-3.5" />
                Read-only. {page.data.identity_note}
              </span>
            </p>
          </header>
          <div className="space-y-6">
            {page.data.items.map((item) => (
              <ItemCard key={`${item.version_id}-${item.region_code}`} secret={secret} item={item} />
            ))}
          </div>
          {page.data.mode === "demo" && <p className="type-meta">Source: demonstration data of a fictional brand.</p>}
        </>
      )}
    </main>
  );
}
