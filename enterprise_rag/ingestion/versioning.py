"""Document versioning: detection of old/archived versions and content overlap."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from enterprise_rag.config import settings
from enterprise_rag.db import get_conn


# Patterns indicating old/archived document versions
OLD_FILENAME_PATTERNS = [
    r"[\s_]alt\d*\.[^.]+$",  # *_alt.pdf, * alt.pdf, *_alt1.pdf
    r"[\s_]alt[\s_]",  # * alt hier.pdf, *_alt_v2.pdf
    r"^alt[\s_]",  # alt_*.pdf, alt *.pdf
    r"[\s_]old\d*\.[^.]+$",  # *_old.pdf, * old.pdf
    r"^old[\s_]",  # old_*.pdf, old *.pdf
    r"[\s_]archiv\d*\.[^.]+$",  # *_archiv.pdf, * archiv.pdf (German)
    r"^archiv[\s_]",  # archiv_*.pdf, archiv *.pdf
    r"_v\d+\.[^.]+$",  # *_v1.pdf, *_v2.pdf (older versions)
]

OLD_FOLDER_PATTERNS = [
    r"/alt/",
    r"/old/",
    r"/archiv/",
    r"/archive/",
    r"/archived/",
    r"/deprecated/",
]


@dataclass
class OverlapResult:
    """Result of checking for content overlap between documents."""

    similar_doc_id: str
    embedding_similarity: float
    text_overlap: float
    similar_doc_title: str
    similar_doc_created_at: datetime


def is_old_by_pattern(uri: str) -> tuple[bool, str | None]:
    """Check if URI indicates an old version based on filename or folder patterns.

    Args:
        uri: File URI or path

    Returns:
        Tuple of (is_old, reason) where reason is 'filename_pattern' or 'folder_pattern' or None
    """
    if not uri:
        return False, None

    uri_lower = uri.lower()
    filename = Path(uri).name.lower()

    # Check filename patterns
    for pattern in OLD_FILENAME_PATTERNS:
        if re.search(pattern, filename, re.IGNORECASE):
            return True, "filename_pattern"

    # Check folder patterns
    for pattern in OLD_FOLDER_PATTERNS:
        if re.search(pattern, uri_lower, re.IGNORECASE):
            return True, "folder_pattern"

    return False, None


def mark_document_archived(
    doc_id: str,
    reason: str,
    archived_at: datetime | None = None,
) -> bool:
    """Mark a document as archived (is_current = FALSE).

    Args:
        doc_id: Document ID to archive
        reason: Archive reason ('filename_pattern', 'folder_pattern', 'orphaned', 'replaced', 'manual')
        archived_at: Timestamp when archived (defaults to now)

    Returns:
        True if document was updated, False if not found
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE documents
                SET is_current = FALSE,
                    archived_at = COALESCE(%(archived_at)s, now()),
                    archive_reason = %(reason)s
                WHERE doc_id = %(doc_id)s AND is_current = TRUE
                RETURNING doc_id
                """,
                {"doc_id": doc_id, "reason": reason, "archived_at": archived_at},
            )
            result = cur.fetchone()
        conn.commit()
    return result is not None


def mark_crawl_seen(doc_ids: list[str]) -> int:
    """Update last_seen_at for documents found in current crawl.

    Args:
        doc_ids: List of document IDs that were seen

    Returns:
        Number of documents updated
    """
    if not doc_ids:
        return 0

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE documents
                SET last_seen_at = now()
                WHERE doc_id = ANY(%(doc_ids)s)
                """,
                {"doc_ids": doc_ids},
            )
            count = cur.rowcount
        conn.commit()
    return count


