import { redirect } from "next/navigation";

export const instant = false;

/** A bare campaign link opens its Campaign Desk. */
export default async function CampaignIndex({ params }: PageProps<"/app/c/[campaignId]">) {
  const { campaignId } = await params;
  redirect(`/app/c/${encodeURIComponent(campaignId)}/desk`);
}
