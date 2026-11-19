"use client";

import { Check, CircleOff, Copy, ExternalLink, Info, Link2, LoaderCircle, MessageSquareText, Plus } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { Tag } from "@/components/evidence/badges";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useCampaign } from "@/features/workspaces/campaign-context";
import { SectionTitle } from "@/features/workspaces/parts";
import { formatDateTime, formatRelative } from "@/lib/format";
import { cn } from "@/lib/utils";

import { useCapabilities, useRegions, useVersionOptions } from "./api";
import { NativeSelect } from "./bits";
import {
  useCreateReviewLink,
  useReviewLinks,
  useReviewResponses,
  useRevokeReviewLink,
  type ReviewDecision,
  type ReviewLink,
  type ReviewLinkCreated,
  type ReviewResponse,
} from "./delivery-api";
import { useRegionChoices } from "./region-choices";

const STATUS = {
  active: { word: "Active", className: "border-success/30 bg-success-soft text-success" },
  expired: { word: "Expired", className: "border-border bg-surface-muted text-ink-secondary" },
  revoked: { word: "Revoked", className: "border-danger/30 bg-danger-soft text-danger" },
} as const;

export const DECISION_WORD: Record<ReviewDecision, { word: string; className: string }> = {
  approve: { word: "Approve", className: "border-success/30 bg-success-soft text-success" },
  request_changes: { word: "Changes requested", className: "border-warning/30 bg-warning-soft text-warning" },
  reject: { word: "Reject", className: "border-danger/30 bg-danger-soft text-danger" },
  comment: { word: "Comment", className: "border-border bg-surface-muted text-ink" },
};

const EXPIRY_CHOICES = [1, 3, 7, 14, 30] as const;

/** The page address a reviewer opens. The secret lives only in this address and in the owner's clipboard. */
export const reviewUrl = (path: string) => `${window.location.origin}${path}`;

function LinkRow({ link, canRevoke, onRevoke, revoking }: { link: ReviewLink; canRevoke: boolean; onRevoke(): void; revoking: boolean }) {
  const status = STATUS[link.status];
  const decided = link.decisions.approve + link.decisions.request_changes + link.decisions.reject + link.decisions.comment;
  return (
    <li className="space-y-2 px-4 py-3.5">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <p className="text-[14.5px] font-semibold text-ink">{link.label}</p>
        <Tag className={status.className}>{status.word}</Tag>
        <span className="font-mono text-[12px] text-ink-muted" title="The last four characters of the secret. The secret itself is not stored.">
          …{link.token_hint}
        </span>
        <span className="type-meta ml-auto" title={formatDateTime(link.expires_at)}>
          {link.status === "revoked" ? `Revoked ${formatRelative(link.revoked_at)}` : link.status === "expired" ? `Expired ${formatRelative(link.expires_at)}` : `Expires ${formatRelative(link.expires_at)}`}
        </span>
      </div>
      <ul className="flex flex-wrap gap-1.5" aria-label="Versions this link can show">
        {link.items.map((i) => (
          <li key={`${i.version_id}-${i.region_code}`} className="rounded-stamp border border-border px-1.5 py-0.5 text-[12px] text-ink-secondary">
            {i.version_label} <span className="text-ink-muted">in {i.region_name}</span>
          </li>
        ))}
      </ul>
      {link.note && <p className="max-w-[72ch] text-[13px] text-ink-secondary">Your note: {link.note}</p>}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <p className="text-[12.5px] text-ink-secondary">
          {decided === 0
            ? "No response yet."
            : `${decided} ${decided === 1 ? "response" : "responses"}: ${link.decisions.approve} approve, ${link.decisions.request_changes} changes, ${link.decisions.reject} reject, ${link.decisions.comment} comment${link.last_response_at ? `, latest ${formatRelative(link.last_response_at)}` : ""}.`}
        </p>
        {link.status === "active" && canRevoke && (
          <Button variant="outline" size="sm" disabled={revoking} onClick={onRevoke} className="ml-auto">
            {revoking ? <LoaderCircle aria-hidden className="animate-spin motion-reduce:animate-none" /> : <CircleOff aria-hidden />}
            Revoke
          </Button>
        )}
      </div>
    </li>
  );
}

