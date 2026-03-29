import { Badge } from "@/components/ui/badge";

export function StatusBadge({ status }: { status: string | null }) {
  const s = status || "NOT_FOUND";

  if (s === "READY") {
    return <Badge variant="default">Ready</Badge>;
  }

  if (s === "PENDING" || s === "IN_PROGRESS") {
    return (
      <Badge variant="secondary">
        <span className="mr-1 animate-pulse">&#9679;</span>
        Indexing...
      </Badge>
    );
  }

  if (s === "FAILED") {
    return <Badge variant="destructive">Failed</Badge>;
  }

  if (s === "STALE") {
    return (
      <Badge variant="outline" className="text-orange-600 border-orange-300">
        Stale
      </Badge>
    );
  }

  return <Badge variant="outline">Not Indexed</Badge>;
}
