import { Suspense } from "react";

import { LoadingState } from "@/components/states";
import { SettingsLayout } from "@/features/settings/frame";

// Settings reads ?w= (useSearchParams), which is runtime data under Cache Components.
export default function Layout({ children }: LayoutProps<"/app/settings">) {
  return (
    <Suspense fallback={<div className="grid min-h-dvh place-items-center bg-canvas"><LoadingState label="Opening settings…" /></div>}>
      <SettingsLayout>{children}</SettingsLayout>
    </Suspense>
  );
}
