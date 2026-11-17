"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { signInAnonymously } from "firebase/auth";
import { useRouter } from "next/navigation";

import { navigate } from "@/components/field/transition";
import { projectKeys } from "@/features/project/project-context";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { firebaseErrorMessage, getFirebaseAuth } from "@/lib/auth/firebase";
import { env } from "@/lib/env";

/** A sign-in failure before the demo project is created. Carries plain-language text for ErrorState. */
export class DemoSignInError extends Error {}

/**
 * "Try the demo": make sure there is a session (anonymous in Firebase mode), create the server-seeded demo brand, then open
 * its newest campaign in Campaign Desk. Everything it shows is labelled DEMO DATA by the backend.
 */
export function useStartDemo() {
  const router = useRouter();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      if (env.authMode === "firebase") {
        const auth = getFirebaseAuth();
        await auth.authStateReady();
        if (!auth.currentUser) {
          try {
            await signInAnonymously(auth);
          } catch (error) {
            throw new DemoSignInError(firebaseErrorMessage(error));
          }
        }
      }
      const project = await unwrap(api.POST("/api/v1/projects/demo"));
      const campaigns = await unwrap(
        api.GET("/api/v1/projects/{project_id}/campaigns", { params: { path: { project_id: project.id }, query: { limit: 100 } } }),
      );
      const newest = [...campaigns.items].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at))[0];
      return { project, campaignId: newest?.id ?? null };
    },
    onSuccess: ({ campaignId }) => {
      void queryClient.invalidateQueries({ queryKey: projectKeys.list });
      void queryClient.invalidateQueries({ queryKey: ["directory"] });
      navigate(router, campaignId ? `/app/c/${campaignId}/desk` : "/app");
    },
  });
}
