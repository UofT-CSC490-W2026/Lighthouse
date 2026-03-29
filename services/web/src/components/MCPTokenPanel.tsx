import { useEffect, useState } from "react";
import { ChevronDown } from "lucide-react";
import { apiFetch, type MCPTokenState } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

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
    if (!tokenState?.token) return;

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
      setTokenState({ token: null, issued_at: null, has_token: false });
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
    <Card>
      <CardContent className="p-5">
        <button
          type="button"
          onClick={() => setExpanded((current) => !current)}
          className="flex w-full items-center justify-between text-left"
          aria-expanded={expanded}
        >
          <div className="space-y-0.5">
            <h2 className="text-base font-semibold text-foreground">MCP Token</h2>
            <p className="text-xs text-muted-foreground">
              Manage the long-lived token used by Cursor and other MCP clients.
            </p>
          </div>
          <ChevronDown
            className={cn(
              "size-4 text-muted-foreground transition-transform duration-200",
              expanded && "rotate-180"
            )}
          />
        </button>

        {expanded ? (
          <div className="mt-4 space-y-4">
            <div className="space-y-2">
              <p className="text-xs text-muted-foreground">
                Use this long-lived token in Cursor or another MCP client. It is
                separate from your current web sign-in and does not expire
                automatically. Rotating or revoking it does not sign you out of
                the dashboard.
              </p>
              <div className="border border-border bg-muted px-3 py-2.5 text-xs text-foreground">
                Authenticate your MCP client by sending this header:
                <code className="mt-1.5 block overflow-x-auto bg-background px-3 py-1.5 text-xs text-muted-foreground font-mono">
                  Authorization: Bearer YOUR_MCP_TOKEN
                </code>
              </div>
            </div>

            <div className="space-y-4">
              {loading ? (
                <div className="border border-border bg-muted px-4 py-3 text-xs text-muted-foreground">
                  Loading token details...
                </div>
              ) : tokenState?.has_token && tokenState.token ? (
                <div className="space-y-3">
                  <div className="border border-border bg-muted p-3">
                    <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                      Token
                    </div>
                    <code className="mt-2 block overflow-x-auto break-all text-xs text-foreground font-mono">
                      {tokenState.token}
                    </code>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    Issued {issuedAt ?? "just now"}
                  </p>
                </div>
              ) : (
                <div className="border border-dashed border-border bg-muted px-4 py-3 text-xs text-muted-foreground">
                  No MCP token has been generated yet.
                </div>
              )}

              {error && (
                <div className="border border-destructive/50 bg-destructive/10 px-3 py-2 text-xs text-destructive">
                  {error}
                </div>
              )}

              <div className="flex flex-wrap gap-2">
                {tokenState?.has_token && tokenState.token ? (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={handleCopy}
                  >
                    {copied ? "Copied!" : "Copy Token"}
                  </Button>
                ) : null}

                <Button
                  type="button"
                  size="sm"
                  disabled={submitting}
                  onClick={handleRotate}
                >
                  {submitting
                    ? "Working..."
                    : tokenState?.has_token
                      ? "Refresh Token"
                      : "Generate Token"}
                </Button>

                {tokenState?.has_token ? (
                  <Button
                    type="button"
                    variant="destructive"
                    size="sm"
                    disabled={submitting}
                    onClick={handleRevoke}
                  >
                    Revoke Token
                  </Button>
                ) : null}
              </div>
            </div>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
