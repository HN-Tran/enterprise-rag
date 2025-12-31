"""Shared dataclasses / types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Literal


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


# Citation-aware response models (Perplexity-style)


@dataclass
class SourceCitation:
    """A single source citation with location and confidence."""
    index: int                          # [1], [2], etc.
    doc_id: str
    title: str
    location: str                       # "Seite 12-14" or "Seite 5, Absatz 3"
    snippet: str                        # Relevant quote from source
    confidence: float                   # 0.0-1.0 confidence score
    uri: Optional[str] = None


@dataclass
class CitedAnswer:
    """Answer with Perplexity-style citations."""
    answer: str                                              # Answer text with [1], [2] citations
    confidence: Literal["high", "medium", "low"]             # Overall confidence
    sources: list[SourceCitation] = field(default_factory=list)
    evidence_count: int = 0
    insufficient_evidence: bool = False
