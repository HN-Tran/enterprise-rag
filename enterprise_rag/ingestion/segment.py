"""Build anchors and windows."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import List

from enterprise_rag.config import settings
from enterprise_rag.ingestion.normalize import clamp, norm_text


def _sha32(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


@dataclass(frozen=True)
class Anchor:
    page_no: int
    anchor_type: str
    start_offset: int
    end_offset: int
    text: str
    sha256: str


@dataclass(frozen=True)
class Window:
    page_start: int
    page_end: int
    text: str
    sha256: str


def build_anchors(pages: List[str]) -> List[Anchor]:
    anchors: List[Anchor] = []
    for page_no, raw in enumerate(pages, start=1):
        text = norm_text(raw)
        if not text:
            continue

        # Conservative split: paragraph-ish
        parts = [p.strip() for p in raw.splitlines() if p.strip()]
        if len(parts) < 3:
            parts = [p.strip() for p in text.split("  ") if p.strip()]

        offset = 0
        for part in parts:
            t = clamp(norm_text(part), settings.MAX_ANCHOR_CHARS)
            if not t:
                continue
            a_type = "paragraph"
            if "\t" in t:
                a_type = "table"
            elif t.startswith(("-", "•", "*")):
                a_type = "list_item"

            start = offset
            end = offset + len(t)
            offset = end + 1

            anchors.append(Anchor(page_no, a_type, start, end, t, _sha32(t)))
    return anchors


def build_windows(pages: List[str]) -> List[Window]:
    w = max(1, settings.WINDOW_PAGES)
    stride = max(1, settings.WINDOW_STRIDE)
    out: List[Window] = []

    n = len(pages)
    i = 0
    while i < n:
        start = i
        end = min(n, i + w)
        slice_texts = [norm_text(pages[j]) for j in range(start, end) if norm_text(pages[j])]
        text = clamp("\n\n".join(slice_texts).strip(), settings.MAX_WINDOW_CHARS)
        if text:
            out.append(Window(page_start=start + 1, page_end=end, text=text, sha256=_sha32(text)))
        i += stride

    return out
