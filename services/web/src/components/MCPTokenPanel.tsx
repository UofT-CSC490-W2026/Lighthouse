import { useEffect, useState } from "react";
import { apiFetch, type MCPTokenState } from "@/lib/api";

export function MCPTokenPanel() {
  const [tokenState, setTokenState] = useState<MCPTokenState | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    void loadToken();
  }, []);

  async function loadToken() {
    setLoading(true);
    setError(null);

    try {
      const response = await apiFetch<MCPTokenState>("/v1/auth/mcp-token");
      setTokenState(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load MCP token.");
    } finally {
      setLoading(false);
    }
  }

  async function handleCopy() {
    if (!tokenState?.token) {
      return;
    }

    try {
      await navigator.clipboard.writeText(tokenState.token);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      setError("Failed to copy token to clipboard.");
    }
  }

  async function handleRotate() {
    setSubmitting(true);
    setError(null);

    try {
      const response = await apiFetch<MCPTokenState>("/v1/auth/mcp-token", {
        method: "POST",
      });
      setTokenState(response);
      setCopied(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to rotate MCP token.");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleRevoke() {
    setSubmitting(true);
    setError(null);

    try {
      await apiFetch("/v1/auth/mcp-token", { method: "DELETE" });
      setTokenState({
        token: null,
        issued_at: null,
        has_token: false,
      });
      setCopied(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to revoke MCP token.");
    } finally {
      setSubmitting(false);
    }
  }

  const issuedAt = tokenState?.issued_at
    ? new Date(tokenState.issued_at).toLocaleString()
    : null;

  return (
    <section className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
      <button
        type="button"
        onClick={() => setExpanded((current) => !current)}
        className="flex w-full items-center justify-between text-left"
        aria-expanded={expanded}
      >
        <div className="space-y-1">
          <h2 className="text-lg font-semibold text-gray-900">MCP Token</h2>
          <p className="text-sm text-gray-600">
            Manage the long-lived token used by Cursor and other MCP clients.
          </p>
        </div>
        <span className="text-sm font-medium text-gray-500">
          {expanded ? "Hide" : "Show"}
        </span>
      </button>

      {expanded ? (
        <div className="mt-4 space-y-4">
          <div className="space-y-2">
            <p className="text-sm text-gray-600">
              Use this long-lived token in Cursor or another MCP client. It is
              separate from your current web sign-in and does not expire
              automatically. Rotating or revoking it does not sign you out of
              the dashboard.
            </p>
            <div className="rounded-lg border border-blue-100 bg-blue-50 p-3 text-sm text-blue-900">
              Authenticate your MCP client by sending this header:
              <code className="mt-2 block overflow-x-auto rounded bg-white px-3 py-2 text-xs text-blue-950">
                Authorization: Bearer YOUR_MCP_TOKEN
              </code>
            </div>
          </div>

          <div className="space-y-4">
            {loading ? (
              <div className="rounded-lg border border-gray-200 bg-gray-50 p-4 text-sm text-gray-500">
                Loading token details...
              </div>
            ) : tokenState?.has_token && tokenState.token ? (
              <div className="space-y-3">
                <div className="rounded-lg border border-gray-200 bg-gray-50 p-3">
                  <div className="text-xs font-medium uppercase tracking-wide text-gray-500">
                    Token
                  </div>
                  <code className="mt-2 block overflow-x-auto break-all text-sm text-gray-900">
                    {tokenState.token}
                  </code>
                </div>
                <p className="text-xs text-gray-500">
                  Issued {issuedAt ?? "just now"}
                </p>
              </div>
            ) : (
              <div className="rounded-lg border border-dashed border-gray-300 bg-gray-50 p-4 text-sm text-gray-600">
                No MCP token has been generated yet.
              </div>
            )}

            {error && (
              <div className="rounded-md bg-red-50 p-3 text-sm text-red-700">
                {error}
              </div>
            )}

            <div className="flex flex-wrap gap-3">
              {tokenState?.has_token && tokenState.token ? (
                <button
                  type="button"
                  onClick={handleCopy}
                  className="inline-flex items-center rounded-md border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 shadow-sm hover:bg-gray-50"
                >
                  {copied ? "Copied" : "Copy Token"}
                </button>
              ) : null}

              <button
                type="button"
                disabled={submitting}
                onClick={handleRotate}
                className="inline-flex items-center rounded-md bg-gray-900 px-3 py-2 text-sm font-medium text-white shadow-sm hover:bg-gray-800 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {submitting
                  ? "Working..."
                  : tokenState?.has_token
                    ? "Refresh Token"
                    : "Generate Token"}
              </button>

              {tokenState?.has_token ? (
                <button
                  type="button"
                  disabled={submitting}
                  onClick={handleRevoke}
                  className="inline-flex items-center rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm font-medium text-red-700 hover:bg-red-100 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Revoke Token
                </button>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}
