import Link from "next/link";

import { buttonVariants } from "@/components/ui/button";

export default function NotFound() {
  return (
    <main id="main" className="grid min-h-dvh place-items-center bg-canvas px-4">
      <div className="max-w-md space-y-4">
        <h1 className="type-title text-[34px] text-ink">This page does not exist</h1>
        <p className="text-[14.5px] text-ink-secondary">The link may be mistyped, or the campaign may have been archived or belong to another account.</p>
        <Link href="/app" className={buttonVariants({ size: "lg" })}>
          Go to Campaign Desk
        </Link>
      </div>
    </main>
  );
}
