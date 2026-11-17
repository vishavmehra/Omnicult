"use client";

import { ArrowRight } from "lucide-react";

import { ErrorState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { DemoSignInError, useStartDemo } from "@/features/desk/use-start-demo";
import { cn } from "@/lib/utils";

/** "Try the demo" on the landing page: a real action that opens the seeded demo campaign (labelled DEMO DATA). */
export function DemoAction({ className, label = "Try the demo" }: { className?: string; label?: string }) {
  const demo = useStartDemo();
  return (
    <div className={cn("space-y-3", className)}>
      <Button size="lg" onClick={() => demo.mutate()} disabled={demo.isPending} className="h-12 px-5 text-[15px]">
        {demo.isPending ? "Preparing the demo…" : label}
        <ArrowRight aria-hidden className="size-4" />
      </Button>
      {demo.error && (
        <div className="max-w-md">
          {demo.error instanceof DemoSignInError ? (
            <p role="alert" className="rounded-lg bg-danger-soft px-3 py-2 text-[13px] text-danger">
              {demo.error.message}
            </p>
          ) : (
            <ErrorState error={demo.error} onRetry={() => demo.mutate()} />
          )}
        </div>
      )}
    </div>
  );
}
