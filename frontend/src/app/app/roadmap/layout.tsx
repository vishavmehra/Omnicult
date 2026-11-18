import { Suspense } from "react";

import { LoadingState } from "@/components/states";
import { PlatformShell } from "@/features/usage/frame";

export default function Layout({ children }: LayoutProps<"/app/roadmap">) {
  return (
    <Suspense fallback={<div className="grid min-h-dvh place-items-center bg-canvas"><LoadingState label="Opening the roadmap…" /></div>}>
      <PlatformShell active="roadmap">{children}</PlatformShell>
    </Suspense>
  );
}
