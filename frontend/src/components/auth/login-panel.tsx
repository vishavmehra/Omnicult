"use client";

import { createUserWithEmailAndPassword, GoogleAuthProvider, onAuthStateChanged, signInWithEmailAndPassword, signInWithPopup } from "firebase/auth";
import { FlaskConical } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { Field } from "@/components/forms/fields";
import { ErrorState } from "@/components/states";
import { Button, buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { DemoSignInError, useStartDemo } from "@/features/desk/use-start-demo";
import { FIREBASE_MISSING, firebaseConfigured, firebaseErrorMessage, getFirebaseAuth } from "@/lib/auth/firebase";
import { env } from "@/lib/env";
import { cn } from "@/lib/utils";

/** Google's multi-colour "G" mark, as its sign-in branding guidelines require for the button. */
function GoogleMark() {
  return (
    <svg aria-hidden viewBox="0 0 48 48" className="size-4">
      <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z" />
      <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z" />
      <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z" />
      <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z" />
    </svg>
  );
}

function DemoButton() {
  const demo = useStartDemo();
  return (
    <div className="space-y-2">
      <Button variant="outline" size="lg" className="w-full" onClick={() => demo.mutate()} disabled={demo.isPending}>
        <FlaskConical aria-hidden />
        {demo.isPending ? "Preparing the demo…" : "Try the demo"}
      </Button>
      <p className="text-[12.5px] leading-relaxed text-ink-muted">
        Opens a sample brand and campaign on labelled fixture data{env.authMode === "firebase" ? " in an anonymous session" : ""}. It is never mixed with your records.
      </p>
      {demo.error &&
        (demo.error instanceof DemoSignInError ? (
          <p role="alert" className="rounded-lg bg-danger-soft px-3 py-2 text-[13px] text-danger">
            {demo.error.message}
          </p>
        ) : (
          <ErrorState error={demo.error} onRetry={() => demo.mutate()} />
        ))}
    </div>
  );
}

/** Sign in with Google or email, create an account, or try the demo (Firebase Auth). Dev mode needs no sign-in. */
export function LoginPanel() {
  if (env.authMode === "dev") {
    return (
      <div className="space-y-5">
        <p className="text-[14px] text-ink-body">Development mode is on: requests carry the local development token, so there is nothing to sign in to.</p>
        <Link href="/app" className={cn(buttonVariants({ size: "lg" }), "w-full")}>
          Open Campaign Desk
        </Link>
        <DemoButton />
      </div>
    );
  }
  if (!firebaseConfigured) return <ErrorState error={new Error(FIREBASE_MISSING)} />;
  return <FirebaseLogin />;
}

function FirebaseLogin() {
  const router = useRouter();
  const [mode, setMode] = useState<"sign-in" | "sign-up">("sign-in");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState<"form" | "google" | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Already signed in (including a persisted session): go straight to Campaign Desk.
  useEffect(() => onAuthStateChanged(getFirebaseAuth(), (user) => user && !user.isAnonymous && router.replace("/app")), [router]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setPending("form");
    setError(null);
    try {
      const auth = getFirebaseAuth();
      if (mode === "sign-in") await signInWithEmailAndPassword(auth, email, password);
      else await createUserWithEmailAndPassword(auth, email, password);
      router.replace("/app");
    } catch (err) {
      setError(firebaseErrorMessage(err));
    } finally {
      setPending(null);
    }
  }

  async function google() {
    setPending("google");
    setError(null);
    try {
      await signInWithPopup(getFirebaseAuth(), new GoogleAuthProvider());
      router.replace("/app");
    } catch (err) {
      setError(firebaseErrorMessage(err));
    } finally {
      setPending(null);
    }
  }

  return (
    <div className="space-y-6">
      <div role="group" aria-label="Account action" className="clay-well inline-flex rounded-lg p-1">
        {(["sign-in", "sign-up"] as const).map((m) => (
          <button
            key={m}
            type="button"
            aria-pressed={mode === m}
            onClick={() => setMode(m)}
            className={cn("h-8 rounded-md px-3 text-[13px] text-ink-secondary", mode === m && "clay font-medium text-ink")}
          >
            {m === "sign-in" ? "Sign in" : "Create account"}
          </button>
        ))}
      </div>
      <Button variant="outline" size="lg" className="w-full" onClick={() => void google()} disabled={pending !== null}>
        <GoogleMark />
        {pending === "google" ? "Waiting for Google…" : "Continue with Google"}
      </Button>
      <form onSubmit={submit} className="space-y-4">
        <Field label="Email" htmlFor="email" required>
          <Input id="email" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} required className="h-10 bg-surface-raised" />
        </Field>
        <Field label="Password" htmlFor="password" required hint={mode === "sign-up" ? "At least 6 characters." : undefined}>
          <Input
            id="password"
            type="password"
            autoComplete={mode === "sign-in" ? "current-password" : "new-password"}
            minLength={6}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            className="h-10 bg-surface-raised"
          />
        </Field>
        {error && (
          <p role="alert" className="rounded-lg bg-danger-soft px-3 py-2 text-[13px] text-danger">
            {error}
          </p>
        )}
        <Button type="submit" className="w-full" size="lg" disabled={pending !== null}>
          {pending === "form" ? "Working…" : mode === "sign-in" ? "Sign in" : "Create account"}
        </Button>
      </form>
      <div className="flex items-center gap-3 text-[12px] text-ink-muted">
        <span className="h-px flex-1 bg-border" />
        or
        <span className="h-px flex-1 bg-border" />
      </div>
      <DemoButton />
    </div>
  );
}
