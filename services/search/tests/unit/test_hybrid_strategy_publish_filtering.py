from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from search.strategies.hybrid_strategy import HybridSearchStrategy


@contextmanager
def _connection_context():
    yield


@pytest.mark.unit
def test_list_indexed_branches_returns_branches_when_indexed_files_non_empty(monkeypatch):
    """Line 348: when IndexedFile returns branches, return them directly."""
    db_manager = SimpleNamespace(connection_context=_connection_context)
    strategy = HybridSearchStrategy(
        db_manager=db_manager,
        milvus=MagicMock(),
        embedder=MagicMock(),
    )

    indexed_file_query = MagicMock()
    indexed_file_query.where.return_value = indexed_file_query
    indexed_file_query.distinct.return_value = [
        SimpleNamespace(branch_name="main"),
        SimpleNamespace(branch_name="dev"),
    ]
    monkeypatch.setattr(
        "search.strategies.hybrid_strategy.IndexedFile.select",
        MagicMock(return_value=indexed_file_query),
    )

    branches = strategy._list_indexed_branches("repo-1")
    assert branches == ["dev", "main"]


@pytest.mark.unit
def test_list_indexed_branches_falls_back_to_chunks_when_indexed_files_empty(monkeypatch):
    """When IndexedFile has no results, fall back to querying Chunk table."""
    db_manager = SimpleNamespace(connection_context=_connection_context)
    strategy = HybridSearchStrategy(
        db_manager=db_manager,
        milvus=MagicMock(),
        embedder=MagicMock(),
    )

    # IndexedFile query returns empty set → no branches
    indexed_file_query = MagicMock()
    indexed_file_query.where.return_value = indexed_file_query
    indexed_file_query.distinct.return_value = []  # No rows
    monkeypatch.setattr(
        "search.strategies.hybrid_strategy.IndexedFile.select",
        MagicMock(return_value=indexed_file_query),
    )

    # Chunk query returns some branches
    chunk_row = SimpleNamespace(branch="feature-x")
    chunk_query = MagicMock()
    chunk_query.where.return_value = chunk_query
    chunk_query.distinct.return_value = [chunk_row]
    monkeypatch.setattr(
        "search.strategies.hybrid_strategy.Chunk.select",
        MagicMock(return_value=chunk_query),
    )

    branches = strategy._list_indexed_branches("repo-1")
    assert branches == ["feature-x"]


@pytest.mark.unit
class TestHybridStrategyPublishFiltering:
    def _make_strategy(self) -> HybridSearchStrategy:
        db_manager = SimpleNamespace(connection_context=_connection_context)
        milvus = MagicMock()
        embedder = MagicMock()
        return HybridSearchStrategy(
            db_manager=db_manager,
            milvus=milvus,
            embedder=embedder,
        )

    def test_filter_vector_results_empty(self):
        strategy = self._make_strategy()

        assert strategy._filter_vector_results([]) == []

    def test_filter_vector_results_respects_active_publish_map(self, monkeypatch):
        strategy = self._make_strategy()
        monkeypatch.setattr(
            strategy,
            "_get_active_publish_map",
            MagicMock(
                return_value={
                    ("repo-1", "main", "active.py"): "batch-123",
                    ("repo-1", "main", "hidden.py"): None,
                }
            ),
        )

        vector_results = [
            {
                "chunk_id": "legacy-keep",
                "repository_id": "repo-1",
                "branch": "main",
                "file_path": "legacy.py",
                "publish_id": "legacy",
                "score": 0.9,
            },
            {
                "chunk_id": "legacy-drop",
                "repository_id": "repo-1",
                "branch": "main",
                "file_path": "legacy.py",
                "publish_id": "batch-000",
                "score": 0.8,
            },
            {
                "chunk_id": "active-keep",
                "repository_id": "repo-1",
                "branch": "main",
                "file_path": "active.py",
                "publish_id": "batch-123",
                "score": 0.7,
            },
            {
                "chunk_id": "active-drop",
                "repository_id": "repo-1",
                "branch": "main",
                "file_path": "active.py",
                "publish_id": "legacy",
                "score": 0.6,
            },
            {
                "chunk_id": "hidden-drop",
                "repository_id": "repo-1",
                "branch": "main",
                "file_path": "hidden.py",
                "publish_id": "batch-999",
                "score": 0.5,
            },
        ]

        filtered = strategy._filter_vector_results(vector_results)

        assert [result["chunk_id"] for result in filtered] == [
            "legacy-keep",
            "active-keep",
        ]

    def test_filter_vector_results_defaults_missing_publish_id_to_legacy(self, monkeypatch):
        strategy = self._make_strategy()
        monkeypatch.setattr(
            strategy,
            "_get_active_publish_map",
            MagicMock(
                return_value={
                    ("repo-1", "main", "active.py"): "batch-123",
                }
            ),
        )

        vector_results = [
            {
                "chunk_id": "legacy-keep",
                "repository_id": "repo-1",
                "branch": "main",
                "file_path": "legacy.py",
                "score": 0.9,
            },
            {
                "chunk_id": "active-drop",
                "repository_id": "repo-1",
                "branch": "main",
                "file_path": "active.py",
                "score": 0.8,
            },
        ]

        filtered = strategy._filter_vector_results(vector_results)

        assert [result["chunk_id"] for result in filtered] == ["legacy-keep"]

    def test_get_active_publish_map_empty(self):
        strategy = self._make_strategy()

        assert strategy._get_active_publish_map([]) == {}

    def test_get_active_publish_map_returns_rows(self, monkeypatch):
        strategy = self._make_strategy()
        rows = [
            SimpleNamespace(
                repository_id="repo-1",
                branch_name="main",
                file_path="a.py",
                active_publish_id="batch-1",
            ),
            SimpleNamespace(
                repository_id="repo-1",
                branch_name="main",
                file_path="b.py",
                active_publish_id=None,
            ),
        ]
        select_query = MagicMock()
        select_query.where.return_value = rows
        monkeypatch.setattr(
            "search.strategies.hybrid_strategy.IndexedFile.select",
            MagicMock(return_value=select_query),
        )

        result = strategy._get_active_publish_map(
            [("repo-1", "main", "a.py"), ("repo-1", "main", "b.py")]
        )

        assert result == {
            ("repo-1", "main", "a.py"): "batch-1",
            ("repo-1", "main", "b.py"): None,
        }

    def test_get_active_publish_map_rows_with_tuples_method(self, monkeypatch):
        """Cover the hasattr(rows, 'tuples') branch where rows yields tuple objects."""
        strategy = self._make_strategy()
        tuple_rows = [
            ("repo-1", "main", "a.py", "batch-1"),
            ("repo-1", "main", "b.py", None),
        ]

        class _RowsWithTuples:
            def tuples(self):
                return tuple_rows

        select_query = MagicMock()
        select_query.where.return_value = _RowsWithTuples()
        monkeypatch.setattr(
            "search.strategies.hybrid_strategy.IndexedFile.select",
            MagicMock(return_value=select_query),
        )

        result = strategy._get_active_publish_map(
            [("repo-1", "main", "a.py"), ("repo-1", "main", "b.py")]
        )

        assert result == {
            ("repo-1", "main", "a.py"): "batch-1",
            ("repo-1", "main", "b.py"): None,
        }