def mark_orphaned(source_url: str, seen_doc_ids: list[str]) -> int:
    """Mark documents from source_url not in seen_doc_ids as orphaned.

    This is called after a crawl to identify documents that were previously
    found on a page but are no longer present.

    Args:
        source_url: The source URL that was crawled
        seen_doc_ids: List of document IDs found in this crawl

    Returns:
        Number of documents marked as orphaned
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            if seen_doc_ids:
                cur.execute(
                    """
                    UPDATE documents
                    SET is_current = FALSE,
                        archived_at = now(),
                        archive_reason = 'orphaned'
                    WHERE source_url = %(source_url)s
                      AND is_current = TRUE
                      AND doc_id != ALL(%(seen_doc_ids)s)
                    """,
                    {"source_url": source_url, "seen_doc_ids": seen_doc_ids},
                )
            else:
                # No documents seen - mark all from this source as orphaned
                cur.execute(
                    """
                    UPDATE documents
                    SET is_current = FALSE,
                        archived_at = now(),
                        archive_reason = 'orphaned'
                    WHERE source_url = %(source_url)s
                      AND is_current = TRUE
                    """,
                    {"source_url": source_url},
                )
            count = cur.rowcount
        conn.commit()
    return count


def mark_unseen_orphaned(seen_doc_ids: list[str]) -> int:
    """Mark documents without a download_url as orphaned if not seen in this crawl.

    Targets folder-ingested documents that the crawler couldn't match by
    SHA256.  Documents that already have a ``download_url`` (i.e. were
    previously confirmed online) are left untouched.

    Args:
        seen_doc_ids: Document IDs matched during this crawl run.

    Returns:
        Number of documents marked as orphaned.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            if seen_doc_ids:
                cur.execute(
                    """
                    UPDATE documents
                    SET is_current = FALSE,
                        archived_at = now(),
                        archive_reason = 'unseen'
                    WHERE is_current = TRUE
                      AND download_url IS NULL
                      AND doc_id != ALL(%(seen)s)
                    """,
                    {"seen": seen_doc_ids},
                )
            else:
                cur.execute(
                    """
                    UPDATE documents
                    SET is_current = FALSE,
                        archived_at = now(),
                        archive_reason = 'unseen'
                    WHERE is_current = TRUE
                      AND download_url IS NULL
                    """,
                )
            count = cur.rowcount
        conn.commit()
    return count


def check_url_replacement(download_url: str, new_sha256: str) -> str | None:
    """Check if download_url exists with a different hash (file was replaced).

    Args:
        download_url: The download URL to check
        new_sha256: Hash of the new file

    Returns:
        Old doc_id if this URL had a different document, None otherwise
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT doc_id, sha256
                FROM documents
                WHERE download_url = %(url)s
                  AND is_current = TRUE
                ORDER BY created_at DESC
                LIMIT 1
                """,
                {"url": download_url},
            )
            row = cur.fetchone()

    if row and row["sha256"] != new_sha256:
        return row["doc_id"]
    return None


def find_similar_documents(
    doc_id: str,
    threshold: float | None = None,
) -> list[OverlapResult]:
    """Find existing documents with high embedding similarity.

    Uses vector search to find documents that might be newer/older versions
    of the given document based on content similarity.

    Args:
        doc_id: Document ID to find similar docs for
        threshold: Cosine similarity threshold (default from settings)

    Returns:
        List of OverlapResult for documents above threshold
    """
    if threshold is None:
        threshold = settings.VERSION_EMBEDDING_THRESHOLD

    with get_conn() as conn:
        with conn.cursor() as cur:
            # Get average embedding for the document
            cur.execute(
                """
                SELECT AVG(embedding) as avg_emb
                FROM windows
                WHERE doc_id = %(doc_id)s AND embedding IS NOT NULL
                """,
                {"doc_id": doc_id},
            )
            row = cur.fetchone()
            if not row or row["avg_emb"] is None:
                return []

            avg_emb = row["avg_emb"]

            # Find similar documents (exclude self)
            cur.execute(
                """
                WITH doc_embeddings AS (
                    SELECT d.doc_id, d.title, d.created_at,
                           AVG(w.embedding) as avg_emb
                    FROM documents d
                    JOIN windows w ON w.doc_id = d.doc_id
                    WHERE d.doc_id != %(doc_id)s
                      AND d.is_current = TRUE
                      AND w.embedding IS NOT NULL
                    GROUP BY d.doc_id, d.title, d.created_at
                )
                SELECT doc_id, title, created_at,
                       1 - (avg_emb <=> %(avg_emb)s::vector) as similarity
                FROM doc_embeddings
                WHERE 1 - (avg_emb <=> %(avg_emb)s::vector) >= %(threshold)s
                ORDER BY similarity DESC
                LIMIT 5
                """,
                {"doc_id": doc_id, "avg_emb": avg_emb, "threshold": threshold},
            )
            results = []
            for r in cur.fetchall():
                results.append(
                    OverlapResult(
                        similar_doc_id=r["doc_id"],
                        embedding_similarity=float(r["similarity"]),
                        text_overlap=0.0,  # Will be filled by confirm_text_overlap
                        similar_doc_title=r["title"],
                        similar_doc_created_at=r["created_at"],
                    )
                )
            return results


