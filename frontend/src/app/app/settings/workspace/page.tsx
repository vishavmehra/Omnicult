import type { Metadata } from "next";

import { WorkspaceScreen } from "@/features/settings/workspace";

export const metadata: Metadata = { title: "Workspace settings" };
export const instant = false;

export default function Page() {
  return <WorkspaceScreen />;
}
