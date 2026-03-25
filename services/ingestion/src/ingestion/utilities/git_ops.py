from __future__ import annotations

import logging
from pathlib import Path

from git import Repo

logger = logging.getLogger(__name__)

# File extensions we consider indexable code
CODE_EXTENSIONS: set[str] = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".rs", ".c", ".cpp",
    ".h", ".hpp", ".rb", ".php", ".cs", ".swift", ".kt", ".scala", ".sh",
    ".bash", ".zsh", ".sql", ".html", ".css", ".scss", ".yaml", ".yml",
    ".json", ".toml", ".xml", ".md", ".r", ".lua", ".dart", ".ex", ".exs",
    ".erl", ".hs", ".ml", ".clj", ".vim", ".proto", ".tf",
}

# Files to skip regardless of extension
SKIP_PATTERNS: set[str] = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock",
    "Pipfile.lock", "uv.lock", "composer.lock", "Gemfile.lock",
    "Cargo.lock", "go.sum",
}

MAX_FILE_SIZE_BYTES = 1_000_000  # 1 MB


class GitOperations:
    """Handle git clone/fetch operations for repository indexing."""

    def __init__(self, base_dir: str, github_token: str | None = None) -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.github_token = github_token

    def _authenticated_url(self, repo_url: str) -> str:
        """Inject GitHub token into HTTPS URL for private repo access."""
        if self.github_token and repo_url.startswith("https://"):
            return repo_url.replace(
                "https://", f"https://x-access-token:{self.github_token}@"
            )
        return repo_url

    def clone_or_fetch(
        self, repo_url: str, repo_dir_name: str, branch: str = "main"
    ) -> Path:
        """Clone if not exists, else fetch and checkout branch. Returns repo path."""
        repo_path = self.base_dir / repo_dir_name

        auth_url = self._authenticated_url(repo_url)

        if repo_path.exists() and (repo_path / ".git").exists():
            logger.info("Fetching updates for %s branch %s", repo_dir_name, branch)
            repo = Repo(repo_path)
            # Update remote URL in case token changed
            repo.remotes.origin.set_url(auth_url)
            repo.remotes.origin.fetch()
            repo.git.checkout(branch)
            repo.git.pull("origin", branch)
        else:
            logger.info("Cloning %s branch %s", repo_dir_name, branch)
            repo = Repo.clone_from(
                auth_url,
                repo_path,
                branch=branch,
                depth=1,
            )

        return repo_path

    def get_latest_commit(self, repo_path: Path, branch: str) -> str:
        """Return the HEAD commit SHA for the branch."""
        repo = Repo(repo_path)
        return str(repo.head.commit.hexsha)

    def list_files(
        self, repo_path: Path, extensions: set[str] | None = None
    ) -> list[Path]:
        """List all trackable code files, optionally filtered by extension."""
        allowed = extensions or CODE_EXTENSIONS
        files: list[Path] = []

        for path in repo_path.rglob("*"):
            if not path.is_file():
                continue
            if ".git" in path.parts:
                continue
            if path.name in SKIP_PATTERNS:
                continue
            if path.suffix.lower() not in allowed:
                # Also check for extensionless files like Dockerfile, Makefile
                if path.name.lower() not in ("dockerfile", "makefile"):
                    continue
            if path.stat().st_size > MAX_FILE_SIZE_BYTES:
                continue
            files.append(path)

        return files

    def get_changed_files(
        self, repo_path: Path, old_commit: str, new_commit: str
    ) -> list[Path]:
        """Return files changed between two commits."""
        repo = Repo(repo_path)
        diff = repo.git.diff("--name-only", old_commit, new_commit)
        if not diff.strip():
            return []

        changed: list[Path] = []
        for name in diff.strip().split("\n"):
            full = repo_path / name
            if full.exists() and full.is_file():
                changed.append(full)
        return changed
