"""Ingestion pipeline: extract -> pages/windows/anchors -> Postgres (+ optional Neo4j)."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from enterprise_rag.config import settings
from enterprise_rag.db import get_conn, make_doc_id, sha256_file
from enterprise_rag.ingestion.extractors import extract_any
from enterprise_rag.ingestion.normalize import norm_text
from enterprise_rag.ingestion.segment import build_anchors, build_windows
from enterprise_rag.ingestion.citations import extract_citations, ExtractedCitation
from enterprise_rag.ingestion.versioning import (
    is_old_by_pattern,
    mark_document_archived,
    check_url_replacement,
    check_and_handle_overlap,
)
from enterprise_rag.neo4j_amp import Neo4jAmp


def _sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _resolve_citation(cur: Any, cit: ExtractedCitation) -> str | None:
    """
    Try to resolve a citation to an existing document in the corpus.

    Returns target doc_id if found, None otherwise.
    """
    # URL match against document URIs
    if cit.citation_type == "url" and cit.target_uri:
        cur.execute(
            "SELECT doc_id FROM documents WHERE uri = %(uri)s",
            {"uri": cit.target_uri},
        )
        row = cur.fetchone()
        if row:
            return row["doc_id"]

    # For internal refs, try fuzzy title matching
    if cit.citation_type == "internal_ref" and len(cit.normalized_ref) >= 10:
        # Simple ILIKE match - could use pg_trgm for better fuzzy matching
        cur.execute(
            """
            SELECT doc_id, title FROM documents
            WHERE title ILIKE %(pattern)s
            LIMIT 1
            """,
            {"pattern": f"%{cit.normalized_ref[:50]}%"},
        )
        row = cur.fetchone()
        if row:
            return row["doc_id"]

    return None


def ingest_path(
    path: str,
    force: bool = False,
    title_override: str | None = None,
    source_url: str | None = None,
    download_url: str | None = None,
    supersedes_doc_id: str | None = None,
    category: str | None = None,
) -> dict[str, Any]:
    """Ingest a document into the RAG system.

    Args:
        path: Path to the file to ingest
        force: If True, re-ingest even if file hasn't changed
        title_override: Use this title instead of extracted title (from crawler anchor text)
        source_url: Page URL where document link was found (crawler metadata)
        download_url: Direct download URL (crawler metadata)
        supersedes_doc_id: If set, mark this doc_id as archived (manual version replacement)
        category: Category to add to document (accumulated, not replaced)

    Returns:
        Dict with ingestion results or duplicate status
    """
    ex = extract_any(path)
    file_hash = sha256_file(path)

    # For HTML/ASP files, hash the normalized extracted text instead of raw bytes.
    # Raw bytes often differ (whitespace, encoding, dynamic content) even when
    # the meaningful content is identical.
    if ex.source_type == "html":
        normalized_pages = [norm_text(p) for p in ex.pages]
        file_hash = _sha256_text("\n".join(normalized_pages))

    # Use title override if provided (e.g., from crawler anchor text)
    doc_title = title_override or ex.title

    # Check if this file pattern indicates an old version
    is_old, old_reason = is_old_by_pattern(ex.uri)

    # For crawled files, check for existing document by download_url or sha256
    # This prevents duplicates when same file is downloaded to different temp paths
    existing_doc_id: str | None = None
    if download_url or file_hash:
        with get_conn() as conn:
            with conn.cursor() as cur:
                # First try by download_url (most reliable for crawled files)
                if download_url:
                    cur.execute(
                        "SELECT doc_id FROM documents WHERE download_url = %(url)s LIMIT 1",
                        {"url": download_url},
                    )
                    row = cur.fetchone()
                    if row:
                        existing_doc_id = row["doc_id"]

                # Fallback: check by sha256 (same content = same document)
                if not existing_doc_id:
                    cur.execute(
                        "SELECT doc_id FROM documents WHERE sha256 = %(sha)s LIMIT 1",
                        {"sha": file_hash},
                    )
                    row = cur.fetchone()
                    if row:
                        existing_doc_id = row["doc_id"]

    # Use existing doc_id if found, otherwise generate from URI
    doc_id = existing_doc_id or make_doc_id(ex.uri)

    # Check if this URL was previously ingested with different content
    replaced_doc_id: str | None = None
    if download_url:
        replaced_doc_id = check_url_replacement(download_url, file_hash)

    # Check for existing document with same hash (skip if unchanged)
    if not force:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT doc_id, sha256, title, updated_at
                    FROM documents
                    WHERE doc_id = %(doc)s
                    """,
                    {"doc": doc_id},
                )
                existing = cur.fetchone()

                if existing and existing["sha256"] == file_hash:
                    # File hasn't changed - but still update metadata if needed
                    updates_made = []

                    # Accumulate category if provided
                    if category:
                        cur.execute(
                            """
                            UPDATE documents
                            SET categories = COALESCE(categories, ARRAY[]::text[]) || ARRAY[%(cat)s]
                            WHERE doc_id = %(doc)s
                              AND (categories IS NULL OR NOT (%(cat)s = ANY(categories)))
                            RETURNING doc_id
                            """,
                            {"doc": doc_id, "cat": category},
                        )
                        if cur.fetchone():
                            updates_made.append(f"category:{category}")

                    # Update last_seen_at if from crawler
                    if source_url:
                        cur.execute(
                            "UPDATE documents SET last_seen_at = now() WHERE doc_id = %(doc)s",
                            {"doc": doc_id},
                        )

                    conn.commit()

                    result = {
                        "status": "unchanged",
                        "doc_id": doc_id,
                        "title": existing["title"],
                        "message": "Document already ingested with same content",
                        "updated_at": existing["updated_at"].isoformat() if existing["updated_at"] else None,
                    }
                    if updates_made:
                        result["metadata_updated"] = updates_made
                    if category:
                        result["category"] = category
                    return result

    # Reuse already-normalized pages for HTML (computed earlier for content hash)
    if ex.source_type == "html":
        pages = normalized_pages  # type: ignore[possibly-undefined]
    else:
        pages = [norm_text(p) for p in ex.pages]
    anchors = build_anchors(pages)
    windows = build_windows(pages)

    with get_conn() as conn:
        with conn.cursor() as cur:
            # ---- documents ----
            # Build categories array: new category (if any) will be merged with existing
            new_categories = [category] if category else []

            cur.execute(
                """
                INSERT INTO documents (
                    doc_id, title, source_type, uri, sha256,
                    is_current, archive_reason,
                    source_url, download_url, last_seen_at,
                    categories,
                    updated_at
                )
                VALUES (
                    %(doc)s, %(title)s, %(typ)s, %(uri)s, %(sha)s,
                    %(is_current)s, %(archive_reason)s,
                    %(source_url)s, %(download_url)s, %(last_seen_at)s,
                    %(categories)s,
                    now()
                )
                ON CONFLICT (doc_id) DO UPDATE
                SET title=EXCLUDED.title,
                    source_type=EXCLUDED.source_type,
                    uri=EXCLUDED.uri,
                    sha256=EXCLUDED.sha256,
                    source_url=COALESCE(EXCLUDED.source_url, documents.source_url),
                    download_url=COALESCE(EXCLUDED.download_url, documents.download_url),
                    last_seen_at=COALESCE(EXCLUDED.last_seen_at, documents.last_seen_at),
                    categories=CASE
                        WHEN cardinality(%(categories)s::text[]) = 0 THEN documents.categories
                        WHEN documents.categories IS NULL THEN %(categories)s::text[]
                        WHEN %(categories)s::text[] <@ documents.categories THEN documents.categories
                        ELSE documents.categories || %(categories)s::text[]
                    END,
                    updated_at=now()
                """,
                {
                    "doc": doc_id,
                    "title": doc_title,
                    "typ": ex.source_type,
                    "uri": ex.uri,
                    "sha": file_hash,
                    "is_current": not is_old,  # Mark as non-current if old pattern detected
                    "archive_reason": old_reason,
                    "source_url": source_url,
                    "download_url": download_url,
                    "last_seen_at": datetime.now() if source_url else None,
                    "categories": new_categories,
                },
            )

            # ---- pages ----
            # IMPORTANT: tsv is GENERATED ALWAYS STORED in schema -> DO NOT insert/update it.
            for page_no, text in enumerate(pages, start=1):
                page_sha = _sha256_text(text)
                cur.execute(
                    """
                    INSERT INTO pages (doc_id, page_no, text, sha256)
                    VALUES (%(doc)s, %(pno)s, %(txt)s, %(sha)s)
                    ON CONFLICT (doc_id, page_no) DO UPDATE
                    SET text = EXCLUDED.text,
                        sha256 = EXCLUDED.sha256
                    """,
                    {"doc": doc_id, "pno": page_no, "txt": text, "sha": page_sha},
                )

            # ---- anchors ----
            # simple replace for doc
            cur.execute("DELETE FROM anchors WHERE doc_id=%(doc)s", {"doc": doc_id})
            for a in anchors:
                cur.execute(
                    """
                    INSERT INTO anchors (doc_id, page_no, anchor_type, start_offset, end_offset, text, sha256)
                    VALUES (%(doc)s, %(pno)s, %(typ)s, %(st)s, %(en)s, %(txt)s, %(sha)s)
                    """,
                    {
                        "doc": doc_id,
                        "pno": a.page_no,
                        "typ": a.anchor_type,
                        "st": a.start_offset,
                        "en": a.end_offset,
                        "txt": a.text,
                        "sha": a.sha256,
                    },
                )

            # ---- windows ----
            # IMPORTANT: tsv is GENERATED ALWAYS STORED in schema -> DO NOT insert/update it.
            # embedding is populated later via embed_windows.py (keep it NULL or default until then).
            # Delete old windows first (ensures clean re-ingestion when chunk sizes change)
            cur.execute("DELETE FROM windows WHERE doc_id=%(doc)s", {"doc": doc_id})
            for w in windows:
                win_sha = _sha256_text(w.text)
                cur.execute(
                    """
                    INSERT INTO windows (doc_id, page_start, page_end, text, sha256)
                    VALUES (%(doc)s, %(ps)s, %(pe)s, %(txt)s, %(sha)s)
                    """,
                    {"doc": doc_id, "ps": w.page_start, "pe": w.page_end, "txt": w.text, "sha": win_sha},
                )

            # ---- citations ----
            citations = extract_citations(pages, ex.links, doc_id)
            cur.execute("DELETE FROM citations WHERE source_doc_id=%(doc)s", {"doc": doc_id})
            citations_resolved = 0
            for cit in citations:
                # Try to resolve internal references to existing documents
                target_doc_id = _resolve_citation(cur, cit)
                if target_doc_id:
                    citations_resolved += 1

                cur.execute(
                    """
                    INSERT INTO citations (source_doc_id, target_doc_id, citation_type, raw_text,
                                          normalized_ref, page_no, char_offset, target_uri,
                                          resolved, confidence)
                    VALUES (%(src)s, %(tgt)s, %(ctype)s, %(raw)s, %(norm)s, %(pno)s,
                            %(offset)s, %(uri)s, %(resolved)s, %(conf)s)
                    ON CONFLICT (source_doc_id, normalized_ref, page_no) DO UPDATE
                    SET target_doc_id = EXCLUDED.target_doc_id,
                        resolved = EXCLUDED.resolved
                    """,
                    {
                        "src": doc_id,
                        "tgt": target_doc_id,
                        "ctype": cit.citation_type,
                        "raw": cit.raw_text[:500],  # Limit raw text length
                        "norm": cit.normalized_ref[:500],
                        "pno": cit.page_no,
                        "offset": cit.char_offset,
                        "uri": cit.target_uri,
                        "resolved": target_doc_id is not None,
                        "conf": cit.confidence,
                    },
                )

        conn.commit()

    # Optional Neo4j mirror for amplification
    if settings.USE_NEO4J:
        amp = Neo4jAmp.create()
        amp.ensure_schema()
        amp.upsert_doc(doc_id, ex.title, ex.uri, None, [])

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT anchor_id, page_no, anchor_type FROM anchors WHERE doc_id=%s", (doc_id,))
                arows = cur.fetchall()

                # Get resolved citations for CITES edges
                cur.execute(
                    """
                    SELECT citation_id, target_doc_id, citation_type, page_no
                    FROM citations
                    WHERE source_doc_id = %s AND resolved = TRUE
                    """,
                    (doc_id,),
                )
                crows = cur.fetchall()

        amp.upsert_pages_and_anchors(
            doc_id=doc_id,
            pages=list(range(1, len(pages) + 1)),
            anchors=[{"anchor_id": r["anchor_id"], "page_no": r["page_no"], "type": r["anchor_type"]} for r in arows],
        )

        # Create CITES edges for resolved citations
        for crow in crows:
            amp.upsert_citation_edge(
                source_doc_id=doc_id,
                target_doc_id=crow["target_doc_id"],
                citation_id=crow["citation_id"],
                citation_type=crow["citation_type"],
                page_no=crow["page_no"],
            )

        amp.close()

    # Handle version replacement
    archived_docs: list[str] = []

    # Mark superseded document as archived
    if supersedes_doc_id:
        if mark_document_archived(supersedes_doc_id, "manual"):
            archived_docs.append(supersedes_doc_id)

    # Mark replaced document as archived (same download_url, different content)
    if replaced_doc_id:
        if mark_document_archived(replaced_doc_id, "replaced"):
            archived_docs.append(replaced_doc_id)

    # Check for content overlap with existing documents
    overlaps: list[dict[str, Any]] = []
    if settings.VERSION_OVERLAP_ENABLED and not is_old:
        overlaps = check_and_handle_overlap(doc_id)
        for overlap in overlaps:
            if overlap.get("archived_doc_id"):
                archived_docs.append(overlap["archived_doc_id"])

    result = {
        "doc_id": doc_id,
        "title": doc_title,
        "source_type": ex.source_type,
        "pages": len(pages),
        "windows": len(windows),
        "anchors": len(anchors),
        "citations": len(citations),
        "citations_resolved": citations_resolved,
        "is_current": not is_old,
    }

    if category:
        result["category"] = category

    if archived_docs:
        result["archived_docs"] = archived_docs
    if overlaps:
        result["overlaps"] = overlaps
    if old_reason:
        result["archive_reason"] = old_reason

    return result
