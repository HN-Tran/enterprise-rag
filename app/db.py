"""Postgres access helpers with connection pooling."""

from __future__ import annotations

import hashlib
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator, Iterable

import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.config import settings

# Global connection pool
_pool: ConnectionPool | None = None


def init_pool() -> None:
    """Initialize the connection pool. Call once at startup."""
    global _pool
    if _pool is not None:
        return

    _pool = ConnectionPool(
        settings.PG_DSN,
        min_size=settings.DB_POOL_MIN,
        max_size=settings.DB_POOL_MAX,
        timeout=settings.DB_POOL_TIMEOUT,
        open=True,
        configure=_configure_conn,
    )


def _configure_conn(conn: psycopg.Connection) -> None:
    """Configure each pooled connection (register vector, set row factory)."""
    conn.row_factory = dict_row
    register_vector(conn)


def close_pool() -> None:
    """Close the connection pool. Call at shutdown."""
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def sha256_text(text: str) -> str:
    """Return SHA-256 hex digest for UTF-8 text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: str) -> str:
    """Return SHA-256 hex digest for file bytes."""
    data = Path(path).read_bytes()
    return hashlib.sha256(data).hexdigest()


def make_doc_id(uri: str) -> str:
    """Stable, short doc id derived from URI/path."""
    return f"doc_{sha256_text(uri)[:16]}"


@contextmanager
def get_conn() -> Generator[psycopg.Connection, None, None]:
    """Get a connection from the pool. Use as context manager."""
    if _pool is None:
        # Fallback for scripts that don't initialize pool
        conn = psycopg.connect(settings.PG_DSN, row_factory=dict_row)
        register_vector(conn)
        try:
            yield conn
        finally:
            conn.close()
    else:
        with _pool.connection() as conn:
            yield conn


def exec_script(sql: str) -> None:
    """Execute a multi-statement SQL script.

    Uses a raw connection without vector registration since this is
    typically used for schema setup (which creates the vector extension).
    """
    conn = psycopg.connect(settings.PG_DSN, row_factory=dict_row)
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()
    finally:
        conn.close()


def fetch_all(sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Execute query and fetch all rows."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or {})
            rows = cur.fetchall()
        return list(rows)


def execute(sql: str, params: dict[str, Any] | None = None) -> None:
    """Execute a statement (INSERT/UPDATE/DELETE)."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or {})
        conn.commit()
