import type { Metadata } from "next";

import { XRayPage } from "@/features/xray/xray-page";

export const metadata: Metadata = { title: "Creative X-Ray" };

// Rendered inside the campaign layout's params boundary (see ../../layout.tsx).
export const instant = false;

export default function Page() {
  return <XRayPage />;
}
