"""Postgres candidate generation (BM25-ish + vector)."""

from __future__ import annotations

from typing import Any

from enterprise_rag.config import get_embedding_profile, settings
from enterprise_rag.db import get_conn
from enterprise_rag.llm import embed_texts


def bm25_candidates(
    query: str,
    categories: list[str] | None,
    k: int,
    include_archived: bool = False,
) -> list[dict[str, Any]]:
    """Retrieve candidates using BM25 text search.

    Args:
        query: Search query text
        categories: Optional list of categories to boost
        k: Number of candidates to return
        include_archived: If True, include archived documents (is_current=FALSE)
    """
    cats = categories or []
    # Filter by is_current unless include_archived is True
    current_filter = "" if include_archived else "AND d.is_current = TRUE"

    with get_conn() as conn:
        with conn.cursor() as cur:
            if cats:
                cur.execute(
                    f"""
                    SELECT w.window_id, w.doc_id, w.page_start, w.page_end, w.text,
                           ts_rank_cd(w.tsv, websearch_to_tsquery('simple', %(q)s)) AS score
                    FROM windows w
                    JOIN documents d ON d.doc_id = w.doc_id
                    WHERE w.tsv @@ websearch_to_tsquery('simple', %(q)s)
                    AND (d.categories && %(cats)s::text[] OR d.categories IS NULL OR d.categories = '{{}}')
                    {current_filter}
                    ORDER BY score DESC
                    LIMIT %(k)s
                    """,
                    {"q": query, "k": k, "cats": cats},
                )
            else:
                cur.execute(
                    f"""
                    SELECT w.window_id, w.doc_id, w.page_start, w.page_end, w.text,
                           ts_rank_cd(w.tsv, websearch_to_tsquery('simple', %(q)s)) AS score
                    FROM windows w
                    JOIN documents d ON d.doc_id = w.doc_id
                    WHERE w.tsv @@ websearch_to_tsquery('simple', %(q)s)
                    {current_filter}
                    ORDER BY score DESC
                    LIMIT %(k)s
                    """,
                    {"q": query, "k": k},
                )
            return cur.fetchall()


def vector_candidates(
    query: str,
    k: int,
    embedding: list[float] | None = None,
    include_archived: bool = False,
    embedding_model: str | None = None,
    categories: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Retrieve candidates by vector similarity.

    Args:
        query: The query text (used for embedding if embedding not provided)
        k: Number of candidates to return
        embedding: Pre-computed embedding vector. If None, will compute it.
        include_archived: If True, include archived documents (is_current=FALSE)
        embedding_model: Optional embedding profile name ('nomic', 'qwen'). If None, uses default.
        categories: Optional list of categories for hard filtering

    Uses the specified or active embedding profile to determine which column to query.
    """
    from enterprise_rag.config import EMBEDDING_PROFILES
    if embedding_model and embedding_model in EMBEDDING_PROFILES:
        profile = EMBEDDING_PROFILES[embedding_model]
    else:
        profile = get_embedding_profile()
    col = profile.db_column  # e.g., "embedding" or "embedding_nomic"

    # Filter by is_current unless include_archived is True
    current_filter = "" if include_archived else "AND d.is_current = TRUE"
    cat_filter = "AND (d.categories && %(cats)s::text[] OR d.categories IS NULL OR d.categories = '{{}}')" if categories else ""

    qvec = embedding if embedding is not None else embed_texts([query])[0]
    params: dict[str, Any] = {"vec": qvec, "k": k}
    if categories:
        params["cats"] = categories

    with get_conn() as conn:
        with conn.cursor() as cur:
            # Dynamic column name - safe because it comes from config, not user input
            cur.execute(
                f"""
                SELECT w.window_id, w.doc_id, w.page_start, w.page_end, w.text,
                       1 - (w.{col} <=> %(vec)s::vector) AS score
                FROM windows w
                JOIN documents d ON d.doc_id = w.doc_id
                WHERE w.{col} IS NOT NULL
                {current_filter}
                {cat_filter}
                ORDER BY w.{col} <=> %(vec)s::vector
                LIMIT %(k)s
                """,
                params,
            )
            return cur.fetchall()
