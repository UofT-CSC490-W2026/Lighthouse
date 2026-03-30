import { useState } from "react";
import { ChevronDown, GitBranchPlus } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Field, FieldDescription, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { StatusBadge } from "./StatusBadge";
import { apiFetch, type AddRepoBranchesRequest, type BranchInfo, type BranchStatus } from "@/lib/api";
import { parseBranchInput } from "@/lib/branches";
import { cn } from "@/lib/utils";

interface RepoCardProps {
  repoId: string;
  repoUrl: string;
  indexStatus: BranchStatus | null;
  addedAt: string;
  branches: BranchInfo[];
  onRemove: (repoId: string) => void;
  onBranchesUpdated: () => void;
}

export function RepoCard({
  repoId,
  repoUrl,
  indexStatus,
  addedAt,
  branches,
  onRemove,
  onBranchesUpdated,
}: RepoCardProps) {
  const [branchesOpen, setBranchesOpen] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [branchInput, setBranchInput] = useState("");
  const [branchError, setBranchError] = useState<string | null>(null);
  const [isSubmittingBranches, setIsSubmittingBranches] = useState(false);

  async function handleAddBranches(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const parsedBranches = parseBranchInput(branchInput);
    if (parsedBranches.length === 0) {
      setBranchError("Enter at least one branch name.");
      return;
    }

    setIsSubmittingBranches(true);
    setBranchError(null);

    try {
      const body: AddRepoBranchesRequest = { branches: parsedBranches };
      await apiFetch(`/v1/user/repos/${encodeURIComponent(repoId)}/branches`, {
        method: "POST",
        body,
      });
      setBranchInput("");
      setDialogOpen(false);
      onBranchesUpdated();
    } catch (err) {
      setBranchError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setIsSubmittingBranches(false);
    }
  }

  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex items-start justify-between gap-3">
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

        <div className="mt-3 flex items-center justify-between gap-3">
          <span className="text-xs text-muted-foreground">Added {new Date(addedAt).toLocaleDateString()}</span>
          <div className="flex items-center gap-1">
            <Dialog
              open={dialogOpen}
              onOpenChange={(open) => {
                setDialogOpen(open);
                if (!open) {
                  setBranchInput("");
                  setBranchError(null);
                }
              }}
            >
              <DialogTrigger asChild>
                <Button variant="ghost" size="sm">
                  <GitBranchPlus data-icon="inline-start" />
                  Add branches
                </Button>
              </DialogTrigger>
              <DialogContent>
                <DialogHeader>
                  <DialogTitle>Index More Branches</DialogTitle>
                  <DialogDescription>
                    Add branch names as a comma-separated list. Existing branches are skipped automatically.
                  </DialogDescription>
                </DialogHeader>
                <form onSubmit={handleAddBranches} className="flex flex-col gap-5">
                  <FieldGroup>
                    <Field data-invalid={branchError ? true : undefined}>
                      <FieldLabel htmlFor={`branches-${repoId}`}>Branches</FieldLabel>
                      <Input
                        id={`branches-${repoId}`}
                        type="text"
                        value={branchInput}
                        onChange={(e) => {
                          setBranchInput(e.target.value);
                          if (branchError) {
                            setBranchError(null);
                          }
                        }}
                        placeholder="feature/auth, release/next"
                        aria-invalid={branchError ? true : undefined}
                      />
                      <FieldDescription>
                        Indexed now: {branches.map((branch) => branch.branch_name).join(", ") || "none"}
                      </FieldDescription>
                      {branchError && <FieldError>{branchError}</FieldError>}
                    </Field>
                  </FieldGroup>
                  <DialogFooter>
                    <Button type="button" variant="outline" onClick={() => setDialogOpen(false)}>
                      Cancel
                    </Button>
                    <Button type="submit" disabled={isSubmittingBranches}>
                      {isSubmittingBranches ? "Adding..." : "Add Branches"}
                    </Button>
                  </DialogFooter>
                </form>
              </DialogContent>
            </Dialog>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onRemove(repoId)}
              className="text-destructive hover:text-destructive hover:bg-destructive/10"
            >
              Remove
            </Button>
          </div>
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
                Indexed branches: {branches.length}
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
