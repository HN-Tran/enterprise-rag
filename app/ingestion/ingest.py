"""Ingestion pipeline: extract -> pages/windows/anchors -> Postgres (+ optional Neo4j)."""

from __future__ import annotations

from typing import Any
import hashlib

from app.config import settings
from app.db import get_conn, make_doc_id, sha256_file
from app.ingestion.extractors import extract_any
from app.ingestion.normalize import norm_text
from app.ingestion.segment import build_anchors, build_windows
from app.neo4j_amp import Neo4jAmp


def _sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def ingest_path(path: str) -> dict[str, Any]:
    ex = extract_any(path)
    doc_id = make_doc_id(ex.uri)
    file_hash = sha256_file(path)

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

        amp.upsert_pages_and_anchors(
            doc_id=doc_id,
            pages=list(range(1, len(pages) + 1)),
            anchors=[{"anchor_id": r["anchor_id"], "page_no": r["page_no"], "type": r["anchor_type"]} for r in arows],
        )
        amp.close()

    return {
        "doc_id": doc_id,
        "title": ex.title,
        "source_type": ex.source_type,
        "pages": len(pages),
        "windows": len(windows),
        "anchors": len(anchors),
    }
