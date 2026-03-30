import { clearApiToken, getApiToken } from "@/lib/auth";

const API_BASE = import.meta.env.VITE_MCP_URL || "";

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function getErrorDetail(res: Response): Promise<string> {
  const contentType = res.headers.get("content-type") || "";

  if (contentType.includes("application/json")) {
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === "string" && body.detail.trim()) {
        return body.detail;
      }
      return JSON.stringify(body);
    } catch {
      /* fall through */
    }
  }

  const text = await res.text();
  return text || res.statusText || "Request failed";
}

export async function apiFetch<T>(
  path: string,
  options: { method?: string; body?: unknown } = {}
): Promise<T> {
  const { method = "GET", body } = options;
  const headers = new Headers();
  const apiToken = getApiToken();

  if (body) {
    headers.set("Content-Type", "application/json");
  }
  if (apiToken) {
    headers.set("Authorization", `Bearer ${apiToken}`);
  }

  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });

  if (!res.ok) {
    if (res.status === 401) {
      clearApiToken();
    }
    const detail = await getErrorDetail(res);
    throw new ApiError(`${method} ${path} failed (${res.status}): ${detail}`, res.status);
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

export type BranchStatus = "PENDING" | "INDEXING" | "INDEXED" | "FAILED";

export interface BranchInfo {
  branch_name: string;
  status: BranchStatus;
}

export interface UserRepo {
  id: string;
  github_repo_id: number;
  full_name: string;
  repo_url: string;
  display_name: string;
  added_at: string;
  index_status: BranchStatus | null;
  branches: BranchInfo[];
}

export interface AddUserRepoRequest {
  repo_url: string;
  branches?: string[];
}

export interface AddRepoBranchesRequest {
  branches: string[];
}

export interface MCPTokenState {
  token: string | null;
  issued_at: string | null;
  has_token: boolean;
}

export interface CodeContextRequest {
  repository_name: string;
  query: string;
  branch?: string;
  file_path?: string;
}

export interface CodeContextSnippet {
  file_path: string;
  start_line: number | null;
  end_line: number | null;
  content: string;
  reason: string | null;
}

export interface CodeContextResponse {
  status: string;
  message: string;
  repository_name: string;
  branch: string;
  query: string;
  requested_by_user_id: string;
  snippets: CodeContextSnippet[];
  follow_up: string[];
}
