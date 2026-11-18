import type { Metadata } from "next";

import { Roadmap } from "@/features/roadmap/roadmap";

export const metadata: Metadata = { title: "Roadmap" };

export default function Page() {
  return <Roadmap />;
}