function ResponseRow({ r }: { r: ReviewResponse }) {
  const d = DECISION_WORD[r.decision];
  return (
    <li className="grid gap-1.5 px-4 py-3 sm:grid-cols-[minmax(0,13rem)_minmax(0,1fr)] sm:gap-x-5">
      <div className="space-y-1">
        <p className="text-[13.5px] font-medium text-ink">{r.reviewer_name ?? "Anonymous reviewer"}</p>
        <p className="type-meta">
          {r.reviewer_kind === "named" ? "Name typed by the reviewer, not verified" : "No name given"}
        </p>
        <p className="type-meta" title={formatDateTime(r.created_at)}>
          {formatRelative(r.created_at)} · {r.link_label}
        </p>
      </div>
      <div className="min-w-0 space-y-1.5">
        <p className="flex flex-wrap items-center gap-2 text-[13.5px] text-ink-body">
          <Tag className={d.className}>{d.word}</Tag>
          <span>
            {r.version_label} <span className="text-ink-muted">in {r.region_name}</span>
          </span>
        </p>
        {r.comment && <p className="max-w-[72ch] text-[13.5px] whitespace-pre-line text-ink">{r.comment}</p>}
      </div>
    </li>
  );
}

function CreatedDialog({ created, onClose }: { created: ReviewLinkCreated | null; onClose(): void }) {
  const [copied, setCopied] = useState(false);
  const url = created ? reviewUrl(created.review_path) : "";
  async function copy() {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error("Could not copy. Select the address and copy it by hand.");
    }
  }
  return (
    <Dialog open={created !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Review link created</DialogTitle>
          <DialogDescription>
            Copy it now. For safety only a fingerprint of the secret is stored, so this address cannot be shown again. If you lose it, revoke the link and make a new one.
          </DialogDescription>
        </DialogHeader>
        {created && (
          <div className="space-y-3">
            <div className="space-y-1.5">
              <label htmlFor="review-url" className="block text-[13px] font-medium text-ink">Link for {created.label}</label>
              <Input id="review-url" readOnly value={url} onFocus={(e) => e.currentTarget.select()} className="font-mono text-[12.5px]" />
            </div>
            <p className="text-[12.5px] text-ink-secondary">
              Anyone who has this address can open the review until it expires on {formatDateTime(created.expires_at)} or you revoke it. They need no account, see only the {created.items.length}{" "}
              {created.items.length === 1 ? "version" : "versions"} you chose, and their decisions are advice: they never approve anything.
            </p>
          </div>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Done</Button>
          {created && (
            <a href={url} target="_blank" rel="noopener noreferrer" className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-border bg-surface-raised px-2.5 text-[14px] font-medium text-ink hover:bg-surface-muted">
              <ExternalLink aria-hidden className="size-4" />
              Open as the reviewer sees it
            </a>
          )}
          <Button onClick={() => void copy()}>
            {copied ? <Check aria-hidden /> : <Copy aria-hidden />}
            {copied ? "Copied" : "Copy link"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

type Pick = { checked: boolean; region: string };

function NewLinkDialog({ campaignId, open, onOpenChange, onCreated }: { campaignId: string; open: boolean; onOpenChange(open: boolean): void; onCreated(link: ReviewLinkCreated): void }) {
  const versions = useVersionOptions();
  const regions = useRegions();
  const choices = useRegionChoices(regions.data);
  const create = useCreateReviewLink(campaignId);
  const [label, setLabel] = useState("");
  const [note, setNote] = useState("");
  const [days, setDays] = useState<number>(7);
  const [picked, setPicked] = useState<Record<string, Pick>>({});
  const studio = versions.options.filter((o) => o.source === "studio");

  const read = (id: string, fallback: string): Pick => picked[id] ?? { checked: false, region: fallback };
  const chosen = studio.filter((o) => read(o.id, o.regionCode ?? "").checked);
  const missingRegion = chosen.some((o) => !read(o.id, o.regionCode ?? "").region);
  const ready = label.trim().length > 0 && chosen.length > 0 && !missingRegion && !create.isPending;

  function close(next: boolean) {
    if (!next) {
      create.reset();
      setLabel("");
      setNote("");
      setDays(7);
      setPicked({});
    }
    onOpenChange(next);
  }

  function submit() {
    create.mutate(
      {
        label: label.trim().slice(0, 60),
        note: note.trim() ? note.trim().slice(0, 300) : null,
        expires_in_days: days,
        items: chosen.map((o) => ({ version_id: o.id, region_code: read(o.id, o.regionCode ?? "").region })),
      },
      {
        onSuccess: (link) => {
          close(false);
          onCreated(link);
        },
      },
    );
  }

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>New review link</DialogTitle>
          <DialogDescription>Share chosen versions with someone who has no account. They can read them and leave a decision or a comment, and nothing else.</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-1.5">
            <label htmlFor="link-label" className="block text-[13px] font-medium text-ink">Name this link <span className="text-danger">*</span></label>
            <Input id="link-label" value={label} maxLength={60} onChange={(e) => setLabel(e.target.value)} placeholder="For example: Tamil Nadu regional head" />
          </div>
          <div className="space-y-1.5">
            <label htmlFor="link-note" className="block text-[13px] font-medium text-ink">Message to the reviewer <span className="font-normal text-ink-secondary">(optional)</span></label>
            <Textarea id="link-note" value={note} maxLength={300} onChange={(e) => setNote(e.target.value)} placeholder="What you would like them to check." />
          </div>
          <fieldset className="space-y-2">
            <legend className="text-[13px] font-medium text-ink">Versions to share <span className="text-danger">*</span></legend>
            {versions.isPending ? (
              <LoadingState label="Reading this campaign’s versions…" />
            ) : versions.error ? (
              <ErrorState error={versions.error} onRetry={() => void versions.refetch()} />
            ) : studio.length === 0 ? (
              <p className="rounded-lg border border-dashed border-border-strong/50 px-3.5 py-3 text-[13px] text-ink-secondary">No Creative Studio version exists yet. Make one in Creative Studio, then share it from here.</p>
            ) : (
              <ul className="ledger-rules rounded-card border border-border">
                {studio.map((o) => {
                  const state = read(o.id, o.regionCode ?? "");
                  return (
                    <li key={o.id} className="grid gap-2 px-3 py-2.5 sm:grid-cols-[minmax(0,1fr)_12rem] sm:items-center">
                      <label className="flex cursor-pointer items-center gap-2.5 text-[14px] text-ink">
                        <Checkbox checked={state.checked} onCheckedChange={(v) => setPicked((p) => ({ ...p, [o.id]: { ...state, checked: v === true } }))} />
                        <span className="min-w-0 truncate">{o.label}</span>
                      </label>
                      <div>
                        <label htmlFor={`region-${o.id}`} className="sr-only">Region for {o.label}</label>
                        <NativeSelect id={`region-${o.id}`} value={state.region} onChange={(e) => setPicked((p) => ({ ...p, [o.id]: { ...state, region: e.target.value } }))}>
                          <option value="">Region…</option>
                          {choices.map((g) => (
                            <optgroup key={g.label} label={g.label}>
                              {g.regions.map((r) => (
                                <option key={r.code} value={r.code}>{r.name}</option>
                              ))}
                            </optgroup>
                          ))}
                        </NativeSelect>
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
            {missingRegion && <p role="alert" className="text-xs font-medium text-danger">Choose a region for each version you share.</p>}
          </fieldset>
          <div className="space-y-1.5">
            <label htmlFor="link-days" className="block text-[13px] font-medium text-ink">Link stops working after</label>
            <NativeSelect id="link-days" value={String(days)} onChange={(e) => setDays(Number(e.target.value))} className="w-40">
              {EXPIRY_CHOICES.map((n) => (
                <option key={n} value={n}>{n} {n === 1 ? "day" : "days"}</option>
              ))}
            </NativeSelect>
          </div>
          {create.error && <ErrorState error={create.error} onRetry={submit} />}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => close(false)}>Cancel</Button>
          <Button disabled={!ready} onClick={submit}>
            {create.isPending ? <LoaderCircle aria-hidden className="animate-spin motion-reduce:animate-none" /> : <Link2 aria-hidden />}
            {create.isPending ? "Creating…" : "Create link"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/**
 * Review Links (feature 38): scoped, expiring, revocable links for people with no account, and the decisions that came back.
 * A reviewer's decision is advice recorded against the version; approvals stay with signed-in members on the Readiness Board.
 */
export function ReviewLinksTab() {
  const { campaign } = useCampaign();
  const caps = useCapabilities();
  const links = useReviewLinks(campaign.id);
  const responses = useReviewResponses(campaign.id);
  const revoke = useRevokeReviewLink(campaign.id);
  const [creating, setCreating] = useState(false);
  const [created, setCreated] = useState<ReviewLinkCreated | null>(null);
  const [revoking, setRevoking] = useState<string | null>(null);
  const total = links.data?.total ?? 0;
  const active = useMemo(() => (links.data?.items ?? []).filter((l) => l.status === "active").length, [links.data]);

  return (
    <div className="space-y-10">
      <section aria-labelledby="links-title" className="space-y-3">
        <div className="space-y-2">
          <SectionTitle id="links-title" meta={links.data ? `${total} ${total === 1 ? "link" : "links"}, ${active} active` : undefined}>
            Review links
          </SectionTitle>
          <p className="max-w-[72ch] text-[13.5px] text-ink-secondary">
            Send a client or a regional head a read-only page of the versions you choose. They open it without an account, and leave a decision or a comment that is recorded against the version.
          </p>
          <div className="flex flex-wrap items-center gap-2.5">
            <Button disabled={!caps.canCompute} onClick={() => setCreating(true)}>
              <Plus aria-hidden />
              New review link
            </Button>
          </div>
          {!caps.loading && !caps.canCompute && caps.reason && (
            <p role="status" className="flex max-w-[72ch] items-start gap-2 text-[13px] text-ink-secondary">
              <Info aria-hidden className="mt-0.5 size-4 shrink-0" />
              Creating and revoking links needs the owner or editor role. {caps.reason}
            </p>
          )}
        </div>

        {links.error ? (
          <ErrorState error={links.error} onRetry={() => void links.refetch()} />
        ) : links.isPending ? (
          <LoadingState label="Reading the review links…" />
        ) : total === 0 ? (
          <EmptyState
            title="No review link yet"
            description="A link names the versions and regions a reviewer can see, expires on a date you choose, and can be revoked at any time. Reviewers see plain text and the region’s rights-confirmed creative files, and nothing else in your workspace."
            needs={[{ label: "A Creative Studio version to share. Make one in Creative Studio first." }]}
          />
        ) : (
          <ul className="ledger-rules rounded-card border border-border bg-surface" aria-label="Review links">
            {links.data.items.map((l) => (
              <LinkRow
                key={l.id}
                link={l}
                canRevoke={caps.canCompute}
                revoking={revoking === l.id && revoke.isPending}
                onRevoke={() => {
                  setRevoking(l.id);
                  revoke.mutate(l.id, { onSuccess: () => toast.success(`Revoked: ${l.label}. It stops working at once.`) });
                }}
              />
            ))}
          </ul>
        )}
        {revoke.error && <ErrorState error={revoke.error} />}
      </section>

      <section aria-labelledby="responses-title" className="space-y-3">
        <SectionTitle id="responses-title" meta={responses.data ? `${responses.data.total} recorded` : undefined}>
          What reviewers said
        </SectionTitle>
        {responses.error ? (
          <ErrorState error={responses.error} onRetry={() => void responses.refetch()} />
        ) : responses.isPending ? (
          <LoadingState label="Reading the responses…" />
        ) : responses.data.items.length === 0 ? (
          <EmptyState
            title="No response yet"
            description={
              <>
                A reviewer’s decision appears here with their name if they gave one, and as an anonymous reviewer if not. It is advice for the people who approve; it does not approve a version.
              </>
            }
          />
        ) : (
          <ul className={cn("ledger-rules rounded-card border border-border bg-surface")} aria-label="Reviewer responses">
            {responses.data.items.map((r) => (
              <ResponseRow key={r.id} r={r} />
            ))}
          </ul>
        )}
        <p className="flex max-w-[72ch] items-start gap-2 text-[12.5px] text-ink-muted">
          <MessageSquareText aria-hidden className="mt-0.5 size-3.5 shrink-0" />
          Reviewer names are typed by the reviewer and are not verified. Each response is also written to the audit log with the decision, never with the name or the comment.
        </p>
      </section>

      <NewLinkDialog campaignId={campaign.id} open={creating} onOpenChange={setCreating} onCreated={setCreated} />
      <CreatedDialog created={created} onClose={() => setCreated(null)} />
    </div>
  );
}
