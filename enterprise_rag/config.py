"""Application configuration (env-driven)."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # Reranker limits
    RERANK_CHARS_PER_DOC: int = 2000  # Chars sent to reranker per document

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
