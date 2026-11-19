"use client";

import { useSearchParams } from "next/navigation";

import { asPulseView, type PulseView } from "./logic";

/**
 * The Live Pulse view in the address (`?view=comments`), so a view can be linked to, reloaded and opened from a digest line. The
 * views are chosen in the workspace header's "In this workspace" row; add one by adding it to PULSE_VIEWS (logic.ts), to the
 * feature catalogue (components/shell/workspaces.ts) and rendering it where the view is read.
 */
export function usePulseView(): PulseView {
  return asPulseView(useSearchParams().get("view"));
}
