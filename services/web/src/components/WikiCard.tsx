import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/esm/styles/prism";
import type { WikiContextSnippet } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

interface WikiCardProps {
  snippet: WikiContextSnippet;
}

/** Extract fenced code blocks and intersperse with plain-text sections. */
function parseContent(content: string) {
  const parts: { type: "text" | "code"; lang?: string; value: string }[] = [];
  const codeBlockRegex = /```(\w*)\n([\s\S]*?)```/g;
  let lastIndex = 0;
  let match;

  while ((match = codeBlockRegex.exec(content)) !== null) {
    if (match.index > lastIndex) {
      parts.push({ type: "text", value: content.slice(lastIndex, match.index) });
    }
    parts.push({ type: "code", lang: match[1] || "text", value: match[2].trimEnd() });
    lastIndex = match.index + match[0].length;
  }

  if (lastIndex < content.length) {
    parts.push({ type: "text", value: content.slice(lastIndex) });
  }

  return parts;
}

export function WikiCard({ snippet }: WikiCardProps) {
  const title = snippet.page_title ?? "Wiki";
  const breadcrumb = snippet.section_path ? snippet.section_path.replace(/-/g, " ").replace(/\//g, " / ") : null;

  const parts = parseContent(snippet.content);
  console.log("parts", parts);

  return (
    <Card className="overflow-hidden gap-0 py-0">
      <div className="flex flex-wrap items-center gap-2 border-b border-border bg-muted px-4 py-2.5">
        <span className="text-xs font-medium text-foreground truncate flex-1 min-w-0">{title}</span>
        <div className="flex items-center gap-1.5 shrink-0">
          <Badge variant="outline" className="text-xs">
            wiki
          </Badge>
          {breadcrumb && <span className="text-xs text-muted-foreground">{breadcrumb}</span>}
          {snippet.reason && (
            <Badge variant="default" className="text-xs">
              {snippet.reason}
            </Badge>
          )}
        </div>
      </div>
      <CardContent className="p-4 space-y-3">
        {parts.map((part, i) =>
          part.type === "code" ? (
            <SyntaxHighlighter
              key={i}
              language={part.lang}
              style={oneDark}
              customStyle={{
                margin: 0,
                borderRadius: "0.25rem",
                fontSize: "0.7rem",
                lineHeight: "1.6",
              }}
            >
              {part.value}
            </SyntaxHighlighter>
          ) : (
            <div key={i} className="text-xs text-foreground whitespace-pre-wrap leading-relaxed">
              {part.value.trim()}
            </div>
          ),
        )}
      </CardContent>
    </Card>
  );
}
