import { StatusBadge } from "./StatusBadge";

interface RepoCardProps {
  repoId: string;
  repoUrl: string;
  branch: string;
  indexStatus: string | null;
  addedAt: string;
  onRemove: (repoId: string) => void;
}

export function RepoCard({
  repoId,
  repoUrl,
  branch,
  indexStatus,
  addedAt,
  onRemove,
}: RepoCardProps) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm hover:shadow-md transition-shadow">
      <div className="flex items-start justify-between">
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-semibold text-gray-900 truncate">
            <a
              href={repoUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="hover:text-blue-600"
            >
              {repoId}
            </a>
          </h3>
          <p className="mt-1 text-xs text-gray-500">
            Branch: <span className="font-mono">{branch}</span>
          </p>
        </div>
        <StatusBadge status={indexStatus} />
      </div>

      <div className="mt-3 flex items-center justify-between">
        <span className="text-xs text-gray-400">
          Added {new Date(addedAt).toLocaleDateString()}
        </span>
        <button
          onClick={() => onRemove(repoId)}
          className="text-xs text-red-500 hover:text-red-700"
        >
          Remove
        </button>
      </div>
    </div>
  );
}
