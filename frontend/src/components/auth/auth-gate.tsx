"use client";

import { onAuthStateChanged } from "firebase/auth";
import { useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { ErrorState, LoadingState } from "@/components/states";
import { FIREBASE_MISSING, firebaseConfigured, getFirebaseAuth } from "@/lib/auth/firebase";
import { env } from "@/lib/env";

/**
 * Client route guard. Dev auth mode needs no sign-in (token.ts sends the development token). Firebase mode waits for the
 * persisted session to resolve, then renders children with a user or redirects to /login. The backend verifies every token.
 */
export function AuthGate({ children }: { children: ReactNode }) {
  if (env.authMode === "dev") return children;
  if (!firebaseConfigured) {
    return (
      <div className="mx-auto max-w-xl p-6">
        <ErrorState error={new Error(FIREBASE_MISSING)} />
      </div>
    );
  }
  return <FirebaseGate>{children}</FirebaseGate>;
}

function FirebaseGate({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [signedIn, setSignedIn] = useState<boolean | null>(null);

  useEffect(
    () =>
      onAuthStateChanged(getFirebaseAuth(), (user) => {
        setSignedIn(Boolean(user));
        if (!user) router.replace("/login");
      }),
    [router],
  );

  if (!signedIn) {
    return (
      <div className="grid min-h-dvh place-items-center bg-canvas">
        <LoadingState label={signedIn === null ? "Checking your session…" : "Redirecting to sign in…"} />
      </div>
    );
  }
  return children;
}
