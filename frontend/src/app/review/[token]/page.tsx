import type { Metadata } from "next";

import { ReviewPageView } from "@/features/launch/review-page";

// A review link is a private address: keep it out of search results and never send it on as a referrer.
export const metadata: Metadata = { title: "Review", robots: { index: false, follow: false, nocache: true }, referrer: "no-referrer" };

// Rendered inside the layout's Suspense boundary: the secret is read on the client.
export const instant = false;

export default function Page() {
  return <ReviewPageView />;
}
