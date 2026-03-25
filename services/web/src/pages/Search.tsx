import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  apiFetch,
  type CodeContextRequest,
  type CodeContextResponse,
  type User,
  type UserRepo,
} from "@/lib/api";
import { clearApiToken, getApiToken } from "@/lib/auth";
import { Navbar } from "@/components/Navbar";

function toOptionalNumber(value: string): number | undefined {
  const trimmed = value.trim();
  if (!trimmed) return undefined;
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? parsed : undefined;
}

export default function Search() {
  const navigate = useNavigate();
  const [user, setUser] = useState<User | null>(null);
  const [repos, setRepos] = useState<UserRepo[]>([]);
  const [reposLoading, setReposLoading] = useState(true);
  const [reposError, setReposError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<CodeContextResponse | null>(null);

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
    if (!getApiToken()) {
      navigate("/login", { replace: true });
      return;
    }

    void Promise.all([
      apiFetch<User>("/v1/auth/me"),
      apiFetch<UserRepo[]>("/v1/user/repos"),
    ])
      .then(([currentUser, userRepos]) => {
        setUser(currentUser);
        setRepos(userRepos);
        setRepositoryName((current) => current || userRepos[0]?.full_name || "");
        if (!branch.trim()) {
          setBranch("main");
        }
      })
      .catch((err) => {
        clearApiToken();
        navigate("/login", { replace: true });
        if (err instanceof Error) {
          setReposError(err.message);
        }
      })
      .finally(() => {
        setReposLoading(false);
      });
  }, [navigate]);

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
      const response = await apiFetch<CodeContextResponse>(
        "/v1/search/code-context",
        {
          method: "POST",
          body: payload,
        }
      );
      setResult(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Search request failed.");
    } finally {
      setSubmitting(false);
    }
  }

  if (!user) return null;

  const canSubmit =
    !!repositoryName.trim() && !!taskDescription.trim() && !reposLoading && !submitting;

  return (
    <>
      <Navbar user={user} />
      <main className="mx-auto max-w-5xl px-4 py-8 sm:px-6 lg:px-8">
        <div className="space-y-6">
          <div className="flex items-start justify-between gap-4">
            <div className="space-y-1">
              <h1 className="text-2xl font-semibold text-gray-900">
                Search Indexed Code
              </h1>
              <p className="text-sm text-gray-600">
                Send a code-context query through the MCP server and inspect the
                raw response.
              </p>
            </div>
            <Link
              to="/dashboard"
              className="inline-flex items-center rounded-md border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 shadow-sm hover:bg-gray-50"
            >
              Back to Dashboard
            </Link>
          </div>

          <section className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
            <form onSubmit={handleSubmit} className="space-y-5">
              <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
                <div>
                  <label
                    htmlFor="repository-name"
                    className="block text-sm font-medium text-gray-700"
                  >
                    Repository
                  </label>
                  <select
                    id="repository-name"
                    value={repositoryName}
                    onChange={(e) => setRepositoryName(e.target.value)}
                    disabled={reposLoading || repos.length === 0}
                    className="mt-1 block w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:cursor-not-allowed disabled:bg-gray-50"
                  >
                    <option value="">
                      {reposLoading
                        ? "Loading repositories..."
                        : repos.length === 0
                          ? "No repositories available"
                          : "Select a repository"}
                    </option>
                    {repos.map((repo) => (
                      <option key={repo.id} value={repo.full_name}>
                        {repo.full_name}
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label
                    htmlFor="branch"
                    className="block text-sm font-medium text-gray-700"
                  >
                    Branch
                  </label>
                  <input
                    id="branch"
                    type="text"
                    value={branch}
                    onChange={(e) => setBranch(e.target.value)}
                    placeholder="main"
                    className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                  />
                </div>
              </div>

              <div>
                <label
                  htmlFor="task-description"
                  className="block text-sm font-medium text-gray-700"
                >
                  Task Description
                </label>
                <textarea
                  id="task-description"
                  value={taskDescription}
                  onChange={(e) => setTaskDescription(e.target.value)}
                  rows={4}
                  placeholder="Describe what context you want to retrieve."
                  className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
              </div>

              <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
                <div>
                  <label
                    htmlFor="file-path"
                    className="block text-sm font-medium text-gray-700"
                  >
                    File Path
                  </label>
                  <input
                    id="file-path"
                    type="text"
                    value={filePath}
                    onChange={(e) => setFilePath(e.target.value)}
                    placeholder="src/auth.ts"
                    className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                  />
                </div>

                <div>
                  <label
                    htmlFor="latest-commit"
                    className="block text-sm font-medium text-gray-700"
                  >
                    Latest Commit
                  </label>
                  <input
                    id="latest-commit"
                    type="text"
                    value={latestCommit}
                    onChange={(e) => setLatestCommit(e.target.value)}
                    placeholder="Optional SHA"
                    className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                  />
                </div>
              </div>

              <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
                <div>
                  <label
                    htmlFor="start-line"
                    className="block text-sm font-medium text-gray-700"
                  >
                    Start Line
                  </label>
                  <input
                    id="start-line"
                    type="number"
                    min="1"
                    value={startLine}
                    onChange={(e) => setStartLine(e.target.value)}
                    placeholder="Optional"
                    className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                  />
                </div>

                <div>
                  <label
                    htmlFor="end-line"
                    className="block text-sm font-medium text-gray-700"
                  >
                    End Line
                  </label>
                  <input
                    id="end-line"
                    type="number"
                    min="1"
                    value={endLine}
                    onChange={(e) => setEndLine(e.target.value)}
                    placeholder="Optional"
                    className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                  />
                </div>
              </div>

              <div>
                <label
                  htmlFor="selected-text"
                  className="block text-sm font-medium text-gray-700"
                >
                  Selected Text
                </label>
                <textarea
                  id="selected-text"
                  value={selectedText}
                  onChange={(e) => setSelectedText(e.target.value)}
                  rows={3}
                  placeholder="Optional highlighted text from the editor."
                  className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
              </div>

              <div>
                <label
                  htmlFor="surrounding-context"
                  className="block text-sm font-medium text-gray-700"
                >
                  Surrounding Context
                </label>
                <textarea
                  id="surrounding-context"
                  value={surroundingContext}
                  onChange={(e) => setSurroundingContext(e.target.value)}
                  rows={4}
                  placeholder="Optional nearby code or notes from the editor."
                  className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
              </div>

              {reposError ? (
                <div className="rounded-md bg-red-50 p-3 text-sm text-red-700">
                  {reposError}
                </div>
              ) : null}

              {error ? (
                <div className="rounded-md bg-red-50 p-3 text-sm text-red-700">
                  {error}
                </div>
              ) : null}

              <div className="flex items-center gap-3">
                <button
                  type="submit"
                  disabled={!canSubmit}
                  className="inline-flex items-center rounded-md bg-gray-900 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-gray-800 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {submitting ? "Searching..." : "Run Search"}
                </button>
                <span className="text-sm text-gray-500">
                  Uses the authenticated MCP HTTP endpoint.
                </span>
              </div>
            </form>
          </section>

          {result ? (
            <section className="space-y-4 rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
              <div className="flex flex-wrap items-center gap-3">
                <span className="inline-flex items-center rounded-full bg-blue-50 px-3 py-1 text-xs font-medium text-blue-700">
                  Status: {result.status}
                </span>
                <span className="inline-flex items-center rounded-full bg-gray-100 px-3 py-1 text-xs font-medium text-gray-700">
                  Repo: {result.repository_name}
                </span>
                <span className="inline-flex items-center rounded-full bg-gray-100 px-3 py-1 text-xs font-medium text-gray-700">
                  Branch: {result.branch}
                </span>
                <span className="inline-flex items-center rounded-full bg-gray-100 px-3 py-1 text-xs font-medium text-gray-700">
                  Snippets: {result.snippets.length}
                </span>
              </div>

              <div className="rounded-lg border border-gray-200 bg-gray-50 p-4 text-sm text-gray-700">
                {result.message}
              </div>

              {result.highlight.file_path ||
              result.highlight.start_line !== null ||
              result.highlight.selected_text ||
              result.highlight.surrounding_context ? (
                <div className="rounded-lg border border-gray-200 p-4">
                  <h2 className="text-sm font-semibold text-gray-900">
                    Request Highlight
                  </h2>
                  <dl className="mt-3 grid grid-cols-1 gap-3 text-sm text-gray-700 md:grid-cols-2">
                    <div>
                      <dt className="font-medium text-gray-900">File Path</dt>
                      <dd>{result.highlight.file_path || "N/A"}</dd>
                    </div>
                    <div>
                      <dt className="font-medium text-gray-900">Line Range</dt>
                      <dd>
                        {result.highlight.start_line ?? "N/A"} -{" "}
                        {result.highlight.end_line ?? "N/A"}
                      </dd>
                    </div>
                  </dl>
                  {result.highlight.selected_text ? (
                    <div className="mt-3">
                      <div className="text-sm font-medium text-gray-900">
                        Selected Text
                      </div>
                      <pre className="mt-1 overflow-x-auto rounded-md bg-gray-50 p-3 text-xs text-gray-800">
                        <code>{result.highlight.selected_text}</code>
                      </pre>
                    </div>
                  ) : null}
                  {result.highlight.surrounding_context ? (
                    <div className="mt-3">
                      <div className="text-sm font-medium text-gray-900">
                        Surrounding Context
                      </div>
                      <pre className="mt-1 overflow-x-auto rounded-md bg-gray-50 p-3 text-xs text-gray-800 whitespace-pre-wrap">
                        <code>{result.highlight.surrounding_context}</code>
                      </pre>
                    </div>
                  ) : null}
                </div>
              ) : null}

              <div className="space-y-4">
                {result.snippets.length === 0 ? (
                  <div className="rounded-lg border border-dashed border-gray-300 bg-gray-50 p-6 text-sm text-gray-600">
                    No snippets returned.
                  </div>
                ) : (
                  result.snippets.map((snippet, index) => (
                    <article
                      key={`${snippet.file_path}-${snippet.start_line}-${index}`}
                      className="overflow-hidden rounded-lg border border-gray-200"
                    >
                      <div className="flex flex-wrap items-center gap-3 border-b border-gray-200 bg-gray-50 px-4 py-3 text-sm">
                        <span className="font-medium text-gray-900">
                          {snippet.file_path}
                        </span>
                        <span className="text-gray-500">
                          Lines {snippet.start_line ?? "?"} -{" "}
                          {snippet.end_line ?? "?"}
                        </span>
                        {snippet.reason ? (
                          <span className="rounded-full bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700">
                            {snippet.reason}
                          </span>
                        ) : null}
                      </div>
                      <pre className="overflow-x-auto bg-white p-4 text-xs text-gray-900">
                        <code>{snippet.content}</code>
                      </pre>
                    </article>
                  ))
                )}
              </div>

              {result.follow_up.length > 0 ? (
                <div className="rounded-lg border border-gray-200 p-4">
                  <h2 className="text-sm font-semibold text-gray-900">
                    Follow-up
                  </h2>
                  <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-gray-700">
                    {result.follow_up.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </section>
          ) : null}
        </div>
      </main>
    </>
  );
}
