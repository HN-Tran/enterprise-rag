"""Context packing for evidence extraction."""

from __future__ import annotations

from typing import Any


def pack_context(query: str, hits: list[dict[str, Any]], anchors: list[dict[str, Any]]) -> dict[str, Any]:
    packed_hits = []
    for h in hits:
        packed_hits.append(
            {
                "window_id": h["window_id"],
                "doc_id": h["doc_id"],
                "title": h.get("title"),
                "uri": h.get("uri"),
                "category": h.get("category"),
                "page_start": h["page_start"],
                "page_end": h["page_end"],
                "text": h["text"],
            }
        )

    packed_anchors = []
    for a in anchors:
        packed_anchors.append(
            {
                "anchor_id": a["anchor_id"],
                "doc_id": a["doc_id"],
                "page_no": a["page_no"],
                "type": a["anchor_type"],
                "text": a["text"],
            }
        )

    return {"query": query, "windows": packed_hits, "anchors": packed_anchors}
