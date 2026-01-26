"""Citation chain expansion for retrieval."""

from __future__ import annotations

from typing import Any

from enterprise_rag.config import settings
from enterprise_rag.db import get_conn
from enterprise_rag.neo4j_amp import Neo4jAmp


def expand_with_citations(
    hit_doc_ids: list[str],
    max_depth: int = 2,
    max_cited: int = 4,
    include_archived: bool = False,
) -> list[dict[str, Any]]:
    """
    Expand retrieval context with documents from citation chains.

    For each retrieved document, finds cited/citing documents via Neo4j
    graph traversal and returns representative windows from them.

    Args:
        hit_doc_ids: Document IDs from initial retrieval
        max_depth: Maximum citation chain depth to traverse
        max_cited: Maximum number of cited documents to include

    Returns:
        List of window dicts from cited documents
    """
    if not settings.USE_NEO4J or not hit_doc_ids:
        return []

    amp = Neo4jAmp.create()
    cited_doc_ids: dict[str, int] = {}  # doc_id -> min distance

    try:
        for doc_id in hit_doc_ids:
            # Outgoing citations (this doc cites X)
            outgoing = amp.get_citations_from(doc_id, depth=max_depth)
            for cited in outgoing:
                cid = cited["doc_id"]
                dist = cited["distance"]
                if cid not in hit_doc_ids:  # Don't duplicate hits
                    cited_doc_ids[cid] = min(cited_doc_ids.get(cid, 999), dist)

            # Incoming citations (X cites this doc) - slightly penalized
            incoming = amp.get_cited_by(doc_id, depth=1)
            for citing in incoming:
                cid = citing["doc_id"]
                dist = citing["distance"] + 1  # Penalize incoming
                if cid not in hit_doc_ids:
                    cited_doc_ids[cid] = min(cited_doc_ids.get(cid, 999), dist)
    finally:
        amp.close()

    if not cited_doc_ids:
        return []

    # Sort by distance (closest first) and limit
    sorted_cited = sorted(cited_doc_ids.items(), key=lambda x: x[1])[:max_cited]
    doc_ids_to_fetch = [doc_id for doc_id, _ in sorted_cited]

    return _fetch_cited_windows(doc_ids_to_fetch, include_archived)


def _fetch_cited_windows(doc_ids: list[str], include_archived: bool = False) -> list[dict[str, Any]]:
    """
    Fetch representative windows from cited documents.

    Gets the first window from each document to provide context.
    """
    if not doc_ids:
        return []

    # Filter by is_current unless include_archived is True
    current_filter = "" if include_archived else "AND d.is_current = TRUE"

    with get_conn() as conn:
        with conn.cursor() as cur:
            # Get first window from each doc (by page_start)
            cur.execute(
                f"""
                SELECT DISTINCT ON (w.doc_id)
                    w.window_id, w.doc_id, w.page_start, w.page_end, w.text,
                    d.title, d.download_url
                FROM windows w
                JOIN documents d ON d.doc_id = w.doc_id
                WHERE w.doc_id = ANY(%s)
                {current_filter}
                ORDER BY w.doc_id, w.page_start
                """,
                (doc_ids,),
            )
            rows = cur.fetchall()

    return [
        {
            "window_id": r["window_id"],
            "doc_id": r["doc_id"],
            "page_start": r["page_start"],
            "page_end": r["page_end"],
            "text": r["text"],
            "title": r["title"],
            "download_url": r["download_url"],
            "source_type": "citation_chain",
        }
        for r in rows
    ]
