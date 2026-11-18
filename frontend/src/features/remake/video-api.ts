"use client";

import { useMutation, useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";

export type VideoRequest = components["schemas"]["RemakeVideoRequest"];
export type VideoPreview = components["schemas"]["RemakeVideoPreview"];
export type VideoRemake = components["schemas"]["VideoRemake"];

/** What a clip request would do: the exact start frame, prompt and cost. Makes no model call and costs nothing. */
export function useVideoPreview(campaignId: string, body: Omit<VideoRequest, "confirm_cost"> | null) {
  return useQuery({
    queryKey: ["remake", "video-preview", campaignId, body],
    enabled: body !== null,
    refetchOnWindowFocus: false,
    queryFn: () =>
      unwrap(
        api.POST("/api/v1/campaigns/{campaign_id}/remakes/video/preview", {
          params: { path: { campaign_id: campaignId } },
          body: { ...body!, confirm_cost: false },
        }),
      ),
  });
}

/** Start one clip (one paid Veo call in a live project). */
export function useStartVideo(campaignId: string) {
  return useMutation({
    mutationFn: (body: VideoRequest) =>
      unwrap(api.POST("/api/v1/campaigns/{campaign_id}/remakes/video", { params: { path: { campaign_id: campaignId } }, body })),
  });
}

/** True for the `scene` element Remake: Video writes (it holds a clip, not a still), so Remake: Visuals never offers it. */
export function isVideoClip(element: { value?: unknown }): boolean {
  const value = element.value;
  return typeof value === "object" && value !== null && (value as { media?: unknown }).media === "video";
}
