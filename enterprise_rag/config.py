"""Application configuration (env-driven)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict


@dataclass
class ModelProfile:
    """Model-specific configuration for different LLM capabilities."""

    name: str
    context_length: int
    max_answer_tokens: int
    # Evidence extraction limits
    evidence_max_windows: int
    evidence_chars_per_window: int
    evidence_max_anchors: int
    evidence_chars_per_anchor: int
    # Context packing limits
    pack_max_sources: int
    pack_chars_per_source: int


# Predefined model profiles for common configurations
MODEL_PROFILES: dict[str, ModelProfile] = {
    # Large models with big context windows
    "large": ModelProfile(
        name="large",
        context_length=32000,
        max_answer_tokens=800,
        evidence_max_windows=8,
        evidence_chars_per_window=2000,
        evidence_max_anchors=4,
        evidence_chars_per_anchor=1000,
        pack_max_sources=12,
        pack_chars_per_source=4000,
    ),
    # Medium models (default) - balanced performance
    "medium": ModelProfile(
        name="medium",
        context_length=16000,
        max_answer_tokens=500,
        evidence_max_windows=4,
        evidence_chars_per_window=1000,
        evidence_max_anchors=2,
        evidence_chars_per_anchor=600,
        pack_max_sources=8,
        pack_chars_per_source=3000,
    ),
    # Small/fast models - optimized for speed
    "small": ModelProfile(
        name="small",
        context_length=8000,
        max_answer_tokens=300,
        evidence_max_windows=3,
        evidence_chars_per_window=800,
        evidence_max_anchors=1,
        evidence_chars_per_anchor=400,
        pack_max_sources=5,
        pack_chars_per_source=2000,
    ),
}


class Settings(BaseSettings):
    """Strongly typed settings loaded from environment."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Postgres
    PG_DSN: str = "postgresql://rag:rag@localhost:5432/ragdb"

    # Neo4j (optional)
    USE_NEO4J: bool = True
    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = "neo4j"

    # Embeddings (OpenAI-compatible)
    EMBED_BASE_URL: str = "http://localhost:11434/v1"
    EMBED_MODEL: str = "qwen3-embedding-8b"
    EMBED_API_KEY: str = ""
    EMBED_DIM: int = 4096

    # Reranker - TEI (Text Embeddings Inference) with cross-encoder model
    # Much faster and more accurate than LLM-based reranking
    RERANK_ENABLED: bool = True
    RERANK_BASE_URL: str = "http://localhost:9001"  # TEI endpoint
    RERANK_MODEL: str = "BAAI/bge-reranker-v2-m3"  # Configured in docker-compose
    RERANK_API_KEY: str = ""

    # LLM (query planning + evidence extraction + answer)
    LLM_BASE_URL: str = "http://localhost:11434/v1"
    LLM_MODEL: str = "qwen3-32b-instruct"
    LLM_API_KEY: str = ""
    LLM_CONTEXT_LENGTH: int = 16000  # num_ctx for Ollama

    # Ingestion / windowing
    WINDOW_PAGES: int = 2
    WINDOW_STRIDE: int = 1
    MAX_WINDOW_CHARS: int = 24000
    MAX_ANCHOR_CHARS: int = 2000

    # Retrieval
    CANDIDATES_BM25: int = 120
    CANDIDATES_VEC: int = 120
    RERANK_KEEP: int = 18
    MAX_PER_DOC: int = 2
    MAX_QUERY_REWRITES: int = 6  # Max query variations for BM25

    # Category boosting
    CATEGORY_BOOST: float = 1.20

    # Context packing (pack.py) - how much context to send to LLM
    PACK_MAX_SOURCES: int = 8  # Max windows to pack
    PACK_CHARS_PER_SOURCE: int = 3000  # Chars per window
    PACK_MAX_CITED_DOCS: int = 2  # Max cited documents from graph

    # Evidence extraction (evidence.py) - context sent for answer generation
    # These can be lower than packing limits for faster responses
    EVIDENCE_MAX_WINDOWS: int = 4  # Windows sent to LLM for answering
    EVIDENCE_CHARS_PER_WINDOW: int = 1000  # Chars per window
    EVIDENCE_MAX_ANCHORS: int = 2  # Anchors (tables, lists) sent to LLM
    EVIDENCE_CHARS_PER_ANCHOR: int = 600  # Chars per anchor
    EVIDENCE_FALLBACK_ANSWER_CHARS: int = 3000  # Max chars for fallback answers
    EVIDENCE_FALLBACK_SNIPPET_CHARS: int = 200  # Snippet length in fallback

    # Reranker limits (TEI has max_batch_tokens=16384, keep payload small)
    RERANK_CHARS_PER_DOC: int = 512  # Chars sent to reranker per document

    # LLM output limits (prevents infinite generation)
    LLM_MAX_ANSWER_TOKENS: int = 500  # Max tokens for answer generation

    # Model profile (small, medium, large) - overrides individual limits when set
    MODEL_PROFILE: str = ""  # Empty = use individual settings

    # Dynamic context sizing - adjusts limits based on query complexity
    DYNAMIC_CONTEXT: bool = True  # Enable/disable dynamic sizing
    DYNAMIC_MIN_MULTIPLIER: float = 0.5  # Min multiplier for simple queries
    DYNAMIC_MAX_MULTIPLIER: float = 1.5  # Max multiplier for complex queries

    # Connection pooling
    DB_POOL_MIN: int = 5
    DB_POOL_MAX: int = 20
    DB_POOL_TIMEOUT: float = 30.0

    # Redis caching
    REDIS_URL: str | None = None
    CACHE_EMBED_TTL: int = 86400  # 24h for embeddings
    CACHE_QUERY_TTL: int = 3600  # 1h for query plans

    # Async ingestion
    ASYNC_INGEST: bool = False

    # Observability
    OTEL_ENDPOINT: str | None = None
    LOG_JSON: bool = True
    LOG_LEVEL: str = "INFO"


