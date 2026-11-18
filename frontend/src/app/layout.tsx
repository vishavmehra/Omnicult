import type { Metadata } from "next";
import { Suspense } from "react";
import {
  Archivo,
  Eczar,
  JetBrains_Mono,
  Noto_Sans_Bengali,
  Noto_Sans_Devanagari,
  Noto_Sans_Gujarati,
  Noto_Sans_Gurmukhi,
  Noto_Sans_Kannada,
  Noto_Sans_Malayalam,
  Noto_Sans_Oriya,
  Noto_Sans_Tamil,
  Noto_Sans_Telugu,
} from "next/font/google";

import { AmbientCanvas } from "@/components/ambient/ambient-canvas";
import { ZoneMarker } from "@/components/field/zone-marker";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";

import { Providers } from "./providers";
import "./globals.css";

// UI and ledger columns: Archivo (variable width axis for narrow ruled columns). Display: Eczar. Identifiers: JetBrains Mono.
const archivo = Archivo({ variable: "--font-archivo", subsets: ["latin", "latin-ext"], axes: ["wdth"] });
const eczar = Eczar({ variable: "--font-eczar", subsets: ["latin", "latin-ext"] });
const jetbrainsMono = JetBrains_Mono({ variable: "--font-jetbrains-mono", subsets: ["latin"] });

// Indic scripts: Noto Sans per script, never preloaded. Each @font-face carries its unicode-range, so a script's file is
// fetched only when text in that script is on screen. Applied by `lang` in globals.css and as fallbacks in --font-sans.
const deva = Noto_Sans_Devanagari({ variable: "--font-noto-deva", subsets: ["devanagari"], preload: false });
const taml = Noto_Sans_Tamil({ variable: "--font-noto-taml", subsets: ["tamil"], preload: false });
const mlym = Noto_Sans_Malayalam({ variable: "--font-noto-mlym", subsets: ["malayalam"], preload: false });
const beng = Noto_Sans_Bengali({ variable: "--font-noto-beng", subsets: ["bengali"], preload: false });
const telu = Noto_Sans_Telugu({ variable: "--font-noto-telu", subsets: ["telugu"], preload: false });
const knda = Noto_Sans_Kannada({ variable: "--font-noto-knda", subsets: ["kannada"], preload: false });
const gujr = Noto_Sans_Gujarati({ variable: "--font-noto-gujr", subsets: ["gujarati"], preload: false });
const guru = Noto_Sans_Gurmukhi({ variable: "--font-noto-guru", subsets: ["gurmukhi"], preload: false });
const orya = Noto_Sans_Oriya({ variable: "--font-noto-orya", subsets: ["oriya"], preload: false });

const fontVars = [archivo, eczar, jetbrainsMono, deva, taml, mlym, beng, telu, knda, gujr, guru, orya].map((f) => f.variable).join(" ");

// Impeccable direction contract, emitted as an HTML comment so the finish review can audit the build against it.
const DIRECTION_CONTRACT = `<!-- OMNICULT DIRECTION CONTRACT · seed 415883f7 (re-directed by the owner: Graphite and Ember)
THESIS: a creative-intelligence workspace kept like a ledger of clay; every finding is a ruled entry with its receipt. Refuses the card-grid AI dashboard and the purple AI palette.
OWN-WORLD: near-black graphite clay panels (dark, default) or white clay with pastel tints on cool grey (light); one ember coral-orange pop for the primary action, focus and the active place; Eczar titles, Archivo ledger columns; one continuous drifting ground under landing and app.
STORY: a brand team sees what needs attention, opens a campaign, and moves along seven numbered workspaces without losing context or evidence.
FIRST VIEWPORT: landing is one Eczar statement, one line, two actions, with two SVG butterflies drifting in the margins; below, one card carousel of the workflow stages; the app opens on a bento of clay panels beside a floating clay spine.
FORM: grounded candidate 3 of 7 (ledger), raised by density (Japanese high-density web), ordered stations (transit diagram), held state (gate board).
FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance. -->`;

export const metadata: Metadata = {
  title: { default: "Omnicult", template: "%s · Omnicult" },
  description:
    "Creative intelligence for regional campaigns: understand the region, adapt the creative, test it with a labelled synthetic audience, decide by visible rules, and keep the evidence.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    // suppressHydrationWarning: next-themes sets the theme class on <html> before hydration.
    <html lang="en" suppressHydrationWarning className={`${fontVars} dark h-full antialiased`}>
      <body className="min-h-full">
        <template id="omnicult-direction" dangerouslySetInnerHTML={{ __html: DIRECTION_CONTRACT }} />
        <Providers>
          <Suspense fallback={null}>
            <ZoneMarker />
            <AmbientCanvas />
          </Suspense>
          <TooltipProvider>{children}</TooltipProvider>
          <Toaster />
        </Providers>
      </body>
    </html>
  );
}
