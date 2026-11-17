import { env } from "@/lib/env";

type TokenProvider = () => Promise<string | null>;

// Dev mode sends the backend's development token. Firebase mode registers a provider on first use (lib/auth/firebase.ts).
let provider: TokenProvider = async () => (env.authMode === "dev" ? "dev-local" : null);

export function setTokenProvider(next: TokenProvider) {
  provider = next;
}

export function getAccessToken() {
  return provider();
}
