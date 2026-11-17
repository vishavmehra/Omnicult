import { redirect } from "next/navigation";

/**
 * The old Supabase OAuth return route. Firebase sign-in uses a popup and never lands here; old links and bookmarks are sent
 * to Campaign Desk, whose auth gate handles sign-in.
 */
export default function AuthCallback() {
  redirect("/app");
}
