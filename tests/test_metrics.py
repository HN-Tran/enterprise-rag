"""Tests for evaluation metrics."""

from __future__ import annotations

import pytest

from app.evaluation.metrics import (
    compute_retrieval_metrics,
    compute_citation_metrics,
)


class TestRetrievalMetrics:
    """Tests for retrieval metrics computation."""

    def test_perfect_retrieval(self):
        """Test metrics when all retrieved docs are relevant."""
        retrieved = ["doc1", "doc2", "doc3"]
        relevant = {"doc1", "doc2", "doc3"}

        metrics = compute_retrieval_metrics(retrieved, relevant)

        assert metrics.precision_at_k[1] == 1.0
        assert metrics.precision_at_k[5] == 0.6  # 3/5
        assert metrics.recall_at_k[1] == pytest.approx(0.333, rel=0.01)
        assert metrics.recall_at_k[5] == 1.0
        assert metrics.mrr == 1.0
        assert metrics.hit_rate_at_k[1] == 1.0

    def test_no_relevant_found(self):
        """Test metrics when no relevant docs are retrieved."""
        retrieved = ["doc4", "doc5", "doc6"]
        relevant = {"doc1", "doc2", "doc3"}

        metrics = compute_retrieval_metrics(retrieved, relevant)

        assert metrics.precision_at_k[1] == 0.0
        assert metrics.recall_at_k[5] == 0.0
        assert metrics.mrr == 0.0
        assert metrics.hit_rate_at_k[5] == 0.0

    def test_partial_match(self):
        """Test metrics with partial match."""
        retrieved = ["doc1", "doc4", "doc2", "doc5", "doc6"]
        relevant = {"doc1", "doc2", "doc3"}

        metrics = compute_retrieval_metrics(retrieved, relevant)

        assert metrics.precision_at_k[1] == 1.0
        assert metrics.precision_at_k[5] == 0.4  # 2/5
        assert metrics.mrr == 1.0  # First relevant at position 1
        assert metrics.hit_rate_at_k[1] == 1.0

    def test_mrr_not_first(self):
        """Test MRR when relevant doc is not first."""
        retrieved = ["doc4", "doc5", "doc1", "doc6"]
        relevant = {"doc1"}

        metrics = compute_retrieval_metrics(retrieved, relevant)

        assert metrics.mrr == pytest.approx(0.333, rel=0.01)  # 1/3

    def test_empty_inputs(self):
        """Test with empty inputs."""
        metrics = compute_retrieval_metrics([], set())
        assert metrics.mrr == 0.0

        metrics = compute_retrieval_metrics(["doc1"], set())
        assert metrics.mrr == 0.0


class TestCitationMetrics:
    """Tests for citation metrics computation."""

    def test_perfect_citations(self):
        """Test when all sources are cited and all citations are valid."""
        answer = "Laut [1] gilt X. Gemäß [2] gilt Y. Siehe auch [3]."
        sources = [
            {"index": 1, "doc_id": "doc1", "confidence": 0.9},
            {"index": 2, "doc_id": "doc2", "confidence": 0.8},
            {"index": 3, "doc_id": "doc3", "confidence": 0.7},
        ]

        metrics = compute_citation_metrics(answer, sources)

        assert metrics.citation_precision == 1.0
        assert metrics.citation_recall == 1.0
        assert metrics.avg_confidence == pytest.approx(0.8, rel=0.01)

    def test_invalid_citations(self):
        """Test when citations reference non-existent sources."""
        answer = "Laut [1] gilt X. Gemäß [5] gilt Y."  # [5] doesn't exist
        sources = [
            {"index": 1, "doc_id": "doc1", "confidence": 0.9},
            {"index": 2, "doc_id": "doc2", "confidence": 0.8},
        ]

        metrics = compute_citation_metrics(answer, sources)

        assert metrics.citation_precision == 0.5  # 1 valid out of 2 cited
        assert metrics.citation_recall == 0.5     # 1 of 2 sources cited

    def test_unused_sources(self):
        """Test when some sources are not cited."""
        answer = "Laut [1] gilt X."
        sources = [
            {"index": 1, "doc_id": "doc1", "confidence": 0.9},
            {"index": 2, "doc_id": "doc2", "confidence": 0.8},
            {"index": 3, "doc_id": "doc3", "confidence": 0.7},
        ]

        metrics = compute_citation_metrics(answer, sources)

        assert metrics.citation_precision == 1.0
        assert metrics.citation_recall == pytest.approx(0.333, rel=0.01)

    def test_source_diversity(self):
        """Test source diversity calculation."""
        answer = "Laut [1] und [2]."
        sources = [
            {"index": 1, "doc_id": "doc1", "confidence": 0.9},
            {"index": 2, "doc_id": "doc1", "confidence": 0.8},  # Same doc
        ]

        metrics = compute_citation_metrics(answer, sources)

        assert metrics.source_diversity == 0.5  # 1 unique doc / 2 sources

    def test_empty_sources(self):
        """Test with empty sources."""
        metrics = compute_citation_metrics("Some answer", [])

        assert metrics.citation_precision == 0.0
        assert metrics.citation_recall == 0.0
        assert metrics.avg_confidence == 0.0

    def test_citation_coverage(self):
        """Test citation coverage across sentences."""
        answer = "Punkt eins [1]. Punkt zwei. Punkt drei [2]."
        sources = [
            {"index": 1, "doc_id": "doc1", "confidence": 0.9},
            {"index": 2, "doc_id": "doc2", "confidence": 0.8},
        ]

        metrics = compute_citation_metrics(answer, sources)

        # 2 sentences with citations out of 3
        assert metrics.citation_coverage == pytest.approx(0.666, rel=0.01)
