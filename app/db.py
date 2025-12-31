"""Postgres access helpers."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Iterable

import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row

from app.config import settings


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


def get_conn() -> psycopg.Connection:
    """Create a new Postgres connection with vector support registered."""
    conn = psycopg.connect(settings.PG_DSN, row_factory=dict_row)
    register_vector(conn)
    return conn


def exec_script(sql: str) -> None:
    """Execute a multi-statement SQL script."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()


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
