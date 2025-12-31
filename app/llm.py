"""LLM clients: embeddings + chat + rerank.

All endpoints are expected to be OpenAI-compatible except rerank,
which is usually custom in enterprise deployments.
"""

from __future__ import annotations

from typing import Any, Iterable, List

import requests

from app.config import settings


def _auth_headers(api_key: str) -> dict[str, str]:
    if not api_key:
        return {"Content-Type": "application/json"}
    return {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Compute embeddings via OpenAI-compatible /embeddings endpoint."""
    url = settings.EMBED_BASE_URL.rstrip("/") + "/embeddings"
    payload = {"model": settings.EMBED_MODEL, "input": texts}
    r = requests.post(url, json=payload, headers=_auth_headers(settings.EMBED_API_KEY), timeout=180)
    r.raise_for_status()
    data = r.json()
    vecs = [item["embedding"] for item in data["data"]]
    if vecs and len(vecs[0]) != settings.EMBED_DIM:
        raise ValueError(f"Embedding dim {len(vecs[0])} != EMBED_DIM {settings.EMBED_DIM}")
    return vecs


def chat_json(system: str, user: str, temperature: float = 0.1, timeout_s: int = 180) -> str:
    """Call OpenAI-compatible chat completions and return message content."""
    url = settings.LLM_BASE_URL.rstrip("/") + "/chat/completions"
    payload = {
        "model": settings.LLM_MODEL,
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    r = requests.post(url, json=payload, headers=_auth_headers(settings.LLM_API_KEY), timeout=timeout_s)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def rerank(query: str, documents: list[dict[str, Any]]) -> dict[int, float]:
    """Rerank windows using custom /rerank endpoint.

    Expects:
      POST {RERANK_BASE_URL}/rerank
      {"model":..., "query":..., "documents":[{"id":..., "text":...}, ...]}
    Returns:
      {window_id: score}
    """
    url = settings.RERANK_BASE_URL.rstrip("/") + "/rerank"
    payload = {"model": settings.RERANK_MODEL, "query": query, "documents": documents}
    r = requests.post(url, json=payload, headers=_auth_headers(settings.RERANK_API_KEY), timeout=180)
    r.raise_for_status()
    out = r.json()
    score_by_id: dict[int, float] = {}
    for item in out.get("results", []):
        score_by_id[int(item["id"])] = float(item["score"])
    return score_by_id
