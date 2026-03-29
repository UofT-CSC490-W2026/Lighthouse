import { Badge } from "@/components/ui/badge";
import type { BranchStatus } from "@/lib/api";

export function StatusBadge({ status }: { status: BranchStatus | null }) {
  if (status === "INDEXED") {
    return <Badge variant="default">Indexed</Badge>;
  }

  if (status === "INDEXING" || status === "PENDING") {
    return (
      <Badge variant="secondary">
        <span className="mr-1 animate-pulse">&#9679;</span>
        Indexing...
      </Badge>
    );
  }

  if (status === "FAILED") {
    return <Badge variant="destructive">Failed</Badge>;
  }

  return <Badge variant="outline">Not Indexed</Badge>;
}