settings = Settings()


def get_model_profile() -> ModelProfile | None:
    """Get the active model profile if configured."""
    if settings.MODEL_PROFILE and settings.MODEL_PROFILE in MODEL_PROFILES:
        return MODEL_PROFILES[settings.MODEL_PROFILE]
    return None


def get_effective_limits(complexity: float = 1.0) -> dict[str, Any]:
    """Get effective limits, considering model profile and dynamic sizing.

    Args:
        complexity: Query complexity score (0.5 = simple, 1.0 = normal, 1.5+ = complex)

    Returns:
        Dictionary with effective limits for context packing and evidence extraction
    """
    profile = get_model_profile()

    # Base values from profile or settings
    if profile:
        limits = {
            "context_length": profile.context_length,
            "max_answer_tokens": profile.max_answer_tokens,
            "evidence_max_windows": profile.evidence_max_windows,
            "evidence_chars_per_window": profile.evidence_chars_per_window,
            "evidence_max_anchors": profile.evidence_max_anchors,
            "evidence_chars_per_anchor": profile.evidence_chars_per_anchor,
            "pack_max_sources": profile.pack_max_sources,
            "pack_chars_per_source": profile.pack_chars_per_source,
        }
    else:
        limits = {
            "context_length": settings.LLM_CONTEXT_LENGTH,
            "max_answer_tokens": settings.LLM_MAX_ANSWER_TOKENS,
            "evidence_max_windows": settings.EVIDENCE_MAX_WINDOWS,
            "evidence_chars_per_window": settings.EVIDENCE_CHARS_PER_WINDOW,
            "evidence_max_anchors": settings.EVIDENCE_MAX_ANCHORS,
            "evidence_chars_per_anchor": settings.EVIDENCE_CHARS_PER_ANCHOR,
            "pack_max_sources": settings.PACK_MAX_SOURCES,
            "pack_chars_per_source": settings.PACK_CHARS_PER_SOURCE,
        }

    # Apply dynamic sizing if enabled
    if settings.DYNAMIC_CONTEXT and complexity != 1.0:
        # Clamp complexity to configured range
        multiplier = max(
            settings.DYNAMIC_MIN_MULTIPLIER,
            min(settings.DYNAMIC_MAX_MULTIPLIER, complexity),
        )

        # Scale limits that benefit from dynamic sizing
        limits["evidence_max_windows"] = max(2, int(limits["evidence_max_windows"] * multiplier))
        limits["evidence_chars_per_window"] = int(limits["evidence_chars_per_window"] * multiplier)
        limits["evidence_max_anchors"] = max(1, int(limits["evidence_max_anchors"] * multiplier))
        limits["pack_max_sources"] = max(3, int(limits["pack_max_sources"] * multiplier))
        limits["pack_chars_per_source"] = int(limits["pack_chars_per_source"] * multiplier)

        # For complex queries, also increase answer tokens
        if complexity > 1.2:
            limits["max_answer_tokens"] = int(limits["max_answer_tokens"] * min(1.5, multiplier))

    return limits
