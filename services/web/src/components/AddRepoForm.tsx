import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { apiFetch } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export function AddRepoForm() {
  const navigate = useNavigate();
  const [repoUrl, setRepoUrl] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);

    try {
      await apiFetch("/v1/user/repos", {
        method: "POST",
        body: { repo_url: repoUrl },
      });
      navigate("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div className="space-y-1.5">
        <Label htmlFor="repo-url">GitHub Repository</Label>
        <Input
          id="repo-url"
          type="text"
          value={repoUrl}
          onChange={(e) => setRepoUrl(e.target.value)}
          placeholder="https://github.com/owner/repo or owner/repo"
          required
        />
      </div>

      {error && (
        <div className="border border-destructive/50 bg-destructive/10 px-3 py-2 text-xs text-destructive">
          {error}
        </div>
      )}

      <div className="flex gap-3">
        <Button type="submit" disabled={loading || !repoUrl.trim()}>
          {loading ? "Adding..." : "Add & Index"}
        </Button>
        <Button type="button" variant="outline" onClick={() => navigate(-1)}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
