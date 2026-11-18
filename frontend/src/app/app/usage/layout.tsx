import { Suspense } from "react";

import { LoadingState } from "@/components/states";
import { PlatformShell } from "@/features/usage/frame";

// The page reads ?w=, ?days= and ?mode= (useSearchParams), which is runtime data under Cache Components.
export default function Layout({ children }: LayoutProps<"/app/usage">) {
  return (
    <Suspense fallback={<div className="grid min-h-dvh place-items-center bg-canvas"><LoadingState label="Opening usage…" /></div>}>
      <PlatformShell active="usage">{children}</PlatformShell>
    </Suspense>
  );
}
