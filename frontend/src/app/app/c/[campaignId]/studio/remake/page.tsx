import type { Metadata } from "next";

import { RemakeWorkspace } from "@/features/remake/remake-workspace";

export const metadata: Metadata = { title: "Remake" };

// Rendered inside the campaign layout's params boundary (see ../../layout.tsx).
export const instant = false;

export default function Page() {
  return <RemakeWorkspace />;
}
