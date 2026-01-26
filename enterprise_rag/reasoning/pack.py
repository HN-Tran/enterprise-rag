"""Context packing for evidence extraction with source indexing."""

from __future__ import annotations

from typing import Any

from enterprise_rag.config import get_effective_limits, settings


def pack_context(
    query: str,
    hits: list[dict[str, Any]],
    anchors: list[dict[str, Any]],
    cited_context: list[dict[str, Any]] | None = None,
    limits: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Pack retrieval results into indexed context for the LLM.

    Each source gets a unique index for citation purposes.
    Windows are indexed first, then anchors, then cited documents.

    Args:
        query: User query
        hits: Retrieved windows
        anchors: Fine-grained anchors (tables, lists, etc.)
        cited_context: Documents from citation chain
        limits: Optional dynamic limits (from get_effective_limits)
    """
    # Use provided limits or fall back to settings
    if limits is None:
        limits = get_effective_limits()

    max_sources = limits.get("pack_max_sources", settings.PACK_MAX_SOURCES)
    chars_per_source = limits.get("pack_chars_per_source", settings.PACK_CHARS_PER_SOURCE)

    # Limit number of hits to avoid context overflow
    hits = hits[:max_sources]

    packed_hits = []
    for i, h in enumerate(hits, start=1):
        page_start = h["page_start"]
        page_end = h["page_end"]
        location = f"Seite {page_start}" if page_start == page_end else f"Seite {page_start}-{page_end}"

        # Truncate text to stay within token budget
        text = h["text"][:chars_per_source]
        if len(h["text"]) > chars_per_source:
            text += "..."

        packed_hits.append(
            {
                "source_index": i,
                "window_id": h["window_id"],
                "doc_id": h["doc_id"],
                "title": h.get("title") or "Unbekannt",
                "download_url": h.get("download_url"),
                "source_type": h.get("source_type"),
                "category": h.get("category"),
                "location": location,
                "page_start": page_start,
                "page_end": page_end,
                "text": text,
            }
        )

    # Continue numbering for anchors (limit to remaining budget)
    remaining_budget = max(0, max_sources - len(hits))
    anchors = anchors[:remaining_budget]

    anchor_start_index = len(hits) + 1
    packed_anchors = []
    for i, a in enumerate(anchors, start=anchor_start_index):
        text = a["text"][:chars_per_source]
        packed_anchors.append(
            {
                "source_index": i,
                "anchor_id": a["anchor_id"],
                "doc_id": a["doc_id"],
                "location": f"Seite {a['page_no']}, {a['anchor_type']}",
                "page_no": a["page_no"],
                "type": a["anchor_type"],
                "text": text,
            }
        )

    # Continue numbering for cited documents (from citation chain)
    cited_start_index = anchor_start_index + len(anchors)
    packed_cited = []
    max_cited = limits.get("pack_max_cited_docs", settings.PACK_MAX_CITED_DOCS)
    if cited_context:
        for i, c in enumerate(cited_context[:max_cited], start=cited_start_index):
            page_start = c["page_start"]
            page_end = c["page_end"]
            location = f"Seite {page_start}" if page_start == page_end else f"Seite {page_start}-{page_end}"

            text = c["text"][:chars_per_source]
            packed_cited.append(
                {
                    "source_index": i,
                    "window_id": c["window_id"],
                    "doc_id": c["doc_id"],
                    "title": c.get("title") or "Unbekannt",
                    "download_url": c.get("download_url"),
                    "location": location,
                    "text": text,
                    "relationship": "zitiert von Hauptquellen",
                }
            )

    return {
        "query": query,
        "windows": packed_hits,
        "anchors": packed_anchors,
        "cited_documents": packed_cited,
    }
