import type { Metadata } from "next";

import { GenerateWorkspace } from "@/features/generate/generate-workspace";

export const metadata: Metadata = { title: "Generate" };

// Rendered inside the campaign layout's params boundary (see ../../layout.tsx).
export const instant = false;

export default function Page() {
  return <GenerateWorkspace />;
}
