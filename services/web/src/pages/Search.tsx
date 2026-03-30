import { useEffect, useState } from "react";
import { ChevronDown, Search as SearchIcon } from "lucide-react";
import { apiFetch, type CodeContextRequest, type CodeContextResponse, type UserRepo } from "@/lib/api";
import { Navbar } from "@/components/Navbar";
import { useUser } from "@/lib/hooks";
import { SnippetCard } from "@/components/SnippetCard";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { cn } from "@/lib/utils";

const textareaClass =
  "w-full resize-none border border-input bg-transparent px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground rounded-none outline-none focus-visible:border-ring focus-visible:ring-1 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50";

export default function Search() {
  const { user, isLoading: userLoading } = useUser();
  const [repos, setRepos] = useState<UserRepo[]>([]);
  const [reposLoading, setReposLoading] = useState(true);
  const [reposError, setReposError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<CodeContextResponse | null>(null);
  const [filtersOpen, setFiltersOpen] = useState(false);

  const [repositoryName, setRepositoryName] = useState("");
  const [query, setQuery] = useState("");
  const [branch, setBranch] = useState("main");
  const [filePath, setFilePath] = useState("");

  useEffect(() => {
    if (!user) return;

    void apiFetch<UserRepo[]>("/v1/user/repos")
      .then((userRepos) => {
        setRepos(userRepos);
        setRepositoryName((current) => current || userRepos[0]?.full_name || "");
      })
      .catch((err) => {
        if (err instanceof Error) {
          setReposError(err.message);
        }
      })
      .finally(() => {
        setReposLoading(false);
      });
  }, [user]);

  useEffect(() => {
    if (!repositoryName || repos.length === 0) return;
    const repo = repos.find((r) => r.full_name === repositoryName);
    const firstBranch = repo?.branches[0]?.branch_name ?? "main";
    setBranch(firstBranch);
  }, [repositoryName, repos]);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    setResult(null);

    const payload: CodeContextRequest = {
      repository_name: repositoryName.trim(),
      query: query.trim(),
      branch: branch.trim() || "main",
    };

    const normalizedFilePath = filePath.trim();

    if (normalizedFilePath) payload.file_path = normalizedFilePath;

    try {
      const response = await apiFetch<CodeContextResponse>("/v1/search/search-code", {
        method: "POST",
        body: payload,
      });
      setResult(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Search request failed.");
    } finally {
      setSubmitting(false);
    }
  }

  if (userLoading && !user) return null;

  const canSubmit = !!repositoryName.trim() && !!query.trim() && !reposLoading && !submitting;
  const selectedRepo = repos.find((r) => r.full_name === repositoryName) ?? null;
  const availableBranches = (selectedRepo?.branches ?? []).filter((b) => b.status === "INDEXED");

  return (
    <>
      <Navbar user={user} />
      <main className="min-h-screen bg-background">
        {/* Hero section */}
        <div className="mx-auto max-w-3xl px-4 pt-16 pb-10 text-center">
          <h1 className="text-4xl font-semibold tracking-tight text-foreground">Lighthouse</h1>
          <p className="mt-2 text-sm text-muted-foreground">Search indexed code across your repositories</p>
        </div>

        {/* Search form */}
        <div className="mx-auto max-w-3xl px-4 pb-16">
          <form onSubmit={handleSubmit} className="space-y-4">
            {/* Search query */}
            <textarea
              id="search-query"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              rows={4}
              placeholder="Describe what you're looking for..."
              className={textareaClass}
            />

            {/* Repository + Branch */}
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="repository-name">Repository</Label>
                {reposLoading ? (
                  <Skeleton className="h-9 w-full" />
                ) : (
                  <Select value={repositoryName} onValueChange={setRepositoryName} disabled={repos.length === 0}>
                    <SelectTrigger id="repository-name" className="rounded-none">
                      <SelectValue
                        placeholder={repos.length === 0 ? "No repositories available" : "Select a repository"}
                      />
                    </SelectTrigger>
                    <SelectContent className="rounded-none">
                      {repos.map((repo) => (
                        <SelectItem key={repo.id} value={repo.full_name} className="rounded-none">
                          {repo.full_name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="branch">Branch</Label>
                {reposLoading ? (
                  <Skeleton className="h-9 w-full" />
                ) : availableBranches.length > 0 ? (
                  <Select value={branch} onValueChange={setBranch} disabled={repos.length === 0 || !repositoryName}>
                    <SelectTrigger id="branch" className="w-full rounded-none">
                      <SelectValue placeholder="Select a branch" />
                    </SelectTrigger>
                    <SelectContent className="rounded-none">
                      {availableBranches.map((b) => (
                        <SelectItem key={b.branch_name} value={b.branch_name} className="rounded-none">
                          {b.branch_name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                ) : (
                  <Input
                    id="branch"
                    value={branch}
                    onChange={(e) => setBranch(e.target.value)}
                    placeholder="main"
                    disabled={repos.length === 0}
                  />
                )}
              </div>
            </div>

            {/* Advanced filters */}
            <Collapsible open={filtersOpen} onOpenChange={setFiltersOpen}>
              <CollapsibleTrigger asChild>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="gap-1.5 text-muted-foreground hover:text-foreground hover:bg-transparent"
                >
                  <ChevronDown
                    className={cn("size-4 transition-transform duration-200", filtersOpen && "rotate-180")}
                  />
                  Advanced Filters
                </Button>
              </CollapsibleTrigger>
              <CollapsibleContent className="pt-3">
                <div className="space-y-4 border border-border p-4">
                  <div className="space-y-1.5">
                    <Label htmlFor="file-path">File Path</Label>
                    <Input
                      id="file-path"
                      value={filePath}
                      onChange={(e) => setFilePath(e.target.value)}
                      placeholder="src/auth.ts"
                    />
                  </div>
                </div>
              </CollapsibleContent>
            </Collapsible>

            {/* Errors */}
            {(reposError || error) && (
              <div className="border border-destructive/50 bg-destructive/10 px-4 py-3 text-xs text-destructive">
                {reposError || error}
              </div>
            )}

            {/* Submit */}
            <div className="flex justify-end">
              <Button type="submit" disabled={!canSubmit} size="lg" className="gap-2">
                <SearchIcon className="size-4" />
                {submitting ? "Searching..." : "Run Search"}
              </Button>
            </div>
          </form>
        </div>

        {/* Loading skeletons */}
        {submitting && (
          <div className="border-t border-border">
            <div className="mx-auto max-w-3xl space-y-4 px-4 py-10">
              <Skeleton className="h-40 w-full" />
              <Skeleton className="h-40 w-full" />
              <Skeleton className="h-40 w-full" />
            </div>
          </div>
        )}

        {/* Results */}
        {result && !submitting && (
          <div className="border-t border-border">
            <div className="mx-auto max-w-3xl space-y-6 px-4 py-10">
              {/* Summary row */}
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="outline">Status: {result.status}</Badge>
                <Badge variant="secondary">{result.repository_name}</Badge>
                <Badge variant="secondary">Branch: {result.branch}</Badge>
                <Badge variant="secondary">
                  {result.snippets.length} snippet{result.snippets.length !== 1 ? "s" : ""}
                </Badge>
              </div>

              {/* Message */}
              <p className="text-xs text-muted-foreground">{result.message}</p>

              {/* Snippet cards */}
              <div className="space-y-4">
                {result.snippets.length === 0 ? (
                  <div className="border border-dashed border-border bg-muted px-6 py-10 text-center text-xs text-muted-foreground">
                    No snippets returned.
                  </div>
                ) : (
                  result.snippets.map((snippet, index) => (
                    <SnippetCard
                      key={`${snippet.file_path}-${snippet.start_line}-${index}`}
                      snippet={snippet}
                      branch={result.branch}
                    />
                  ))
                )}
              </div>

              {/* Follow-up suggestions */}
              {result.follow_up.length > 0 && (
                <div className="border border-border p-4 space-y-2">
                  <h2 className="text-xs font-medium text-foreground uppercase tracking-wide">Follow-up Suggestions</h2>
                  <ul className="space-y-1">
                    {result.follow_up.map((item) => (
                      <li key={item} className="text-xs text-muted-foreground">
                        — {item}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </div>
        )}
      </main>
    </>
  );
}
