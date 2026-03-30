import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { apiFetch, type AddUserRepoRequest } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Field, FieldDescription, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field";
import { parseBranchInput } from "@/lib/branches";

export function AddRepoForm() {
  const navigate = useNavigate();
  const [repoUrl, setRepoUrl] = useState("");
  const [branchInput, setBranchInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);

    try {
      const branches = parseBranchInput(branchInput);
      const body: AddUserRepoRequest = { repo_url: repoUrl };
      if (branches.length > 0) {
        body.branches = branches;
      }

      await apiFetch("/v1/user/repos", {
        method: "POST",
        body,
      });
      navigate("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-5">
      <FieldGroup>
        <Field>
          <FieldLabel htmlFor="repo-url">GitHub Repository</FieldLabel>
          <Input
            id="repo-url"
            type="text"
            value={repoUrl}
            onChange={(e) => {
              setRepoUrl(e.target.value);
              if (error) {
                setError(null);
              }
            }}
            placeholder="https://github.com/owner/repo or owner/repo"
            required
          />
        </Field>
        <Field>
          <FieldLabel htmlFor="repo-branches">Extra Branches</FieldLabel>
          <Input
            id="repo-branches"
            type="text"
            value={branchInput}
            onChange={(e) => {
              setBranchInput(e.target.value);
              if (error) {
                setError(null);
              }
            }}
            placeholder="feature/auth, release/next"
          />
          <FieldDescription>
            The default branch is always indexed. Add more branches as a comma-separated list.
          </FieldDescription>
        </Field>
        {error && <FieldError>{error}</FieldError>}
      </FieldGroup>

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
