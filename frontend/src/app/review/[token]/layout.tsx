import { Suspense } from "react";

import { LoadingState } from "@/components/states";

// The page reads the review secret from the address on the client (runtime data under Cache Components), like the campaign shell.
export default function ReviewLayout({ children }: LayoutProps<"/review/[token]">) {
  return <Suspense fallback={<div className="grid min-h-dvh place-items-center"><LoadingState label="Opening the review…" /></div>}>{children}</Suspense>;
}
