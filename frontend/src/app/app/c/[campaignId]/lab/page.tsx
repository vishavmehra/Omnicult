import type { Metadata } from "next";

import { LabWorkspace } from "@/features/workspaces/lab";

export const metadata: Metadata = { title: "Audience Lab" };

// Rendered inside the campaign layout's params boundary (see ../layout.tsx).
export const instant = false;

export default function Page() {
  return <LabWorkspace />;
}
