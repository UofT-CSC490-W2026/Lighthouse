const API_TOKEN_STORAGE_KEY = "LIGHTHOUSE_MCP_TOKEN";

function hasStorage() {
  return typeof window !== "undefined" && typeof window.localStorage !== "undefined";
}

export function getApiToken(): string | null {
  if (!hasStorage()) {
    return null;
  }

  const token = window.localStorage.getItem(API_TOKEN_STORAGE_KEY)?.trim();
  return token || null;
}

export function setApiToken(token: string): void {
  if (!hasStorage()) {
    return;
  }

  window.localStorage.setItem(API_TOKEN_STORAGE_KEY, token.trim());
}

export function clearApiToken(): void {
  if (!hasStorage()) {
    return;
  }

  window.localStorage.removeItem(API_TOKEN_STORAGE_KEY);
}
