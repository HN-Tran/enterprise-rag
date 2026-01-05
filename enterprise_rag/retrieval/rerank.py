"""Reranking windows using a dedicated reranker endpoint (TEI) or hybrid scores."""

from __future__ import annotations

from typing import Any

from enterprise_rag.config import settings


def rerank_windows(query: str, windows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rerank windows using dedicated reranker or fall back to hybrid scores."""
    if not settings.RERANK_ENABLED:
        # Skip reranking - use existing hybrid score
        out = [dict(w) for w in windows]
        for w in out:
            w["rerank"] = w.get("score", 0.5)
        out.sort(key=lambda x: x["rerank"], reverse=True)
        return out

    # Use dedicated reranker (TEI API)
    from enterprise_rag.llm import rerank

    docs = [{"id": w["window_id"], "text": w["text"]} for w in windows]
    scores = rerank(query=query, documents=docs)

    out = []
    for w in windows:
        w2 = dict(w)
        w2["rerank"] = float(scores.get(int(w["window_id"]), 0.0))
        out.append(w2)

    # Sort by rerank score, with window_id as tie-breaker for determinism
    out.sort(key=lambda x: (x["rerank"], -x["window_id"]), reverse=True)
    return out
