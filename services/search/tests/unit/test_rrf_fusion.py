import pytest

from search.strategies.hybrid_strategy import HybridSearchStrategy


@pytest.mark.unit
class TestRRFFusion:
    """Tests for HybridSearchStrategy._rrf_fusion static method."""

    def test_empty_both(self):
        result = HybridSearchStrategy._rrf_fusion([], [])
        assert result == []

    def test_vector_only(self):
        vector = [
            {"chunk_id": "a", "score": 0.9},
            {"chunk_id": "b", "score": 0.8},
        ]
        result = HybridSearchStrategy._rrf_fusion(vector, [])
        assert len(result) == 2
        assert result[0]["chunk_id"] == "a"
        assert result[0]["score"] == pytest.approx(1.0 / (60 + 0 + 1))
        assert result[1]["chunk_id"] == "b"
        assert result[1]["score"] == pytest.approx(1.0 / (60 + 1 + 1))

    def test_keyword_only(self):
        keyword = [
            {"chunk_id": "x", "score": 5.0},
            {"chunk_id": "y", "score": 3.0},
        ]
        result = HybridSearchStrategy._rrf_fusion([], keyword)
        assert len(result) == 2
        assert result[0]["chunk_id"] == "x"
        assert result[0]["score"] == pytest.approx(1.0 / (60 + 0 + 1))
        assert result[1]["chunk_id"] == "y"
        assert result[1]["score"] == pytest.approx(1.0 / (60 + 1 + 1))

    def test_both_sources_overlap(self):
        vector = [{"chunk_id": "shared", "score": 0.9}]
        keyword = [{"chunk_id": "shared", "score": 5.0}]
        result = HybridSearchStrategy._rrf_fusion(vector, keyword)
        assert len(result) == 1
        expected = 1.0 / (60 + 0 + 1) + 1.0 / (60 + 0 + 1)
        assert result[0]["score"] == pytest.approx(expected)
        assert result[0]["chunk_id"] == "shared"

    def test_disjoint_sources(self):
        vector = [{"chunk_id": "v1", "score": 0.9}]
        keyword = [{"chunk_id": "k1", "score": 5.0}]
        result = HybridSearchStrategy._rrf_fusion(vector, keyword)
        ids = {r["chunk_id"] for r in result}
        assert ids == {"v1", "k1"}
        assert len(result) == 2

    def test_ordering(self):
        """Overlapping chunk should rank higher than non-overlapping ones."""
        vector = [
            {"chunk_id": "both", "score": 0.9},
            {"chunk_id": "vec_only", "score": 0.8},
        ]
        keyword = [
            {"chunk_id": "both", "score": 5.0},
            {"chunk_id": "kw_only", "score": 3.0},
        ]
        result = HybridSearchStrategy._rrf_fusion(vector, keyword)
        assert result[0]["chunk_id"] == "both"
        # Verify descending order
        scores = [r["score"] for r in result]
        assert scores == sorted(scores, reverse=True)

    def test_k_parameter(self):
        vector = [{"chunk_id": "a", "score": 0.9}]
        keyword = []

        result_k10 = HybridSearchStrategy._rrf_fusion(vector, keyword, k=10)
        result_k100 = HybridSearchStrategy._rrf_fusion(vector, keyword, k=100)

        assert result_k10[0]["score"] == pytest.approx(1.0 / (10 + 0 + 1))
        assert result_k100[0]["score"] == pytest.approx(1.0 / (100 + 0 + 1))
        # Smaller k produces higher score for rank-0 item
        assert result_k10[0]["score"] > result_k100[0]["score"]

    def test_preserves_extra_data(self):
        vector = [{"chunk_id": "a", "score": 0.9, "file_path": "foo.py"}]
        keyword = []
        result = HybridSearchStrategy._rrf_fusion(vector, keyword)
        assert result[0]["file_path"] == "foo.py"
        assert result[0]["chunk_id"] == "a"
