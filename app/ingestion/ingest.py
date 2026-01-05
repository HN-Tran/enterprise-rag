"""Ingestion pipeline: extract -> pages/windows/anchors -> Postgres (+ optional Neo4j)."""

from __future__ import annotations

from typing import Any
import hashlib

from app.config import settings
from app.db import get_conn, make_doc_id, sha256_file
from app.ingestion.extractors import extract_any
from app.ingestion.normalize import norm_text
from app.ingestion.segment import build_anchors, build_windows
from app.ingestion.citations import extract_citations, ExtractedCitation
from app.neo4j_amp import Neo4jAmp


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


def ingest_path(path: str, force: bool = False) -> dict[str, Any]:
    """Ingest a document into the RAG system.

    Args:
        path: Path to the file to ingest
        force: If True, re-ingest even if file hasn't changed

    Returns:
        Dict with ingestion results or duplicate status
    """
    ex = extract_any(path)
    doc_id = make_doc_id(ex.uri)
    file_hash = sha256_file(path)

    # Check for existing document with same hash (skip if unchanged)
    if not force:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT doc_id, sha256, updated_at
                    FROM documents
                    WHERE doc_id = %(doc)s
                    """,
                    {"doc": doc_id},
                )
                existing = cur.fetchone()

                if existing and existing["sha256"] == file_hash:
                    # File hasn't changed, skip re-ingestion
                    return {
                        "status": "unchanged",
                        "doc_id": doc_id,
                        "message": "Document already ingested with same content",
                        "updated_at": existing["updated_at"].isoformat() if existing["updated_at"] else None,
                    }

    pages = [norm_text(p) for p in ex.pages]
    anchors = build_anchors(pages)
    windows = build_windows(pages)

    with get_conn() as conn:
        with conn.cursor() as cur:
            # ---- documents ----
            cur.execute(
                """
                INSERT INTO documents (doc_id, title, source_type, uri, sha256, updated_at)
                VALUES (%(doc)s, %(title)s, %(typ)s, %(uri)s, %(sha)s, now())
                ON CONFLICT (doc_id) DO UPDATE
                SET title=EXCLUDED.title,
                    source_type=EXCLUDED.source_type,
                    uri=EXCLUDED.uri,
                    sha256=EXCLUDED.sha256,
                    updated_at=now()
                """,
                {"doc": doc_id, "title": ex.title, "typ": ex.source_type, "uri": ex.uri, "sha": file_hash},
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
            for w in windows:
                win_sha = _sha256_text(w.text)
                cur.execute(
                    """
                    INSERT INTO windows (doc_id, page_start, page_end, text, sha256)
                    VALUES (%(doc)s, %(ps)s, %(pe)s, %(txt)s, %(sha)s)
                    ON CONFLICT (doc_id, page_start, page_end) DO UPDATE
                    SET text = EXCLUDED.text,
                        sha256 = EXCLUDED.sha256
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

    return {
        "doc_id": doc_id,
        "title": ex.title,
        "source_type": ex.source_type,
        "pages": len(pages),
        "windows": len(windows),
        "anchors": len(anchors),
        "citations": len(citations),
        "citations_resolved": citations_resolved,
    }
