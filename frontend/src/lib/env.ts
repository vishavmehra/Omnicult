/** Public runtime configuration. Only NEXT_PUBLIC_* values belong here, never secrets. */
export const env = {
  apiBaseUrl: process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000",
  // dev: the backend's development token, no sign-in (local only). firebase: Firebase Auth ID tokens.
  authMode: (process.env.NEXT_PUBLIC_AUTH_MODE === "firebase" ? "firebase" : "dev") as "firebase" | "dev",
  // Firebase web config values are public identifiers, not secrets; access is enforced by the backend verifying ID tokens.
  firebase: {
    apiKey: process.env.NEXT_PUBLIC_FIREBASE_API_KEY ?? "",
    authDomain: process.env.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN ?? "",
    projectId: process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID ?? "",
    appId: process.env.NEXT_PUBLIC_FIREBASE_APP_ID ?? "",
  },
};
