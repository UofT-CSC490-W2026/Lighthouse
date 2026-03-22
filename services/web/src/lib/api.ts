const API_BASE = import.meta.env.VITE_MCP_URL || "";

export async function apiFetch<T>(
  path: string,
  options: { method?: string; body?: unknown } = {}
): Promise<T> {
  const { method = "GET", body } = options;

  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
    credentials: "include",
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${method} ${path} failed (${res.status}): ${text}`);
  }

  if (res.status === 204) return undefined as T;
  return res.json();
}

export interface User {
  id: string;
  github_id: number;
  github_login: string;
  display_name: string | null;
  avatar_url: string | null;
  email: string | null;
}

export interface UserRepo {
  id: string;
  repo_id: string;
  repo_url: string;
  display_name: string;
  ref: string;
  added_at: string;
  index_status: string | null;
}
