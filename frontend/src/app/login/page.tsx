import type { Metadata } from "next";

import { LoginPanel } from "@/components/auth/login-panel";
import { ThemeToggle } from "@/components/shell/theme-toggle";
import { Wordmark } from "@/components/shell/wordmark";

export const metadata: Metadata = { title: "Sign in" };

/** Sign-in on one raised clay panel over the same continuous ground as the landing page and the app. */
export default function LoginPage() {
  return (
    <main id="main" className="relative grid min-h-dvh place-items-center px-4 py-12 text-ink">
      <div className="absolute top-5 right-5">
        <ThemeToggle />
      </div>
      <div className="w-full max-w-[26rem] space-y-6">
        <Wordmark href="/" size="lg" />
        <div className="clay-panel border border-border/60 p-6 sm:p-8">
          <div className="mb-6 space-y-1.5">
            <h1 className="type-title text-[30px] text-ink">Sign in to Omnicult</h1>
            <p className="text-[14px] text-ink-secondary">Brands, campaigns and evidence are private to your team.</p>
          </div>
          <LoginPanel />
        </div>
      </div>
    </main>
  );
}
