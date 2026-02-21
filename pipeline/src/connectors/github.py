"""GitHub API connector for repository metadata and source archives."""

from __future__ import annotations

from dataclasses import dataclass
import re
from urllib.request import Request, urlopen

from github import Github
from github.GithubException import GithubException

_DEFAULT_ACCEPT_HEADER = "application/vnd.github+json"
_GITHUB_HTTP_RE = re.compile(
    r"^https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$",
    re.IGNORECASE,
)
_GITHUB_SSH_RE = re.compile(
    r"^git@github\.com:(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?$",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class GitHubTarballResult:
    """Fetched GitHub source archive and optional resolved commit SHA."""

    snapshot_sha: str | None
    archive_bytes: bytes


class GitHubConnector:
    """Read-only GitHub connector used by runtime ingest activities."""

    def __init__(
        self,
        *,
        request_timeout_commit: tuple[int, int] = (5, 20),
        request_timeout_tarball: tuple[int, int] = (10, 60),
    ) -> None:
        self.request_timeout_commit = request_timeout_commit
        self.request_timeout_tarball = request_timeout_tarball

    def parse_owner_repo(self, repo_url: str) -> tuple[str, str] | None:
        """Extract owner/repo from GitHub HTTPS or SSH references."""
        match = _GITHUB_HTTP_RE.match(repo_url) or _GITHUB_SSH_RE.match(repo_url)
        if match is None:
            return None
        return match.group("owner"), match.group("repo")

    def fetch_tarball(
        self,
        *,
        owner: str,
        repo: str,
        ref: str,
        token: str | None = None,
    ) -> GitHubTarballResult:
        """Fetch repository tarball for a ref plus optional resolved commit SHA."""
        client = Github(
            login_or_token=token,
            timeout=self.request_timeout_commit[1],
            per_page=100,
        )
        try:
            repository = client.get_repo(f"{owner}/{repo}")

            snapshot_sha = None
            try:
                snapshot_sha = repository.get_commit(sha=ref).sha
            except GithubException:
                snapshot_sha = None

            tarball_url = repository.get_archive_link("tarball", ref=ref)
            archive_bytes = self._download_archive_bytes(
                tarball_url=tarball_url,
                token=token,
            )
            return GitHubTarballResult(
                snapshot_sha=snapshot_sha,
                archive_bytes=archive_bytes,
            )
        finally:
            if hasattr(client, "close"):
                client.close()

    def _download_archive_bytes(self, *, tarball_url: str, token: str | None) -> bytes:
        """Download tarball bytes from an archive URL."""
        headers = {"Accept": _DEFAULT_ACCEPT_HEADER}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        request = Request(tarball_url, headers=headers)
        timeout_seconds = self.request_timeout_tarball[1]
        with urlopen(request, timeout=timeout_seconds) as response:
            return response.read()
