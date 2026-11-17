import type { Metadata } from "next";

import { LaunchWorkspace } from "@/features/workspaces/launch";

export const metadata: Metadata = { title: "Launch Room" };

// Rendered inside the campaign layout's params boundary (see ../layout.tsx).
export const instant = false;

export default function Page() {
  return <LaunchWorkspace />;
}
