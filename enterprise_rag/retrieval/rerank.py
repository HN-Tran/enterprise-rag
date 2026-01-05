"""Reranking windows using a dedicated reranker endpoint."""

from __future__ import annotations

from typing import Any

from enterprise_rag.llm import rerank


def rerank_windows(query: str, windows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    docs = [{"id": w["window_id"], "text": w["text"]} for w in windows]
    scores = rerank(query=query, documents=docs)

    out = []
    for w in windows:
        w2 = dict(w)
        w2["rerank"] = float(scores.get(int(w["window_id"]), 0.0))
        out.append(w2)

    out.sort(key=lambda x: x["rerank"], reverse=True)
    return out
