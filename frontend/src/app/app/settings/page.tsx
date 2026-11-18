import type { Metadata } from "next";

import { TeamScreen } from "@/features/settings/team";

export const metadata: Metadata = { title: "Teams and roles" };
export const instant = false;

export default function Page() {
  return <TeamScreen />;
}
