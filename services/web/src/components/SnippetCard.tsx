import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/esm/styles/prism";
import type { CodeContextSnippet } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

interface SnippetCardProps {
  snippet: CodeContextSnippet;
  branch: string;
}

function getLanguage(filePath: string): string {
  const ext = filePath.split(".").pop()?.toLowerCase();
  const map: Record<string, string> = {
    ts: "typescript",
    tsx: "tsx",
    js: "javascript",
    jsx: "jsx",
    py: "python",
    rs: "rust",
    go: "go",
    java: "java",
    css: "css",
    html: "html",
    json: "json",
    md: "markdown",
    sh: "bash",
    yaml: "yaml",
    yml: "yaml",
    toml: "toml",
    rb: "ruby",
    cpp: "cpp",
    c: "c",
    cs: "csharp",
    php: "php",
    swift: "swift",
    kt: "kotlin",
  };
  return map[ext ?? ""] ?? "text";
}

export function SnippetCard({ snippet, branch }: SnippetCardProps) {
  return (
    <Card className="overflow-hidden">
      <div className="flex flex-wrap items-center gap-2 border-b border-border bg-muted px-4 py-2.5">
        <span className="font-mono text-xs font-medium text-foreground truncate flex-1 min-w-0">
          {snippet.file_path}
        </span>
        <div className="flex items-center gap-1.5 shrink-0">
          <Badge variant="outline" className="text-xs font-mono">
            {branch}
          </Badge>
          {(snippet.start_line != null || snippet.end_line != null) && (
            <span className="text-xs text-muted-foreground">
              L{snippet.start_line ?? "?"}&ndash;{snippet.end_line ?? "?"}
            </span>
          )}
          {snippet.reason && (
            <Badge variant="default" className="text-xs">
              {snippet.reason}
            </Badge>
          )}
        </div>
      </div>
      <CardContent className="p-0">
        <SyntaxHighlighter
          language={getLanguage(snippet.file_path)}
          style={oneDark}
          showLineNumbers={true}
          startingLineNumber={snippet.start_line ?? 1}
          customStyle={{
            margin: 0,
            borderRadius: 0,
            fontSize: "0.7rem",
            lineHeight: "1.6",
          }}
          lineNumberStyle={{
            minWidth: "2.5em",
            paddingRight: "1em",
            color: "oklch(0.556 0 0)",
            userSelect: "none",
          }}
        >
          {snippet.content}
        </SyntaxHighlighter>
      </CardContent>
    </Card>
  );
}
