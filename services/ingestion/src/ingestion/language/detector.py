from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class LanguageDetector(ABC):
    """Abstract base for language detection strategies."""

    @abstractmethod
    def detect(self, file_path: str) -> str | None:
        """Detect the programming language for a given file path."""
        ...


EXTENSION_TO_LANGUAGE: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".jsx": "javascript",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".rb": "ruby",
    ".php": "php",
    ".cs": "csharp",
    ".swift": "swift",
    ".kt": "kotlin",
    ".scala": "scala",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".sql": "sql",
    ".html": "html",
    ".css": "css",
    ".scss": "scss",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".toml": "toml",
    ".xml": "xml",
    ".md": "markdown",
    ".r": "r",
    ".lua": "lua",
    ".dart": "dart",
    ".ex": "elixir",
    ".exs": "elixir",
    ".erl": "erlang",
    ".hs": "haskell",
    ".ml": "ocaml",
    ".clj": "clojure",
    ".vim": "vim",
    ".proto": "protobuf",
    ".tf": "terraform",
    ".dockerfile": "dockerfile",
}


class ExtensionLanguageDetector(LanguageDetector):
    """Detects programming language from file extension."""

    def detect(self, file_path: str) -> str | None:
        name = Path(file_path).name.lower()
        if name == "dockerfile":
            return "dockerfile"
        if name == "makefile":
            return "makefile"
        suffix = Path(file_path).suffix.lower()
        return EXTENSION_TO_LANGUAGE.get(suffix)
