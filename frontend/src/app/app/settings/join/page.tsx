import type { Metadata } from "next";

import { JoinScreen } from "@/features/settings/join";

export const metadata: Metadata = { title: "Join a workspace" };
export const instant = false;

export default function Page() {
  return <JoinScreen />;
}
