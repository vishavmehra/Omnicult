import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";

/** A native select in the same well as Input: one control vocabulary, real keyboard and screen-reader behaviour. */
export function NativeSelect({ className, ...props }: ComponentProps<"select">) {
  return (
    <select
      className={cn(
        "h-8 w-full min-w-0 rounded-lg border border-input bg-surface-raised px-2 text-sm text-ink shadow-well outline-none focus-visible:border-ring disabled:cursor-not-allowed disabled:opacity-50 dark:bg-surface-muted",
        className,
      )}
      {...props}
    />
  );
}
