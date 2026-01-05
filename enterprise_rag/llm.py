"""LLM clients: embeddings + chat + rerank.

All endpoints are expected to be OpenAI-compatible except rerank,
which is usually custom in enterprise deployments.
"""

from __future__ import annotations

from typing import Any, Iterable, List

import requests

from enterprise_rag.cache import cached_embeddings
from enterprise_rag.config import settings


def _auth_headers(api_key: str) -> dict[str, str]:
    if not api_key:
        return {"Content-Type": "application/json"}
    return {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}


def _embed_texts_impl(texts: list[str]) -> list[list[float]]:
    """Compute embeddings via OpenAI-compatible /embeddings endpoint (uncached)."""
    url = settings.EMBED_BASE_URL.rstrip("/") + "/embeddings"
    payload = {"model": settings.EMBED_MODEL, "input": texts}
    r = requests.post(url, json=payload, headers=_auth_headers(settings.EMBED_API_KEY), timeout=180)
    r.raise_for_status()
    data = r.json()
    vecs = [item["embedding"] for item in data["data"]]
    if vecs and len(vecs[0]) != settings.EMBED_DIM:
        raise ValueError(f"Embedding dim {len(vecs[0])} != EMBED_DIM {settings.EMBED_DIM}")
    return vecs


# Apply caching decorator - caches individual text embeddings
embed_texts = cached_embeddings(_embed_texts_impl)


def chat_json(
    system: str,
    user: str,
    temperature: float = 0.1,
    timeout_s: int = 180,
    force_json: bool = True,
    max_tokens: int | None = None,
) -> str:
    """Call OpenAI-compatible chat completions and return message content."""
    url = settings.LLM_BASE_URL.rstrip("/") + "/chat/completions"
    payload = {
        "model": settings.LLM_MODEL,
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        # Ollama-specific: set context window size
        "options": {
            "num_ctx": settings.LLM_CONTEXT_LENGTH,
        },
    }
    # Force JSON output mode for Ollama
    if force_json:
        payload["format"] = "json"
    if max_tokens:
        payload["options"]["num_predict"] = max_tokens
    r = requests.post(url, json=payload, headers=_auth_headers(settings.LLM_API_KEY), timeout=timeout_s)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def rerank(query: str, documents: list[dict[str, Any]]) -> dict[int, float]:
    """Rerank using TEI (Text Embeddings Inference) reranker API.

    Expects TEI-compatible endpoint at RERANK_BASE_URL/rerank
    Returns:
      {window_id: score}
    """
    if not documents:
        return {}

    # TEI rerank API format
    url = settings.RERANK_BASE_URL.rstrip("/") + "/rerank"
    payload = {
        "query": query,
        "texts": [doc["text"][:settings.RERANK_CHARS_PER_DOC] for doc in documents],
        "return_text": False,
    }

    try:
        r = requests.post(url, json=payload, headers=_auth_headers(settings.RERANK_API_KEY), timeout=30)
        r.raise_for_status()
        results = r.json()

        # TEI returns list of {index, score} sorted by score desc
        score_by_id: dict[int, float] = {}
        for item in results:
            idx = item["index"]
            score_by_id[int(documents[idx]["id"])] = float(item["score"])
        return score_by_id
    except Exception:
        pass

    # Fallback: return uniform scores
    return {int(doc["id"]): 0.5 for doc in documents}
