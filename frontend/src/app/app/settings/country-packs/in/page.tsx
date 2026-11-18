import type { Metadata } from "next";

import { CountryPackScreen } from "@/features/settings/country-pack";

export const metadata: Metadata = { title: "India Country Pack" };
export const instant = false;

export default function Page() {
  return <CountryPackScreen />;
}
