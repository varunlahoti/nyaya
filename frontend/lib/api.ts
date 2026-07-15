import type { SearchRequest, SearchResponse } from "./types";

const PW_KEY = "nyaya_pw";

export function getPassword(): string {
  if (typeof window === "undefined") return "";
  return window.localStorage.getItem(PW_KEY) || "";
}

export function setPassword(pw: string) {
  window.localStorage.setItem(PW_KEY, pw);
}

export function clearPassword() {
  window.localStorage.removeItem(PW_KEY);
}

export class UnauthorizedError extends Error {}

// Requests go to /api/* which next.config.js rewrites to the backend.
export async function search(req: SearchRequest): Promise<SearchResponse> {
  const res = await fetch("/api/v1/search", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-app-password": getPassword(),
    },
    body: JSON.stringify(req),
  });
  if (res.status === 401) {
    throw new UnauthorizedError("Wrong password.");
  }
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
