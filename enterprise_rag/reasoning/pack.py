"""Context packing for evidence extraction with source indexing."""

from __future__ import annotations

from typing import Any

from enterprise_rag.config import settings


def pack_context(
    query: str,
    hits: list[dict[str, Any]],
    anchors: list[dict[str, Any]],
    cited_context: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Pack retrieval results into indexed context for the LLM.

    Each source gets a unique index for citation purposes.
    Windows are indexed first, then anchors, then cited documents.
    """
    # Limit number of hits to avoid context overflow
    hits = hits[:settings.PACK_MAX_SOURCES]

    packed_hits = []
    for i, h in enumerate(hits, start=1):
        page_start = h["page_start"]
        page_end = h["page_end"]
        location = f"Seite {page_start}" if page_start == page_end else f"Seite {page_start}-{page_end}"

        # Truncate text to stay within token budget
        text = h["text"][:settings.PACK_CHARS_PER_SOURCE]
        if len(h["text"]) > settings.PACK_CHARS_PER_SOURCE:
            text += "..."

        packed_hits.append(
            {
                "source_index": i,
                "window_id": h["window_id"],
                "doc_id": h["doc_id"],
                "title": h.get("title") or "Unbekannt",
                "uri": h.get("uri"),
                "category": h.get("category"),
                "location": location,
                "page_start": page_start,
                "page_end": page_end,
                "text": text,
            }
        )

    # Continue numbering for anchors (limit to remaining budget)
    remaining_budget = max(0, settings.PACK_MAX_SOURCES - len(hits))
    anchors = anchors[:remaining_budget]

    anchor_start_index = len(hits) + 1
    packed_anchors = []
    for i, a in enumerate(anchors, start=anchor_start_index):
        text = a["text"][:settings.PACK_CHARS_PER_SOURCE]
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
    if cited_context:
        for i, c in enumerate(cited_context[:settings.PACK_MAX_CITED_DOCS], start=cited_start_index):
            page_start = c["page_start"]
            page_end = c["page_end"]
            location = f"Seite {page_start}" if page_start == page_end else f"Seite {page_start}-{page_end}"

            text = c["text"][:settings.PACK_CHARS_PER_SOURCE]
            packed_cited.append(
                {
                    "source_index": i,
                    "window_id": c["window_id"],
                    "doc_id": c["doc_id"],
                    "title": c.get("title") or "Unbekannt",
                    "uri": c.get("uri"),
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
