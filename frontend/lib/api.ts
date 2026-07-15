import type { SearchRequest, SearchResponse } from "./types";

// Requests go to /api/* which next.config.js rewrites to the backend.
export async function search(req: SearchRequest): Promise<SearchResponse> {
  const res = await fetch("/api/v1/search", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(req),
  });
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
