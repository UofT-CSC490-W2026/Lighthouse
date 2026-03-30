import useSWR from "swr";
import { apiFetch, type UserRepo } from "@/lib/api";
import { RepoCard } from "./RepoCard";
import { Skeleton } from "@/components/ui/skeleton";

const fetcher = () => apiFetch<UserRepo[]>("/v1/user/repos");

export function RepoList() {
  const { data, error, isLoading, mutate } = useSWR("repos", fetcher, {
    refreshInterval: 5000,
  });

  console.log(data);

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
          <Skeleton key={i} className="h-28 w-full" />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="border border-destructive/50 bg-destructive/10 px-4 py-3 text-sm text-destructive">
        Failed to load repositories. Please try again.
      </div>
    );
  }

  if (!data || data.length === 0) {
    return (
      <div className="border border-border bg-muted px-8 py-10 text-center">
        <p className="text-sm text-muted-foreground">No repositories added yet.</p>
        <p className="mt-1 text-xs text-muted-foreground/70">Add a GitHub repository to start indexing.</p>
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
          branches={repo.branches}
          onRemove={handleRemove}
          onBranchesUpdated={() => mutate()}
        />
      ))}
    </div>
  );
}
