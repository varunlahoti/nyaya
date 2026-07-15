// Auth: token storage + auth API calls (JWT access + rotating refresh).

const ACCESS = "nyaya_access";
const REFRESH = "nyaya_refresh";

export interface AuthUser {
  id: string;
  email: string;
  full_name?: string;
  plan: string;
  role?: string;
}

export function getAccess(): string {
  if (typeof window === "undefined") return "";
  return localStorage.getItem(ACCESS) || "";
}
function getRefresh(): string {
  if (typeof window === "undefined") return "";
  return localStorage.getItem(REFRESH) || "";
}
export function setTokens(access: string, refresh: string) {
  localStorage.setItem(ACCESS, access);
  localStorage.setItem(REFRESH, refresh);
}
export function clearTokens() {
  localStorage.removeItem(ACCESS);
  localStorage.removeItem(REFRESH);
}
export function isAuthed(): boolean {
  return !!getAccess();
}

async function post(path: string, body: unknown) {
  const res = await fetch(`/api/v1/auth/${path}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = `Failed (${res.status})`;
    try {
      const j = await res.json();
      if (j?.detail) detail = j.detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return res.json();
}

export async function register(email: string, password: string, full_name: string) {
  const data = await post("register", { email, password, full_name });
  setTokens(data.access_token, data.refresh_token);
  return data.user as AuthUser;
}

export async function login(email: string, password: string) {
  const data = await post("login", { email, password });
  setTokens(data.access_token, data.refresh_token);
  return data.user as AuthUser;
}

export async function refreshTokens(): Promise<boolean> {
  const rt = getRefresh();
  if (!rt) return false;
  try {
    const data = await post("refresh", { refresh_token: rt });
    setTokens(data.access_token, data.refresh_token);
    return true;
  } catch {
    clearTokens();
    return false;
  }
}

export async function logout() {
  const rt = getRefresh();
  try {
    if (rt) await post("logout", { refresh_token: rt });
  } catch {
    /* ignore */
  }
  clearTokens();
}

export async function me(): Promise<AuthUser & { searches_today: number; daily_limit: number }> {
  const res = await fetch("/api/v1/auth/me", {
    headers: { authorization: `Bearer ${getAccess()}` },
  });
  if (!res.ok) throw new Error("unauthorized");
  return res.json();
}
