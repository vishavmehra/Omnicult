import type { Metadata } from "next";

import { DeskWorkspace } from "@/features/workspaces/desk";

export const metadata: Metadata = { title: "Campaign Desk" };

// Rendered inside the campaign layout's params boundary (see ../layout.tsx).
export const instant = false;

export default function Page() {
  return <DeskWorkspace />;
}
