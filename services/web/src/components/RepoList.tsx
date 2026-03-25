import useSWR from "swr";
import { apiFetch, type UserRepo } from "@/lib/api";
import { RepoCard } from "./RepoCard";

const fetcher = () => apiFetch<UserRepo[]>("/v1/user/repos");

export function RepoList() {
  const { data, error, isLoading, mutate } = useSWR("repos", fetcher, {
    refreshInterval: 5000,
  });

  async function handleRemove(repoId: string) {
    await apiFetch(`/v1/user/repos/${encodeURIComponent(repoId)}`, {
      method: "DELETE",
    });
    mutate();
  }

  if (isLoading) {
    return (
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {[1, 2, 3].map((i) => (
          <div
            key={i}
            className="h-28 rounded-lg border border-gray-200 bg-gray-50 animate-pulse"
          />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
        Failed to load repositories. Please try again.
      </div>
    );
  }

  if (!data || data.length === 0) {
    return (
      <div className="rounded-lg border border-gray-200 bg-gray-50 p-8 text-center">
        <p className="text-gray-500">No repositories added yet.</p>
        <p className="mt-1 text-sm text-gray-400">
          Add a GitHub repository to start indexing.
        </p>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      {data.map((repo) => (
        <RepoCard
          key={repo.id}
          repoId={repo.full_name}
          repoUrl={repo.repo_url}
          indexStatus={repo.index_status}
          addedAt={repo.added_at}
          onRemove={handleRemove}
        />
      ))}
    </div>
  );
}
