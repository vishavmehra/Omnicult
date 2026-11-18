import { Suspense } from "react";

import { AuthGate } from "@/components/auth/auth-gate";
import { AmbientBackground } from "@/components/creative/ambient-background";
import { CommandBarProvider } from "@/features/desk/command-bar";

// The Command Bar (Ctrl or Cmd+K) and the living ground are mounted once here, so they persist across every /app page;
// the ground changes its variant with the workspace instead of remounting. It reads the route (runtime data under Cache
// Components), hence its own Suspense boundary.
export default function AppLayout({ children }: LayoutProps<"/app">) {
  return (
    <>
      <Suspense fallback={null}>
        <AmbientBackground />
      </Suspense>
      <AuthGate>
        <CommandBarProvider>{children}</CommandBarProvider>
      </AuthGate>
    </>
  );
}
