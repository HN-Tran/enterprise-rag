"""Shared dataclasses / types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class DocumentInfo:
    doc_id: str
    title: str
    source_type: str
    uri: Optional[str]


@dataclass(frozen=True)
class WindowRow:
    window_id: int
    doc_id: str
    page_start: int
    page_end: int
    text: str
    bm25: float
    vec: float
    blend: float
    title: Optional[str] = None
    uri: Optional[str] = None
    category: Optional[str] = None
    categories: Optional[list[str]] = None
    rerank: float = 0.0
