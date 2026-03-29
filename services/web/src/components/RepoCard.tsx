import { useState } from "react";
import { ChevronDown } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { StatusBadge } from "./StatusBadge";
import type { BranchInfo, BranchStatus } from "@/lib/api";
import { cn } from "@/lib/utils";

interface RepoCardProps {
  repoId: string;
  repoUrl: string;
  indexStatus: BranchStatus | null;
  addedAt: string;
  branches: BranchInfo[];
  onRemove: (repoId: string) => void;
}

export function RepoCard({
  repoId,
  repoUrl,
  indexStatus,
  addedAt,
  branches,
  onRemove,
}: RepoCardProps) {
  const [branchesOpen, setBranchesOpen] = useState(false);

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

        {branches.length > 0 && (
          <Collapsible open={branchesOpen} onOpenChange={setBranchesOpen}>
            <CollapsibleTrigger asChild>
              <button
                type="button"
                className="mt-3 flex w-full items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                <ChevronDown
                  className={cn("size-3 transition-transform duration-200", branchesOpen && "rotate-180")}
                />
                {branches.length} branch{branches.length !== 1 ? "es" : ""}
              </button>
            </CollapsibleTrigger>
            <CollapsibleContent>
              <div className="mt-2 max-h-40 overflow-y-auto space-y-1">
                {branches.map((b) => (
                  <div key={b.branch_name} className="flex items-center justify-between py-0.5">
                    <span className="text-xs text-muted-foreground font-mono truncate mr-2">
                      {b.branch_name}
                    </span>
                    <StatusBadge status={b.status} />
                  </div>
                ))}
              </div>
            </CollapsibleContent>
          </Collapsible>
        )}
      </CardContent>
    </Card>
  );
}
