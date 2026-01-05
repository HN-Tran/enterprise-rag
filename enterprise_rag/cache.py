"""Redis caching layer for embeddings and query plans."""

from __future__ import annotations

import hashlib
import json
from functools import wraps
from typing import Any, Callable, TypeVar

from enterprise_rag.config import settings

# Optional Redis import - gracefully degrade if not available
try:
    import redis

    _HAS_REDIS = True
except ImportError:
    _HAS_REDIS = False
    redis = None  # type: ignore

# Global Redis client
_redis: Any = None

F = TypeVar("F", bound=Callable[..., Any])


def init_cache() -> None:
    """Initialize Redis connection. Call once at startup."""
    global _redis
    if not _HAS_REDIS or not settings.REDIS_URL:
        return
    _redis = redis.from_url(settings.REDIS_URL, decode_responses=False)


def close_cache() -> None:
    """Close Redis connection. Call at shutdown."""
    global _redis
    if _redis is not None:
        _redis.close()
        _redis = None


def is_cache_available() -> bool:
    """Check if caching is enabled and available."""
    return _redis is not None


def _hash_key(*args: Any, **kwargs: Any) -> str:
    """Create a stable hash key from function arguments."""
    # Convert args and kwargs to a stable string representation
    key_parts = [str(a) for a in args]
    key_parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
    key_str = "|".join(key_parts)
    return hashlib.sha256(key_str.encode("utf-8")).hexdigest()[:32]


def cached_embeddings(func: F) -> F:
    """Cache embedding results keyed by text content.

    Embeddings are deterministic for the same text, so we can cache them
    with a long TTL (24h default).
    """

    @wraps(func)
    def wrapper(texts: list[str]) -> list[list[float]]:
        if not is_cache_available():
            return func(texts)

        # Check cache for each text individually
        cached_results: dict[int, list[float]] = {}
        uncached_texts: list[tuple[int, str]] = []

        for i, text in enumerate(texts):
            cache_key = f"embed:{_hash_key(text)}"
            cached = _redis.get(cache_key)
            if cached:
                cached_results[i] = json.loads(cached)
            else:
                uncached_texts.append((i, text))

        # If all cached, return immediately
        if not uncached_texts:
            return [cached_results[i] for i in range(len(texts))]

        # Compute uncached embeddings
        texts_to_embed = [t for _, t in uncached_texts]
        new_embeddings = func(texts_to_embed)

        # Cache new embeddings
        for (orig_idx, text), embedding in zip(uncached_texts, new_embeddings):
            cache_key = f"embed:{_hash_key(text)}"
            _redis.setex(cache_key, settings.CACHE_EMBED_TTL, json.dumps(embedding))
            cached_results[orig_idx] = embedding

        # Return in original order
        return [cached_results[i] for i in range(len(texts))]

    return wrapper  # type: ignore


def cached_query_plan(func: F) -> F:
    """Cache query plan results keyed by query text.

    Query plans are deterministic for the same query (same LLM, same prompt),
    so we can cache them with a moderate TTL (1h default).
    """

    @wraps(func)
    def wrapper(query: str, *args: Any, **kwargs: Any) -> Any:
        if not is_cache_available():
            return func(query, *args, **kwargs)

        cache_key = f"plan:{_hash_key(query)}"
        cached = _redis.get(cache_key)
        if cached:
            return json.loads(cached)

        result = func(query, *args, **kwargs)

        # Cache the result (convert dataclass/dict to JSON-serializable)
        if hasattr(result, "__dict__"):
            # Dataclass - convert to dict
            cache_data = {k: v for k, v in result.__dict__.items()}
        else:
            cache_data = result

        _redis.setex(cache_key, settings.CACHE_QUERY_TTL, json.dumps(cache_data))
        return result

    return wrapper  # type: ignore


def cached_doc_metadata(ttl: int = 3600) -> Callable[[F], F]:
    """Cache document metadata lookups.

    Returns a decorator that caches function results keyed by doc_id.
    """

    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(doc_ids: list[str], *args: Any, **kwargs: Any) -> dict[str, Any]:
            if not is_cache_available():
                return func(doc_ids, *args, **kwargs)

            # Check cache for each doc_id
            cached_results: dict[str, Any] = {}
            uncached_ids: list[str] = []

            for doc_id in doc_ids:
                cache_key = f"doc:{doc_id}"
                cached = _redis.get(cache_key)
                if cached:
                    cached_results[doc_id] = json.loads(cached)
                else:
                    uncached_ids.append(doc_id)

            # If all cached, return immediately
            if not uncached_ids:
                return cached_results

            # Fetch uncached metadata
            new_metadata = func(uncached_ids, *args, **kwargs)

            # Cache new metadata
            for doc_id, meta in new_metadata.items():
                cache_key = f"doc:{doc_id}"
                _redis.setex(cache_key, ttl, json.dumps(meta))
                cached_results[doc_id] = meta

            return cached_results

        return wrapper  # type: ignore

    return decorator


def invalidate_doc_cache(doc_id: str) -> None:
    """Invalidate cached metadata for a document."""
    if is_cache_available():
        _redis.delete(f"doc:{doc_id}")


def get_cache_stats() -> dict[str, Any]:
    """Get cache statistics for monitoring."""
    if not is_cache_available():
        return {"enabled": False}

    info = _redis.info("stats")
    return {
        "enabled": True,
        "hits": info.get("keyspace_hits", 0),
        "misses": info.get("keyspace_misses", 0),
        "keys": _redis.dbsize(),
    }
