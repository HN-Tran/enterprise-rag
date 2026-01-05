"""Evaluation harness for running RAG evaluations."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from enterprise_rag.evaluation.metrics import (
    RetrievalMetrics,
    CitationMetrics,
    compute_retrieval_metrics,
    compute_citation_metrics,
)


@dataclass
class TestCase:
    """A single evaluation test case."""
    query: str
    relevant_doc_ids: list[str]             # Ground truth relevant documents
    expected_answer_contains: list[str] = field(default_factory=list)  # Keywords expected in answer
    category: str = "general"


@dataclass
class TestResult:
    """Result for a single test case."""
    query: str
    retrieval_metrics: RetrievalMetrics
    citation_metrics: CitationMetrics
    answer: str
    confidence: str
    latency_ms: float
    passed: bool
    error: str | None = None


@dataclass
class EvaluationResult:
    """Aggregated evaluation results."""
    timestamp: str
    total_cases: int
    passed_cases: int
    failed_cases: int
    avg_retrieval_metrics: dict[str, Any]
    avg_citation_metrics: dict[str, Any]
    avg_latency_ms: float
    results_by_category: dict[str, dict[str, Any]]
    individual_results: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def save(self, path: str | Path) -> None:
        """Save results to JSON file."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)

    def summary(self) -> str:
        """Return human-readable summary."""
        lines = [
            f"Evaluation Results ({self.timestamp})",
            "=" * 50,
            f"Total: {self.total_cases} | Passed: {self.passed_cases} | Failed: {self.failed_cases}",
            f"Pass Rate: {self.passed_cases / self.total_cases * 100:.1f}%",
            "",
            "Retrieval Metrics (avg):",
        ]

        for k, v in self.avg_retrieval_metrics.items():
            if isinstance(v, dict):
                for sub_k, sub_v in v.items():
                    lines.append(f"  {k}@{sub_k}: {sub_v:.3f}")
            else:
                lines.append(f"  {k}: {v:.3f}")

        lines.append("")
        lines.append("Citation Metrics (avg):")
        for k, v in self.avg_citation_metrics.items():
            lines.append(f"  {k}: {v:.3f}")

        lines.append("")
        lines.append(f"Avg Latency: {self.avg_latency_ms:.0f}ms")

        return "\n".join(lines)


