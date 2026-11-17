import type { Metadata } from "next";

import { StudioWorkspace } from "@/features/workspaces/studio";

export const metadata: Metadata = { title: "Creative Studio" };

// Rendered inside the campaign layout's params boundary (see ../layout.tsx).
export const instant = false;

export default function Page() {
  return <StudioWorkspace />;
}
