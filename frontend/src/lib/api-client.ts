const TOKEN_KEY = "taskboard_token";
const USER_KEY = "taskboard_user";

export type StoredUser = { id: string; email: string; name: string };

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function getStoredUser(): StoredUser | null {
  if (typeof window === "undefined") return null;
  const raw = window.localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as StoredUser;
  } catch {
    return null;
  }
}

export function setSession(token: string, user: StoredUser) {
  window.localStorage.setItem(TOKEN_KEY, token);
  window.localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function clearSession() {
  window.localStorage.removeItem(TOKEN_KEY);
  window.localStorage.removeItem(USER_KEY);
}

export async function apiFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  // Login/register exchange credentials for a token; an old token has no business there.
  const token = path.startsWith("/api/auth/") ? null : getToken();
  const headers = new Headers(options.headers);
  headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const res = await fetch(path, { ...options, headers });
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;

  if (!res.ok) {
    // A 401 on a request that carried a token means the session is dead (expired, or its
    // user was deleted, e.g. by a reseed). Drop it and go sign in again instead of
    // leaving every page failing.
    if (res.status === 401 && token) {
      clearSession();
      window.location.assign("/login");
    }
    const message =
      (data && ((data.error as string) || (data.detail as string))) ||
      `request failed (${res.status})`;
    throw new Error(message);
  }
  return data as T;
}
