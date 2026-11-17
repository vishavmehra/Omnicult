import type { Metadata } from "next";

import { LensWorkspace } from "@/features/workspaces/lens";

export const metadata: Metadata = { title: "Market Lens" };

// Rendered inside the campaign layout's params boundary (see ../layout.tsx).
export const instant = false;

export default function Page() {
  return <LensWorkspace />;
}
