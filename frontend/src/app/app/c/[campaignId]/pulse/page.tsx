import type { Metadata } from "next";

import { PulseWorkspace } from "@/features/workspaces/pulse";

export const metadata: Metadata = { title: "Live Pulse" };

// Rendered inside the campaign layout's params boundary (see ../layout.tsx).
export const instant = false;

export default function Page() {
  return <PulseWorkspace />;
}
