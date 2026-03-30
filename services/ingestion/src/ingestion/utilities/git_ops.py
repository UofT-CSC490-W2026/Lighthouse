from __future__ import annotations

import logging
import os
from pathlib import Path
import subprocess

from git import Repo

from ..language.detector import CODE_EXTENSIONS

logger = logging.getLogger(__name__)

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
        self.git_global_config_path = self.base_dir / ".ingestion-gitconfig"
        if not os.environ.get("GIT_CONFIG_GLOBAL"):
            os.environ["GIT_CONFIG_GLOBAL"] = str(self.git_global_config_path)

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
        self._ensure_safe_directory(repo_path)

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
            self._ensure_safe_directory(repo_path)

        return repo_path

    def get_latest_commit(self, repo_path: Path, branch: str) -> str:
        """Return the HEAD commit SHA for the branch."""
        self._ensure_safe_directory(repo_path)
        repo = Repo(repo_path)
        return str(repo.head.commit.hexsha)

    def list_files(
        self, repo_path: Path, extensions: set[str] | None = None
    ) -> list[Path]:
        """List all trackable code files, optionally filtered by extension."""
        allowed = extensions or CODE_EXTENSIONS
        files: list[Path] = []
        allow_extensionless = {"dockerfile", "makefile"}

        for root, dirs, filenames in os.walk(repo_path):
            # Skip git metadata directory during traversal.
            dirs[:] = [d for d in dirs if d != ".git"]
            root_path = Path(root)

            for filename in filenames:
                if filename in SKIP_PATTERNS:
                    continue

                suffix = os.path.splitext(filename)[1].lower()
                lower_name = filename.lower()
                if suffix not in allowed and lower_name not in allow_extensionless:
                    continue

                path = root_path / filename
                try:
                    if path.stat().st_size > MAX_FILE_SIZE_BYTES:
                        continue
                except OSError:
                    continue
                files.append(path)

        return files

    def get_changed_files(
        self, repo_path: Path, old_commit: str, new_commit: str
    ) -> list[Path]:
        """Return files changed between two commits."""
        self._ensure_safe_directory(repo_path)
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

    def _ensure_safe_directory(self, repo_path: Path) -> None:
        """Allow git access to synthetic repos mounted with differing ownership."""
        candidates = [str(repo_path)]
        dot_git = repo_path / ".git"
        if dot_git.exists():
            candidates.append(str(dot_git))
        for candidate in candidates:
            result = subprocess.run(
                ["git", "config", "--global", "--add", "safe.directory", candidate],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                logger.warning(
                    "Failed to set git safe.directory for %s: %s",
                    candidate,
                    (result.stderr or result.stdout).strip() or "unknown error",
                )
