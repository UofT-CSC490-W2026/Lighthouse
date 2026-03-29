import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "./StatusBadge";

interface RepoCardProps {
  repoId: string;
  repoUrl: string;
  indexStatus: string | null;
  addedAt: string;
  onRemove: (repoId: string) => void;
}

export function RepoCard({
  repoId,
  repoUrl,
  indexStatus,
  addedAt,
  onRemove,
}: RepoCardProps) {
  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex items-start justify-between">
          <div className="min-w-0 flex-1">
            <h3 className="text-sm font-semibold text-foreground truncate">
              <a
                href={repoUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="hover:text-primary transition-colors"
              >
                {repoId}
              </a>
            </h3>
          </div>
          <StatusBadge status={indexStatus} />
        </div>

        <div className="mt-3 flex items-center justify-between">
          <span className="text-xs text-muted-foreground">
            Added {new Date(addedAt).toLocaleDateString()}
          </span>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => onRemove(repoId)}
            className="text-destructive hover:text-destructive hover:bg-destructive/10 h-auto py-0.5 px-2 text-xs"
          >
            Remove
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
