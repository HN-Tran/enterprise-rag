"""Context packing for evidence extraction with source indexing."""

from __future__ import annotations

from typing import Any


def pack_context(query: str, hits: list[dict[str, Any]], anchors: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Pack retrieval results into indexed context for the LLM.

    Each source gets a unique index for citation purposes.
    Windows are indexed first, then anchors continue the numbering.
    """
    packed_hits = []
    for i, h in enumerate(hits, start=1):
        page_start = h["page_start"]
        page_end = h["page_end"]
        location = f"Seite {page_start}" if page_start == page_end else f"Seite {page_start}-{page_end}"

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
                "text": h["text"],
            }
        )

    # Continue numbering for anchors
    anchor_start_index = len(hits) + 1
    packed_anchors = []
    for i, a in enumerate(anchors, start=anchor_start_index):
        packed_anchors.append(
            {
                "source_index": i,
                "anchor_id": a["anchor_id"],
                "doc_id": a["doc_id"],
                "location": f"Seite {a['page_no']}, {a['anchor_type']}",
                "page_no": a["page_no"],
                "type": a["anchor_type"],
                "text": a["text"],
            }
        )

    return {"query": query, "windows": packed_hits, "anchors": packed_anchors}
