const STATUS_STYLES: Record<string, { bg: string; text: string; label: string }> = {
  READY: { bg: "bg-green-100", text: "text-green-800", label: "Ready" },
  PENDING: { bg: "bg-yellow-100", text: "text-yellow-800", label: "Indexing..." },
  IN_PROGRESS: { bg: "bg-yellow-100", text: "text-yellow-800", label: "Indexing..." },
  FAILED: { bg: "bg-red-100", text: "text-red-800", label: "Failed" },
  STALE: { bg: "bg-orange-100", text: "text-orange-800", label: "Stale" },
  NOT_FOUND: { bg: "bg-gray-100", text: "text-gray-600", label: "Not Indexed" },
};

export function StatusBadge({ status }: { status: string | null }) {
  const style = STATUS_STYLES[status || "NOT_FOUND"] || STATUS_STYLES.NOT_FOUND;
  return (
    <span
      className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${style.bg} ${style.text}`}
    >
      {(status === "PENDING" || status === "IN_PROGRESS") && (
        <span className="mr-1 animate-pulse">&#9679;</span>
      )}
      {style.label}
    </span>
  );
}
