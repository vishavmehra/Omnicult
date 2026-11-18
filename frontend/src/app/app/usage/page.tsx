import type { Metadata } from "next";

import { UsageScreen } from "@/features/usage/usage-screen";

export const metadata: Metadata = { title: "Usage and credits" };
export const instant = false;

export default function Page() {
  return <UsageScreen />;
}
