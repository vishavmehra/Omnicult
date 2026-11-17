"use client";

import { getApps, initializeApp } from "firebase/app";
import { getAuth, type Auth } from "firebase/auth";

import { setTokenProvider } from "@/lib/auth/token";
import { env } from "@/lib/env";

const { apiKey, authDomain, projectId, appId } = env.firebase;

export const firebaseConfigured = Boolean(apiKey && authDomain && projectId && appId);

export const FIREBASE_MISSING =
  "Firebase sign-in is enabled (NEXT_PUBLIC_AUTH_MODE=firebase), but NEXT_PUBLIC_FIREBASE_API_KEY, NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN, NEXT_PUBLIC_FIREBASE_PROJECT_ID or NEXT_PUBLIC_FIREBASE_APP_ID is missing.";

let auth: Auth | null = null;

/**
 * Firebase Auth for NEXT_PUBLIC_AUTH_MODE=firebase. On first use it registers the API token provider: every request waits
 * for the persisted session to resolve, then sends the current user's ID token (the SDK refreshes it before expiry).
 */
export function getFirebaseAuth(): Auth {
  if (!auth) {
    if (!firebaseConfigured) throw new Error(FIREBASE_MISSING);
    const app = getApps()[0] ?? initializeApp({ apiKey, authDomain, projectId, appId });
    const instance = getAuth(app);
    setTokenProvider(async () => {
      await instance.authStateReady();
      return instance.currentUser ? instance.currentUser.getIdToken() : null;
    });
    auth = instance;
  }
  return auth;
}

/** Plain-language text for Firebase Auth error codes. Provider text is never shown raw. */
export function firebaseErrorMessage(error: unknown): string {
  const code = typeof error === "object" && error && "code" in error ? String((error as { code: unknown }).code) : "";
  switch (code) {
    case "auth/invalid-credential":
    case "auth/wrong-password":
    case "auth/user-not-found":
    case "auth/invalid-email":
      return "That email and password do not match an account.";
    case "auth/email-already-in-use":
      return "An account with this email already exists. Sign in instead.";
    case "auth/weak-password":
      return "Choose a password of at least 6 characters.";
    case "auth/too-many-requests":
      return "Too many attempts from this browser. Wait a few minutes, then try again.";
    case "auth/popup-closed-by-user":
    case "auth/cancelled-popup-request":
      return "The Google window was closed before sign-in finished.";
    case "auth/popup-blocked":
      return "The browser blocked the Google sign-in window. Allow pop-ups for this site and try again.";
    case "auth/operation-not-allowed":
    case "auth/admin-restricted-operation":
      return "This sign-in method is not enabled for this Firebase project.";
    case "auth/network-request-failed":
      return "Could not reach Firebase. Check your connection and try again.";
    default:
      return "Sign-in failed. Try again in a moment.";
  }
}
