import type { Metadata } from "next";
import { Suspense } from "react";

import { LoadingState } from "@/components/states";
import { ProofWorkspace } from "@/features/workspaces/proof";

export const metadata: Metadata = { title: "Proof Vault" };

// Rendered inside the campaign layout's params boundary (see ../layout.tsx).
export const instant = false;

export default function Page() {
  // The open view, snapshot and claim live in the URL, which a client component reads under a Suspense boundary.
  return (
    <Suspense fallback={<LoadingState label="Opening Proof Vault…" />}>
      <ProofWorkspace />
    </Suspense>
  );
}
