"use client";

import { onAuthStateChanged, signOut as firebaseSignOut } from "firebase/auth";
import { useEffect, useState } from "react";

import { firebaseConfigured, getFirebaseAuth } from "@/lib/auth/firebase";
import { env } from "@/lib/env";

export type Account =
  | { status: "dev"; label: string }
  | { status: "loading"; label: null }
  | { status: "signed-out"; label: null }
  | { status: "anonymous" | "user"; label: string };

const initial = (): Account => (env.authMode === "dev" ? { status: "dev", label: "Development mode" } : { status: "loading", label: null });

/** Who is signed in, for the account menu and greetings. Never throws when Firebase is not configured. */
export function useAccount(): Account {
  const [account, setAccount] = useState<Account>(initial);
  useEffect(() => {
    if (env.authMode !== "firebase" || !firebaseConfigured) return;
    return onAuthStateChanged(getFirebaseAuth(), (user) =>
      setAccount(
        !user
          ? { status: "signed-out", label: null }
          : user.isAnonymous
            ? { status: "anonymous", label: "Anonymous demo session" }
            : { status: "user", label: user.displayName ?? user.email ?? "Signed in" },
      ),
    );
  }, []);
  return account;
}

/** Ends the Firebase session. Dev mode has no session to end. */
export async function signOut() {
  if (env.authMode === "firebase" && firebaseConfigured) await firebaseSignOut(getFirebaseAuth());
}
