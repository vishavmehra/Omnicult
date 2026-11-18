import createClient, { type Middleware } from "openapi-fetch";

import { getAccessToken } from "@/lib/auth/token";
import { env } from "@/lib/env";

import type { paths } from "./schema";

const auth: Middleware = {
  async onRequest({ request }) {
    const token = await getAccessToken();
    if (token) request.headers.set("Authorization", `Bearer ${token}`);
    return request;
  },
};

/** Typed client for the Omnicult API (paths and bodies come from contracts/openapi.json). */
export const api = createClient<paths>({ baseUrl: env.apiBaseUrl });
api.use(auth);