def confirm_text_overlap(doc_id1: str, doc_id2: str, threshold: float | None = None) -> float:
    """Calculate text overlap between two documents.

    Compares window texts using Jaccard similarity on word sets.

    Args:
        doc_id1: First document ID
        doc_id2: Second document ID
        threshold: Minimum threshold (not used for filtering, just for reference)

    Returns:
        Overlap ratio between 0 and 1
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            # Get all window texts for both documents
            cur.execute(
                """
                SELECT doc_id, text
                FROM windows
                WHERE doc_id IN (%(doc1)s, %(doc2)s)
                """,
                {"doc1": doc_id1, "doc2": doc_id2},
            )
            rows = cur.fetchall()

    # Separate texts by document
    texts1 = [r["text"] for r in rows if r["doc_id"] == doc_id1]
    texts2 = [r["text"] for r in rows if r["doc_id"] == doc_id2]

    if not texts1 or not texts2:
        return 0.0

    # Combine all text and extract word sets
    def extract_words(texts: list[str]) -> set[str]:
        words = set()
        for text in texts:
            # Simple word extraction (lowercase, alphanumeric only)
            words.update(re.findall(r"\b\w+\b", text.lower()))
        return words

    words1 = extract_words(texts1)
    words2 = extract_words(texts2)

    if not words1 or not words2:
        return 0.0

    # Jaccard similarity
    intersection = len(words1 & words2)
    union = len(words1 | words2)
    return intersection / union if union > 0 else 0.0


def check_and_handle_overlap(
    new_doc_id: str,
    mode: str | None = None,
) -> list[dict[str, Any]]:
    """Check for content overlap and handle according to mode.

    Args:
        new_doc_id: The newly ingested document ID
        mode: Handling mode ('auto' or 'prompt'), defaults to settings

    Returns:
        List of overlap results with actions taken
    """
    if not settings.VERSION_OVERLAP_ENABLED:
        return []

    mode = mode or settings.VERSION_OVERLAP_MODE

    # Find similar documents
    similar_docs = find_similar_documents(new_doc_id)
    if not similar_docs:
        return []

    results = []
    with get_conn() as conn:
        with conn.cursor() as cur:
            # Get new document's created_at
            cur.execute(
                "SELECT created_at FROM documents WHERE doc_id = %(doc_id)s",
                {"doc_id": new_doc_id},
            )
            new_doc_row = cur.fetchone()
            if not new_doc_row:
                return []
            new_doc_created = new_doc_row["created_at"]

            for overlap in similar_docs:
                # Confirm with text overlap
                text_overlap = confirm_text_overlap(new_doc_id, overlap.similar_doc_id)

                if text_overlap < settings.VERSION_TEXT_OVERLAP_THRESHOLD:
                    continue  # Not enough text overlap

                overlap.text_overlap = text_overlap

                # Determine which document is older
                if new_doc_created > overlap.similar_doc_created_at:
                    # New doc is newer, archive the old one
                    old_doc_id = overlap.similar_doc_id
                    action = "auto_archived" if mode == "auto" else "pending"
                else:
                    # New doc is older, archive the new one
                    old_doc_id = new_doc_id
                    action = "auto_archived" if mode == "auto" else "pending"

                if mode == "auto":
                    mark_document_archived(old_doc_id, "replaced")

                # Log the overlap
                cur.execute(
                    """
                    INSERT INTO version_overlap_log
                        (new_doc_id, old_doc_id, embedding_similarity, text_overlap, action)
                    VALUES (%(new)s, %(old)s, %(emb_sim)s, %(txt_overlap)s, %(action)s)
                    """,
                    {
                        "new": new_doc_id,
                        "old": old_doc_id,
                        "emb_sim": overlap.embedding_similarity,
                        "txt_overlap": text_overlap,
                        "action": action,
                    },
                )

                results.append(
                    {
                        "similar_doc_id": overlap.similar_doc_id,
                        "similar_doc_title": overlap.similar_doc_title,
                        "embedding_similarity": overlap.embedding_similarity,
                        "text_overlap": text_overlap,
                        "archived_doc_id": old_doc_id if mode == "auto" else None,
                        "action": action,
                    }
                )

        conn.commit()

    return results


def restore_document(doc_id: str) -> bool:
    """Restore an archived document to current status.

    Args:
        doc_id: Document ID to restore

    Returns:
        True if document was restored, False if not found or already current
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE documents
                SET is_current = TRUE,
                    archived_at = NULL,
                    archive_reason = NULL
                WHERE doc_id = %(doc_id)s AND is_current = FALSE
                RETURNING doc_id
                """,
                {"doc_id": doc_id},
            )
            result = cur.fetchone()
        conn.commit()
    return result is not None


def get_archived_documents(limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    """Get list of archived documents.

    Args:
        limit: Maximum number of documents to return
        offset: Number of documents to skip

    Returns:
        List of archived document info
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT doc_id, title, uri, archive_reason, archived_at, created_at
                FROM documents
                WHERE is_current = FALSE
                ORDER BY archived_at DESC
                LIMIT %(limit)s OFFSET %(offset)s
                """,
                {"limit": limit, "offset": offset},
            )
            return cur.fetchall()
