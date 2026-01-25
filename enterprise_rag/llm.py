"""LLM clients: embeddings + chat + rerank.

All endpoints are expected to be OpenAI-compatible except rerank,
which is usually custom in enterprise deployments.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Generator, Iterable, List

import requests

from enterprise_rag.cache import cached_embeddings
from enterprise_rag.config import get_embedding_profile, settings

logger = logging.getLogger(__name__)


def _auth_headers(api_key: str) -> dict[str, str]:
    if not api_key:
        return {"Content-Type": "application/json"}
    return {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}


def _embed_texts_impl(texts: list[str], profile_name: str | None = None) -> list[list[float]]:
    """Compute embeddings via embedding endpoint (uncached).

    Uses the active embedding profile (EMBEDDING_PROFILE) to determine model and dimensions.
    Supports both OpenAI-compatible (Ollama) and TEI formats.

    Args:
        texts: List of texts to embed
        profile_name: Optional profile name ('nomic', 'qwen'). If None, uses default profile.
    """
    from enterprise_rag.config import EMBEDDING_PROFILES, EmbeddingProfile

    # Get the appropriate profile
    if profile_name and profile_name in EMBEDDING_PROFILES:
        base_profile = EMBEDDING_PROFILES[profile_name]
        # For nomic, populate base_url from settings
        if base_profile.name == "nomic" and base_profile.base_url is None:
            profile = EmbeddingProfile(
                name=base_profile.name,
                model=base_profile.model,
                dim=base_profile.dim,
                db_column=base_profile.db_column,
                base_url=settings.NOMIC_BASE_URL if hasattr(settings, 'NOMIC_BASE_URL') else None,
            )
        else:
            profile = base_profile
    else:
        profile = get_embedding_profile()
    base_url = profile.base_url or settings.EMBED_BASE_URL

    # TEI uses different format than OpenAI
    if profile.base_url:
        # TEI format: /embed endpoint with "inputs" field
        # Truncate texts to avoid exceeding TEI token limits (~4 chars per token, 8192 max)
        max_chars = 6000  # Conservative limit per text
        truncated = [t[:max_chars] if len(t) > max_chars else t for t in texts]
        url = base_url.rstrip("/").removesuffix("/v1") + "/embed"
        payload = {"inputs": truncated}
    else:
        # OpenAI format: /embeddings endpoint with "input" field
        url = base_url.rstrip("/") + "/embeddings"
        payload = {"model": profile.model, "input": texts}

    logger.debug(f"Embedding request: URL={url}, model={profile.model}, texts={len(texts)}")
    r = requests.post(url, json=payload, headers=_auth_headers(settings.EMBED_API_KEY), timeout=180)
    if not r.ok:
        logger.error(f"Embedding failed: {r.status_code} - {r.text[:500]}")
    r.raise_for_status()

    # TEI returns list directly, OpenAI returns {"data": [{"embedding": ...}]}
    data = r.json()
    if isinstance(data, list):
        vecs = data  # TEI format
    else:
        vecs = [item["embedding"] for item in data["data"]]  # OpenAI format

    if vecs and len(vecs[0]) != profile.dim:
        raise ValueError(f"Embedding dim {len(vecs[0])} != expected {profile.dim} for {profile.model}")
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


def chat_stream(
    system: str,
    user: str,
    temperature: float = 0.1,
    timeout_s: int = 180,
    max_tokens: int | None = None,
) -> Generator[str, None, None]:
    """Stream chat completions, yielding text chunks as they arrive.

    Uses Server-Sent Events (SSE) format from OpenAI-compatible endpoints.
    """
    url = settings.LLM_BASE_URL.rstrip("/") + "/chat/completions"
    payload = {
        "model": settings.LLM_MODEL,
        "temperature": temperature,
        "stream": True,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "options": {
            "num_ctx": settings.LLM_CONTEXT_LENGTH,
        },
    }
    if max_tokens:
        payload["options"]["num_predict"] = max_tokens

    with requests.post(
        url,
        json=payload,
        headers=_auth_headers(settings.LLM_API_KEY),
        timeout=timeout_s,
        stream=True,
    ) as r:
        r.raise_for_status()
        for line_bytes in r.iter_lines():
            if not line_bytes:
                continue
            # Force UTF-8 decoding
            line = line_bytes.decode("utf-8")
            if not line.startswith("data: "):
                continue
            data = line[6:]  # Remove "data: " prefix
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
                delta = chunk.get("choices", [{}])[0].get("delta", {})
                content = delta.get("content", "")
                if content:
                    yield content
            except json.JSONDecodeError:
                continue


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
    except Exception as e:
        logger.warning(f"Reranker failed, using fallback scores: {e}")

    # Fallback: return uniform scores (maintains hybrid ordering)
    return {int(doc["id"]): 0.5 for doc in documents}
