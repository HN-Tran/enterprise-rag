"""Evaluation metrics for retrieval and citation quality."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RetrievalMetrics:
    """Metrics for retrieval quality."""
    precision_at_k: dict[int, float] = field(default_factory=dict)  # P@1, P@5, P@10
    recall_at_k: dict[int, float] = field(default_factory=dict)     # R@1, R@5, R@10
    mrr: float = 0.0                                                 # Mean Reciprocal Rank
    ndcg_at_k: dict[int, float] = field(default_factory=dict)       # NDCG@5, NDCG@10
    hit_rate_at_k: dict[int, float] = field(default_factory=dict)   # Hit@1, Hit@5, Hit@10

    def to_dict(self) -> dict[str, Any]:
        return {
            "precision": self.precision_at_k,
            "recall": self.recall_at_k,
            "mrr": self.mrr,
            "ndcg": self.ndcg_at_k,
            "hit_rate": self.hit_rate_at_k,
        }


@dataclass
class CitationMetrics:
    """Metrics for citation accuracy."""
    citation_precision: float = 0.0    # Citations that are actually in sources
    citation_recall: float = 0.0       # Sources that are cited in answer
    citation_coverage: float = 0.0     # % of claims with citations
    avg_confidence: float = 0.0        # Average source confidence
    source_diversity: float = 0.0      # Unique docs / total citations

    def to_dict(self) -> dict[str, Any]:
        return {
            "citation_precision": self.citation_precision,
            "citation_recall": self.citation_recall,
            "citation_coverage": self.citation_coverage,
            "avg_confidence": self.avg_confidence,
            "source_diversity": self.source_diversity,
        }


def compute_retrieval_metrics(
    retrieved_doc_ids: list[str],
    relevant_doc_ids: set[str],
    k_values: list[int] | None = None,
) -> RetrievalMetrics:
    """
    Compute retrieval metrics given retrieved and relevant document IDs.

    Args:
        retrieved_doc_ids: Ordered list of retrieved document IDs
        relevant_doc_ids: Set of ground-truth relevant document IDs
        k_values: List of k values for P@k, R@k (default: [1, 5, 10])

    Returns:
        RetrievalMetrics with computed values
    """
    if k_values is None:
        k_values = [1, 5, 10]

    metrics = RetrievalMetrics()

    if not retrieved_doc_ids or not relevant_doc_ids:
        return metrics

    # Precision@k and Recall@k
    for k in k_values:
        top_k = retrieved_doc_ids[:k]
        relevant_in_top_k = sum(1 for doc in top_k if doc in relevant_doc_ids)

        metrics.precision_at_k[k] = relevant_in_top_k / k if k > 0 else 0.0
        metrics.recall_at_k[k] = relevant_in_top_k / len(relevant_doc_ids)
        metrics.hit_rate_at_k[k] = 1.0 if relevant_in_top_k > 0 else 0.0

    # MRR (Mean Reciprocal Rank)
    for i, doc_id in enumerate(retrieved_doc_ids):
        if doc_id in relevant_doc_ids:
            metrics.mrr = 1.0 / (i + 1)
            break

    # NDCG@k
    for k in k_values:
        metrics.ndcg_at_k[k] = _compute_ndcg(retrieved_doc_ids[:k], relevant_doc_ids)

    return metrics


def _compute_ndcg(retrieved: list[str], relevant: set[str]) -> float:
    """Compute NDCG (Normalized Discounted Cumulative Gain)."""
    import math

    if not retrieved or not relevant:
        return 0.0

    # DCG
    dcg = 0.0
    for i, doc_id in enumerate(retrieved):
        if doc_id in relevant:
            dcg += 1.0 / math.log2(i + 2)  # i+2 because log2(1) = 0

    # Ideal DCG (all relevant docs at top)
    ideal_dcg = sum(1.0 / math.log2(i + 2) for i in range(min(len(relevant), len(retrieved))))

    return dcg / ideal_dcg if ideal_dcg > 0 else 0.0


def compute_citation_metrics(
    answer_text: str,
    sources: list[dict[str, Any]],
) -> CitationMetrics:
    """
    Compute citation metrics from answer and sources.

    Args:
        answer_text: The answer text with [1], [2] citations
        sources: List of source dictionaries with 'index' and 'confidence'

    Returns:
        CitationMetrics with computed values
    """
    metrics = CitationMetrics()

    if not sources:
        return metrics

    # Extract citation indices from answer
    citation_pattern = r'\[(\d+)\]'
    cited_indices = set(int(m) for m in re.findall(citation_pattern, answer_text))
    source_indices = set(s.get("index", i + 1) for i, s in enumerate(sources))

    # Citation precision: cited indices that exist in sources
    if cited_indices:
        valid_citations = cited_indices & source_indices
        metrics.citation_precision = len(valid_citations) / len(cited_indices)

    # Citation recall: sources that are cited
    if source_indices:
        metrics.citation_recall = len(cited_indices & source_indices) / len(source_indices)

    # Citation coverage: estimate based on sentences with citations
    sentences = re.split(r'[.!?]', answer_text)
    sentences_with_citations = sum(1 for s in sentences if re.search(citation_pattern, s))
    total_sentences = len([s for s in sentences if s.strip()])
    if total_sentences > 0:
        metrics.citation_coverage = sentences_with_citations / total_sentences

    # Average confidence
    confidences = [s.get("confidence", 0.0) for s in sources]
    if confidences:
        metrics.avg_confidence = sum(confidences) / len(confidences)

    # Source diversity: unique docs / total sources
    doc_ids = [s.get("doc_id") for s in sources]
    unique_docs = len(set(d for d in doc_ids if d))
    if doc_ids:
        metrics.source_diversity = unique_docs / len(doc_ids)

    return metrics
