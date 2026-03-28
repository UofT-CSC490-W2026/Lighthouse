from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ingestion.utilities.git_ops import GitOperations


@pytest.mark.unit
class TestGitOperations:
    """Tests for GitOperations."""

    def test_authenticated_url_with_token(self, tmp_path: Path) -> None:
        ops = GitOperations(str(tmp_path), github_token="tok")
        result = ops._authenticated_url("https://github.com/o/r")
        assert result == "https://x-access-token:tok@github.com/o/r"

    def test_authenticated_url_without_token(self, tmp_path: Path) -> None:
        ops = GitOperations(str(tmp_path))
        url = "https://github.com/o/r"
        assert ops._authenticated_url(url) == url

    def test_authenticated_url_non_https(self, tmp_path: Path) -> None:
        ops = GitOperations(str(tmp_path), github_token="tok")
        url = "git@github.com:o/r.git"
        assert ops._authenticated_url(url) == url

    @patch("ingestion.utilities.git_ops.Repo")
    def test_clone_new_repo(self, mock_repo_cls: MagicMock, tmp_path: Path) -> None:
        ops = GitOperations(str(tmp_path), github_token="tok")
        repo_url = "https://github.com/o/r"
        auth_url = "https://x-access-token:tok@github.com/o/r"

        result = ops.clone_or_fetch(repo_url, "my-repo", branch="main")

        mock_repo_cls.clone_from.assert_called_once_with(
            auth_url,
            tmp_path / "my-repo",
            branch="main",
            depth=1,
        )
        assert result == tmp_path / "my-repo"

    @patch("ingestion.utilities.git_ops.Repo")
    def test_fetch_existing_repo(self, mock_repo_cls: MagicMock, tmp_path: Path) -> None:
        repo_dir = tmp_path / "my-repo"
        repo_dir.mkdir()
        (repo_dir / ".git").mkdir()

        mock_repo = MagicMock()
        mock_repo_cls.return_value = mock_repo

        ops = GitOperations(str(tmp_path), github_token="tok")
        result = ops.clone_or_fetch("https://github.com/o/r", "my-repo", branch="dev")

        mock_repo_cls.assert_called_once_with(repo_dir)
        mock_repo.remotes.origin.fetch.assert_called_once()
        mock_repo.git.checkout.assert_called_once_with("dev")
        mock_repo.git.pull.assert_called_once_with("origin", "dev")
        assert result == repo_dir

    def test_list_files_filters_extensions(self, tmp_path: Path) -> None:
        ops = GitOperations(str(tmp_path))
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "main.py").write_text("print('hi')")
        (repo / "data.xyz").write_text("unknown")

        result = ops.list_files(repo)
        names = [p.name for p in result]
        assert "main.py" in names
        assert "data.xyz" not in names

    def test_list_files_skips_lock_files(self, tmp_path: Path) -> None:
        ops = GitOperations(str(tmp_path))
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "package-lock.json").write_text("{}")

        result = ops.list_files(repo)
        names = [p.name for p in result]
        assert "package-lock.json" not in names

    def test_list_files_skips_file_on_oserror(self, tmp_path: Path) -> None:
        ops = GitOperations(str(tmp_path))
        repo = tmp_path / "repo"
        repo.mkdir()
        py_file = repo / "ghost.py"
        py_file.write_text("print('hi')")

        original_stat = Path.stat

        def patched_stat(self: Path, **kwargs):
            if self.name == "ghost.py":
                raise OSError("stat failed")
            return original_stat(self, **kwargs)

        with patch.object(Path, "stat", patched_stat):
            result = ops.list_files(repo)

        assert "ghost.py" not in [p.name for p in result]

    def test_list_files_skips_large_files(self, tmp_path: Path) -> None:
        ops = GitOperations(str(tmp_path))
        repo = tmp_path / "repo"
        repo.mkdir()
        large_file = repo / "big.py"
        large_file.write_text("x" * 1_100_000)

        result = ops.list_files(repo)
        names = [p.name for p in result]
        assert "big.py" not in names

    def test_list_files_skips_dot_git(self, tmp_path: Path) -> None:
        ops = GitOperations(str(tmp_path))
        repo = tmp_path / "repo"
        repo.mkdir()
        git_dir = repo / ".git"
        git_dir.mkdir()
        (git_dir / "config").write_text("[core]")

        result = ops.list_files(repo)
        names = [p.name for p in result]
        assert "config" not in names

    def test_list_files_includes_dockerfile(self, tmp_path: Path) -> None:
        ops = GitOperations(str(tmp_path))
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "Dockerfile").write_text("FROM python:3.12")

        result = ops.list_files(repo)
        names = [p.name for p in result]
        assert "Dockerfile" in names

    @patch("ingestion.utilities.git_ops.Repo")
    def test_get_latest_commit(self, mock_repo_cls: MagicMock, tmp_path: Path) -> None:
        mock_repo = MagicMock()
        mock_repo.head.commit.hexsha = "abc123def456"
        mock_repo_cls.return_value = mock_repo

        ops = GitOperations(str(tmp_path))
        result = ops.get_latest_commit(tmp_path / "repo", "main")
        assert result == "abc123def456"

    @patch("ingestion.utilities.git_ops.Repo")
    def test_get_changed_files(self, mock_repo_cls: MagicMock, tmp_path: Path) -> None:
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        (repo_dir / "changed.py").write_text("new content")
        # deleted.py does not exist on disk

        mock_repo = MagicMock()
        mock_repo.git.diff.return_value = "changed.py\ndeleted.py"
        mock_repo_cls.return_value = mock_repo

        ops = GitOperations(str(tmp_path))
        result = ops.get_changed_files(repo_dir, "aaa", "bbb")

        mock_repo.git.diff.assert_called_once_with("--name-only", "aaa", "bbb")
        assert len(result) == 1
        assert result[0] == repo_dir / "changed.py"

    @patch("ingestion.utilities.git_ops.Repo")
    def test_get_changed_files_empty(self, mock_repo_cls: MagicMock, tmp_path: Path) -> None:
        mock_repo = MagicMock()
        mock_repo.git.diff.return_value = ""
        mock_repo_cls.return_value = mock_repo

        ops = GitOperations(str(tmp_path))
        result = ops.get_changed_files(tmp_path / "repo", "aaa", "bbb")
        assert result == []
