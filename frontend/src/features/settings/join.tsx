"use client";

import { UsersRound } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, useSyncExternalStore } from "react";

import { ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiError } from "@/lib/api/errors";
import { formatDateTime } from "@/lib/format";

import { personName, roleLabel, useAcceptInvite, useMe, usePreviewInvite, type InvitePreview } from "./api";

function subscribe(cb: () => void) {
  window.addEventListener("hashchange", cb);
  return () => window.removeEventListener("hashchange", cb);
}
/** The code in the link's fragment (#code=...). A fragment is never sent to a server or written to its logs. */
function useHashCode() {
  return useSyncExternalStore(subscribe, () => new URLSearchParams(window.location.hash.replace(/^#/, "")).get("code") ?? "", () => "");
}

function InvalidCode({ error }: { error: unknown }) {
  if (error instanceof ApiError && error.status === 404) {
    return (
      <p role="alert" className="text-[13.5px] text-danger">
        {error.message} Ask the workspace owner for a new invite.
      </p>
    );
  }
  return <ErrorState error={error} />;
}

function Offer({ preview, code }: { preview: InvitePreview; code: string }) {
  const router = useRouter();
  const accept = useAcceptInvite();
  const blocked = preview.already_member;
  return (
    <div className="space-y-4 rounded-card border border-border bg-surface p-5">
      <div className="space-y-1">
        <p className="text-[13px] text-ink-muted">You are invited to join</p>
        <p className="type-title text-[26px] text-ink">{preview.workspace_name}</p>
        <p className="text-[14px] text-ink-body">
          as {roleLabel(preview.role)}
          {preview.invited_by ? `, invited by ${personName(preview.invited_by)}` : ""}. Expires {formatDateTime(preview.expires_at)}.
        </p>
      </div>
      {preview.email_matches_account === false && (
        <p role="alert" className="text-[13.5px] text-danger">
          This invite was issued for a different email address than the one on your account, so joining will be refused.
        </p>
      )}
      {blocked && <p className="text-[13.5px] text-ink-body">You are already a member of this workspace.</p>}
      <div className="flex flex-wrap items-center gap-3">
        <Button
          size="lg"
          disabled={accept.isPending || blocked || preview.email_matches_account === false}
          onClick={() => accept.mutate(code, { onSuccess: (w) => router.replace(`/app/settings?w=${w.id}`) })}
        >
          <UsersRound aria-hidden />
          {accept.isPending ? "Joining…" : "Accept and join"}
        </Button>
        <Link href="/app/settings" className="text-[13.5px] text-ink-secondary hover:text-ink hover:underline">
          Not now
        </Link>
      </div>
      {accept.error && <InvalidCode error={accept.error} />}
    </div>
  );
}

/** Accept-invite flow for a signed-in user: paste or open the link, see what it offers, then accept. */
export function JoinScreen() {
  const me = useMe();
  const fromLink = useHashCode();
  const [typed, setTyped] = useState("");
  const code = (typed || fromLink).trim();
  const preview = usePreviewInvite();
  const anonymous = Boolean(me.data?.is_anonymous);

  return (
    <div className="max-w-[40rem] space-y-6">
      <header className="space-y-1.5 border-b border-border pb-5">
        <h1 className="type-title text-[30px] text-ink sm:text-[34px]">Join a workspace</h1>
        <p className="text-[14.5px] text-ink-secondary">Open the invite link you were sent, or paste the invite code below.</p>
      </header>
      {me.error ? (
        <ErrorState error={me.error} onRetry={() => void me.refetch()} />
      ) : !me.data ? (
        <LoadingState label="Checking your account…" />
      ) : anonymous ? (
        <p role="alert" className="text-[14px] text-ink-body">
          You are using an anonymous demo session. Sign in with an account, then open this invite link again.
        </p>
      ) : (
        <>
          <form
            className="space-y-3"
            onSubmit={(e) => {
              e.preventDefault();
              if (code) preview.mutate(code);
            }}
          >
            <div className="space-y-1">
              <label htmlFor="join-code" className="type-meta block">
                Invite code
              </label>
              <Input
                id="join-code" value={typed || fromLink} onChange={(e) => { setTyped(e.target.value); preview.reset(); }}
                autoComplete="off" spellCheck={false} className="h-10 font-mono text-[13px]" placeholder="Paste the code from your invite"
              />
            </div>
            <Button type="submit" variant="outline" size="lg" disabled={code.length < 16 || preview.isPending}>
              {preview.isPending ? "Checking…" : "Check invite"}
            </Button>
          </form>
          {preview.error && <InvalidCode error={preview.error} />}
          {preview.data && <Offer preview={preview.data} code={code} />}
        </>
      )}
    </div>
  );
}
