"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import type { MouseEvent } from "react";

import { navigate } from "@/components/field/transition";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/** "Sign in" that keeps the scene continuous: a real link (new tab and no-JS still work), crossfaded when clicked. */
export function SignInLink({ variant, size, className }: { variant?: "outline" | "default"; size?: "lg"; className?: string }) {
  const router = useRouter();
  function onClick(e: MouseEvent<HTMLAnchorElement>) {
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return;
    e.preventDefault();
    navigate(router, "/login");
  }
  return (
    <Link href="/login" onClick={onClick} className={cn(buttonVariants({ variant, size }), className)}>
      Sign in
    </Link>
  );
}
