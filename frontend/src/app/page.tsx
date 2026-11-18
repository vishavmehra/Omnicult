import type { Metadata } from "next";

import { AdaptationArtefact } from "@/components/landing/adaptation-artefact";
import { DemoAction } from "@/components/landing/demo-action";
import { LandingMotion } from "@/components/landing/landing-motion";
import { Meadow } from "@/components/landing/meadow";
import { SignInLink } from "@/components/landing/sign-in-link";
import { SoundToggle } from "@/components/landing/sound-toggle";
import { StageCarousel } from "@/components/landing/stage-carousel";
import { ThemeToggle } from "@/components/shell/theme-toggle";
import { Wordmark } from "@/components/shell/wordmark";

export const metadata: Metadata = { title: { absolute: "Omnicult: adapt the campaign, not just the language" } };

/**
 * First viewport: nav, the statement with its two actions, the product itself (one adaptation, with its evidence and
 * verdict), and the top of the stage cards. Everything sits on the same continuous ground as the app.
 */
export default function LandingPage() {
  return (
    <div className="min-h-dvh text-ink">
      <LandingMotion>
        <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 focus:rounded-md focus:bg-surface focus:px-3 focus:py-2 focus:text-sm">
          Skip to content
        </a>
        <header className="mx-auto flex h-16 w-full max-w-[1240px] items-center justify-between gap-3 px-5 sm:px-8">
          <Wordmark href="/" />
          <div className="flex items-center gap-1.5">
            <SoundToggle />
            <ThemeToggle />
            <SignInLink variant="outline" className="h-9 px-3.5 text-[13.5px]" />
          </div>
        </header>

        <main id="main">
          <section
            data-hero
            aria-labelledby="hero-title"
            className="mx-auto grid w-full max-w-[1240px] items-center gap-x-14 gap-y-10 px-5 pt-8 pb-12 sm:px-8 lg:grid-cols-[minmax(0,1.15fr)_minmax(0,0.9fr)] lg:pt-12 lg:pb-14"
          >
            <div data-hero-content>
              <h1 id="hero-title" className="type-hero text-[clamp(36px,4.2vw,60px)] text-ink">
                <span className="hero-settle block">
                  Adapt the{" "}
                  <span className="underline decoration-pop decoration-[0.075em] underline-offset-[0.16em] [text-decoration-skip-ink:none]">campaign</span>,
                </span>
                <span className="hero-settle block text-ink-secondary" style={{ animationDelay: "120ms" }}>
                  not just the language.
                </span>
              </h1>
              <p className="hero-rise mt-5 max-w-[46ch] text-[clamp(15.5px,1.2vw,18px)] leading-relaxed text-ink-secondary" style={{ animationDelay: "320ms" }}>
                Learn the region, remake the creative, test it, and keep the evidence behind every call.
              </p>
              <div className="hero-rise mt-7 flex flex-wrap items-start gap-3" style={{ animationDelay: "440ms" }}>
                <DemoAction />
                <SignInLink variant="outline" size="lg" className="h-12 px-5 text-[15px]" />
              </div>
            </div>
            <div className="hero-rise" style={{ animationDelay: "260ms" }}>
              <AdaptationArtefact />
            </div>
          </section>

          <StageCarousel />

          <p className="mx-auto max-w-[1240px] px-5 pt-1 pb-8 text-[12.5px] text-ink-muted sm:px-8">
            Omnicult is decision support for regional campaigns, not a prediction of how a campaign will perform.
          </p>
        </main>
      </LandingMotion>
      {/* The meadow's creatures: a fixed layer in viewport coordinates, outside the scroll choreography. */}
      <Meadow />
    </div>
  );
}
