import type { Metadata } from "next";

import { ProofWorkspace } from "@/features/workspaces/proof";

export const metadata: Metadata = { title: "Proof Vault" };

// Rendered inside the campaign layout's params boundary (see ../layout.tsx).
export const instant = false;

export default function Page() {
  return <ProofWorkspace />;
}
