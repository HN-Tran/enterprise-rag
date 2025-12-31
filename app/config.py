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

    # Reranker (custom endpoint)
    RERANK_BASE_URL: str = "http://localhost:9001/v1"
    RERANK_MODEL: str = "qwen3-reranker-8b"
    RERANK_API_KEY: str = ""

    # LLM (query planning + evidence extraction + answer)
    LLM_BASE_URL: str = "http://localhost:11434/v1"
    LLM_MODEL: str = "qwen3-32b-instruct"
    LLM_API_KEY: str = ""

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

    # Category boosting
    CATEGORY_BOOST: float = 1.20


settings = Settings()
