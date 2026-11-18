"use client";

import { useMediaQuery } from "@/hooks/use-media-query";
import type { WorkspaceKey } from "@/components/shell/workspaces";

/**
 * Motion and role helpers shared by the creative primitives.
 *
 * - `useReducedMotion()`: true when the person asked for reduced motion. CSS motion is already collapsed by the global
 *   rule in globals.css; JS-driven motion (ambient, count-up, tilt) must read this hook.
 * - `useFinePointer()`: true on devices that hover with a precise pointer. Tilt and hover-scrub only switch on there.
 * - `roleColor(key, strong?)`: the CSS colour of a workspace role (identity only, never status or action).
 */
export function useReducedMotion() {
  return useMediaQuery("(prefers-reduced-motion: reduce)");
}

export function useFinePointer() {
  return useMediaQuery("(hover: hover) and (pointer: fine)");
}

export type RoleKey = WorkspaceKey;

export const roleColor = (key: RoleKey, strong = false) => `var(--role-${key}${strong ? "-strong" : ""})`;

/** The pastel tile class for a workspace (light: pastel clay; dark: a whisper of hue on graphite). */
export const roleTint = (key: RoleKey) => `tint-${key}`;