class EvaluationHarness:
    """
    Harness for running RAG evaluations.

    Usage:
        harness = EvaluationHarness()
        harness.add_test_case(TestCase(
            query="What is GDPR?",
            relevant_doc_ids=["doc1", "doc2"],
        ))
        results = harness.run()
        print(results.summary())
    """

    def __init__(self, search_fn: Any = None):
        """
        Initialize harness.

        Args:
            search_fn: Function to call for search (default: uses app.api.search)
        """
        self.test_cases: list[TestCase] = []
        self.search_fn = search_fn

    def add_test_case(self, case: TestCase) -> None:
        """Add a test case."""
        self.test_cases.append(case)

    def add_test_cases_from_file(self, path: str | Path) -> None:
        """Load test cases from JSON file."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        for item in data.get("test_cases", []):
            self.test_cases.append(TestCase(
                query=item["query"],
                relevant_doc_ids=item.get("relevant_doc_ids", []),
                expected_answer_contains=item.get("expected_answer_contains", []),
                category=item.get("category", "general"),
            ))

    def run(self, verbose: bool = False) -> EvaluationResult:
        """Run all test cases and return aggregated results."""
        if self.search_fn is None:
            from enterprise_rag.api import search
            from enterprise_rag.api import SearchRequest
            self.search_fn = lambda q: search(SearchRequest(query=q, k=10))

        results: list[TestResult] = []

        for i, case in enumerate(self.test_cases):
            if verbose:
                print(f"[{i+1}/{len(self.test_cases)}] {case.query[:50]}...")

            result = self._run_single(case)
            results.append(result)

        return self._aggregate_results(results)

    def _run_single(self, case: TestCase) -> TestResult:
        """Run a single test case."""
        start = time.time()

        try:
            response = self.search_fn(case.query)
            latency_ms = (time.time() - start) * 1000

            # Handle both dict and Pydantic model responses
            if hasattr(response, "model_dump"):
                response = response.model_dump()
            elif hasattr(response, "dict"):
                response = response.dict()

            answer_data = response.get("answer", {})
            answer_text = answer_data.get("answer", "")
            sources = answer_data.get("sources", [])
            confidence = answer_data.get("confidence", "low")

            # Get retrieved doc IDs
            retrieved_doc_ids = [s.get("doc_id", "") for s in sources]

            # Compute metrics
            retrieval_metrics = compute_retrieval_metrics(
                retrieved_doc_ids=retrieved_doc_ids,
                relevant_doc_ids=set(case.relevant_doc_ids),
            )
            citation_metrics = compute_citation_metrics(
                answer_text=answer_text,
                sources=sources,
            )

            # Check if passed (at least one relevant doc found)
            passed = retrieval_metrics.hit_rate_at_k.get(10, 0) > 0

            # Also check expected keywords if provided
            if case.expected_answer_contains:
                answer_lower = answer_text.lower()
                keywords_found = all(
                    kw.lower() in answer_lower
                    for kw in case.expected_answer_contains
                )
                passed = passed and keywords_found

            return TestResult(
                query=case.query,
                retrieval_metrics=retrieval_metrics,
                citation_metrics=citation_metrics,
                answer=answer_text,
                confidence=confidence,
                latency_ms=latency_ms,
                passed=passed,
            )

        except Exception as e:
            return TestResult(
                query=case.query,
                retrieval_metrics=RetrievalMetrics(),
                citation_metrics=CitationMetrics(),
                answer="",
                confidence="low",
                latency_ms=(time.time() - start) * 1000,
                passed=False,
                error=str(e),
            )

    def _aggregate_results(self, results: list[TestResult]) -> EvaluationResult:
        """Aggregate individual results into summary."""
        if not results:
            return EvaluationResult(
                timestamp=datetime.now().isoformat(),
                total_cases=0,
                passed_cases=0,
                failed_cases=0,
                avg_retrieval_metrics={},
                avg_citation_metrics={},
                avg_latency_ms=0,
                results_by_category={},
            )

        # Count pass/fail
        passed = sum(1 for r in results if r.passed)
        failed = len(results) - passed

        # Average retrieval metrics
        avg_retrieval = self._average_retrieval_metrics([r.retrieval_metrics for r in results])

        # Average citation metrics
        avg_citation = self._average_citation_metrics([r.citation_metrics for r in results])

        # Average latency
        avg_latency = sum(r.latency_ms for r in results) / len(results)

        # Results by category
        categories: dict[str, list[TestResult]] = {}
        for i, result in enumerate(results):
            cat = self.test_cases[i].category if i < len(self.test_cases) else "general"
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(result)

        results_by_category = {}
        for cat, cat_results in categories.items():
            results_by_category[cat] = {
                "total": len(cat_results),
                "passed": sum(1 for r in cat_results if r.passed),
                "avg_latency_ms": sum(r.latency_ms for r in cat_results) / len(cat_results),
            }

        # Individual results
        individual = [
            {
                "query": r.query,
                "passed": r.passed,
                "confidence": r.confidence,
                "latency_ms": r.latency_ms,
                "retrieval": r.retrieval_metrics.to_dict(),
                "citation": r.citation_metrics.to_dict(),
                "error": r.error,
            }
            for r in results
        ]

        return EvaluationResult(
            timestamp=datetime.now().isoformat(),
            total_cases=len(results),
            passed_cases=passed,
            failed_cases=failed,
            avg_retrieval_metrics=avg_retrieval,
            avg_citation_metrics=avg_citation,
            avg_latency_ms=avg_latency,
            results_by_category=results_by_category,
            individual_results=individual,
        )

    def _average_retrieval_metrics(self, metrics_list: list[RetrievalMetrics]) -> dict[str, Any]:
        """Compute average retrieval metrics."""
        if not metrics_list:
            return {}

        n = len(metrics_list)
        avg: dict[str, Any] = {
            "precision": {},
            "recall": {},
            "mrr": 0.0,
            "ndcg": {},
            "hit_rate": {},
        }

        for m in metrics_list:
            avg["mrr"] += m.mrr / n
            for k, v in m.precision_at_k.items():
                avg["precision"][k] = avg["precision"].get(k, 0) + v / n
            for k, v in m.recall_at_k.items():
                avg["recall"][k] = avg["recall"].get(k, 0) + v / n
            for k, v in m.ndcg_at_k.items():
                avg["ndcg"][k] = avg["ndcg"].get(k, 0) + v / n
            for k, v in m.hit_rate_at_k.items():
                avg["hit_rate"][k] = avg["hit_rate"].get(k, 0) + v / n

        return avg

    def _average_citation_metrics(self, metrics_list: list[CitationMetrics]) -> dict[str, Any]:
        """Compute average citation metrics."""
        if not metrics_list:
            return {}

        n = len(metrics_list)
        return {
            "citation_precision": sum(m.citation_precision for m in metrics_list) / n,
            "citation_recall": sum(m.citation_recall for m in metrics_list) / n,
            "citation_coverage": sum(m.citation_coverage for m in metrics_list) / n,
            "avg_confidence": sum(m.avg_confidence for m in metrics_list) / n,
            "source_diversity": sum(m.source_diversity for m in metrics_list) / n,
        }
