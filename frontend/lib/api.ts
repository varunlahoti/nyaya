import type { SearchRequest, SearchResponse } from "./types";
import { getAccess, refreshTokens, clearTokens } from "./auth";

export class UnauthorizedError extends Error {}

async function authedFetch(input: string, init: RequestInit, retry = true): Promise<Response> {
  const res = await fetch(input, {
    ...init,
    headers: { ...(init.headers || {}), authorization: `Bearer ${getAccess()}` },
  });
  // Access token expired → try one refresh + replay.
  if (res.status === 401 && retry) {
    const ok = await refreshTokens();
    if (ok) return authedFetch(input, init, false);
    clearTokens();
    throw new UnauthorizedError("Session expired — please sign in again.");
  }
  return res;
}

// Requests go to /api/* which next.config.js rewrites to the backend.
export async function search(req: SearchRequest): Promise<SearchResponse> {
  const res = await authedFetch("/api/v1/search", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(req),
  });
  if (res.status === 401) throw new UnauthorizedError("Please sign in.");
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (body?.detail) detail = body.detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return res.json();
}
