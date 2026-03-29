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

function toOptionalNumber(value: string): number | undefined {
  const trimmed = value.trim();
  if (!trimmed) return undefined;
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? parsed : undefined;
}

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
  const [taskDescription, setTaskDescription] = useState("");
  const [branch, setBranch] = useState("main");
  const [latestCommit, setLatestCommit] = useState("");
  const [filePath, setFilePath] = useState("");
  const [startLine, setStartLine] = useState("");
  const [endLine, setEndLine] = useState("");
  const [selectedText, setSelectedText] = useState("");
  const [surroundingContext, setSurroundingContext] = useState("");

  useEffect(() => {
    if (!user) return;

    void apiFetch<UserRepo[]>("/v1/user/repos")
      .then((userRepos) => {
        setRepos(userRepos);
        setRepositoryName((current) => current || userRepos[0]?.full_name || "");
        if (!branch.trim()) {
          setBranch("main");
        }
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

async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    setResult(null);

    const payload: CodeContextRequest = {
      repository_name: repositoryName.trim(),
      task_description: taskDescription.trim(),
      branch: branch.trim() || "main",
    };

    const normalizedLatestCommit = latestCommit.trim();
    const normalizedFilePath = filePath.trim();
    const normalizedSelectedText = selectedText.trim();
    const normalizedSurroundingContext = surroundingContext.trim();
    const normalizedStartLine = toOptionalNumber(startLine);
    const normalizedEndLine = toOptionalNumber(endLine);

    if (normalizedLatestCommit) payload.latest_commit = normalizedLatestCommit;
    if (normalizedFilePath) payload.file_path = normalizedFilePath;
    if (normalizedStartLine !== undefined) payload.start_line = normalizedStartLine;
    if (normalizedEndLine !== undefined) payload.end_line = normalizedEndLine;
    if (normalizedSelectedText) payload.selected_text = normalizedSelectedText;
    if (normalizedSurroundingContext) {
      payload.surrounding_context = normalizedSurroundingContext;
    }

    try {
      const response = await apiFetch<CodeContextResponse>("/v1/search/code-context", {
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

  const canSubmit = !!repositoryName.trim() && !!taskDescription.trim() && !reposLoading && !submitting;

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
            {/* Task description */}
            <textarea
              id="task-description"
              value={taskDescription}
              onChange={(e) => setTaskDescription(e.target.value)}
              rows={4}
              placeholder="Describe what you're looking for..."
              className={textareaClass}
            />

            {/* Repository + Branch */}
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="repository-name">Repository</Label>
                <Select
                  value={repositoryName}
                  onValueChange={setRepositoryName}
                  disabled={reposLoading || repos.length === 0}
                >
                  <SelectTrigger id="repository-name" className="rounded-none">
                    <SelectValue
                      placeholder={
                        reposLoading
                          ? "Loading repositories..."
                          : repos.length === 0
                            ? "No repositories available"
                            : "Select a repository"
                      }
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
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="branch">Branch</Label>
                <Input id="branch" value={branch} onChange={(e) => setBranch(e.target.value)} placeholder="main" />
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
                  <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                    <div className="space-y-1.5">
                      <Label htmlFor="file-path">File Path</Label>
                      <Input
                        id="file-path"
                        value={filePath}
                        onChange={(e) => setFilePath(e.target.value)}
                        placeholder="src/auth.ts"
                      />
                    </div>
                    <div className="space-y-1.5">
                      <Label htmlFor="latest-commit">Latest Commit</Label>
                      <Input
                        id="latest-commit"
                        value={latestCommit}
                        onChange={(e) => setLatestCommit(e.target.value)}
                        placeholder="Optional SHA"
                      />
                    </div>
                  </div>

                  <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                    <div className="space-y-1.5">
                      <Label htmlFor="start-line">Start Line</Label>
                      <Input
                        id="start-line"
                        type="number"
                        min="1"
                        value={startLine}
                        onChange={(e) => setStartLine(e.target.value)}
                        placeholder="Optional"
                      />
                    </div>
                    <div className="space-y-1.5">
                      <Label htmlFor="end-line">End Line</Label>
                      <Input
                        id="end-line"
                        type="number"
                        min="1"
                        value={endLine}
                        onChange={(e) => setEndLine(e.target.value)}
                        placeholder="Optional"
                      />
                    </div>
                  </div>

                  <div className="space-y-1.5">
                    <Label htmlFor="selected-text">Selected Text</Label>
                    <textarea
                      id="selected-text"
                      value={selectedText}
                      onChange={(e) => setSelectedText(e.target.value)}
                      rows={3}
                      placeholder="Optional highlighted text from the editor."
                      className={textareaClass}
                    />
                  </div>

                  <div className="space-y-1.5">
                    <Label htmlFor="surrounding-context">Surrounding Context</Label>
                    <textarea
                      id="surrounding-context"
                      value={surroundingContext}
                      onChange={(e) => setSurroundingContext(e.target.value)}
                      rows={4}
                      placeholder="Optional nearby code or notes from the editor."
                      className={textareaClass}
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
