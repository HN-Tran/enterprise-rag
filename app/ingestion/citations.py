"""Citation extraction from document text and embedded links."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal


@dataclass
class EmbeddedLink:
    """A hyperlink embedded in a PDF."""
    page_no: int
    uri: str
    text: str | None = None


@dataclass
class ExtractedCitation:
    """A citation/reference extracted from document content."""
    citation_type: Literal["url", "iso", "law", "internal_ref"]
    raw_text: str
    normalized_ref: str
    page_no: int
    char_offset: int | None = None
    confidence: float = 1.0
    target_uri: str | None = None


# URL pattern
_URL_PATTERN = re.compile(
    r'https?://[^\s<>"\'\)\]]+',
    re.IGNORECASE
)

# ISO/DIN standards
_ISO_PATTERN = re.compile(
    r'\b(?:DIN\s*(?:EN\s*)?)?ISO\s*(\d{4,5})(?:[-:]\d+)?\b',
    re.IGNORECASE
)

# German law/regulation references
_LAW_PATTERNS = [
    # DSGVO/GDPR with article
    (re.compile(r'\b(?:Art\.?\s*)?(\d+)\s*(?:Abs\.?\s*\d+)?\s*(?:DSGVO|GDPR|DS-GVO)\b', re.IGNORECASE), "DSGVO"),
    # BDSG
    (re.compile(r'\b§?\s*(\d+[a-z]?)\s*(?:Abs\.?\s*\d+)?\s*BDSG\b', re.IGNORECASE), "BDSG"),
    # Generic German law reference
    (re.compile(r'\b§\s*(\d+[a-z]?)\s*(?:Abs\.?\s*\d+)?\s*([A-Z]{2,6})\b'), None),
]

# German cross-reference patterns
_GERMAN_REF_PATTERNS = [
    re.compile(r'(?:siehe|s\.)\s+(?:auch\s+)?[„"]?(.{10,100}?)["""]?(?:\.|,|\n|$)', re.IGNORECASE),
    re.compile(r'gemäß\s+[„"]?(.{10,100}?)["""]?(?:\.|,|\n|$)', re.IGNORECASE),
    re.compile(r'laut\s+[„"]?(.{10,100}?)["""]?(?:\.|,|\n|$)', re.IGNORECASE),
    re.compile(r'nach\s+(?:Maßgabe\s+)?[„"]?(.{10,100}?)["""]?(?:\.|,|\n|$)', re.IGNORECASE),
]


def extract_citations(
    pages: list[str],
    links: list[EmbeddedLink] | None = None,
    source_doc_id: str | None = None,
) -> list[ExtractedCitation]:
    """
    Extract all citations from document pages and embedded links.

    Args:
        pages: List of page texts (1-indexed in output)
        links: Optional list of embedded hyperlinks from PDF
        source_doc_id: Document ID for context (unused currently)

    Returns:
        List of extracted citations
    """
    citations: list[ExtractedCitation] = []
    seen: set[tuple[str, int]] = set()  # (normalized_ref, page_no) for dedup

    # Extract from embedded links first (highest confidence)
    if links:
        for link in links:
            if link.uri and link.uri.startswith(("http://", "https://")):
                key = (link.uri, link.page_no)
                if key not in seen:
                    seen.add(key)
                    citations.append(ExtractedCitation(
                        citation_type="url",
                        raw_text=link.text or link.uri,
                        normalized_ref=link.uri,
                        page_no=link.page_no,
                        confidence=1.0,
                        target_uri=link.uri,
                    ))

    # Extract from page text
    for page_no, text in enumerate(pages, start=1):
        # URLs in text
        for match in _URL_PATTERN.finditer(text):
            url = _clean_url(match.group(0))
            key = (url, page_no)
            if key not in seen:
                seen.add(key)
                citations.append(ExtractedCitation(
                    citation_type="url",
                    raw_text=match.group(0),
                    normalized_ref=url,
                    page_no=page_no,
                    char_offset=match.start(),
                    confidence=0.95,
                    target_uri=url,
                ))

        # ISO/DIN standards
        for match in _ISO_PATTERN.finditer(text):
            iso_num = match.group(1)
            normalized = f"ISO {iso_num}"
            key = (normalized, page_no)
            if key not in seen:
                seen.add(key)
                citations.append(ExtractedCitation(
                    citation_type="iso",
                    raw_text=match.group(0),
                    normalized_ref=normalized,
                    page_no=page_no,
                    char_offset=match.start(),
                    confidence=0.95,
                ))

        # Law references
        for pattern, law_name in _LAW_PATTERNS:
            for match in pattern.finditer(text):
                if law_name:
                    normalized = f"{law_name} {match.group(1)}"
                else:
                    # Generic § reference
                    normalized = match.group(0).strip()
                key = (normalized, page_no)
                if key not in seen:
                    seen.add(key)
                    citations.append(ExtractedCitation(
                        citation_type="law",
                        raw_text=match.group(0),
                        normalized_ref=normalized,
                        page_no=page_no,
                        char_offset=match.start(),
                        confidence=0.9,
                    ))

        # German cross-references (lower confidence, needs resolution)
        for pattern in _GERMAN_REF_PATTERNS:
            for match in pattern.finditer(text):
                ref_text = match.group(1).strip()
                # Skip if too short or looks like a sentence fragment
                if len(ref_text) < 15 or ref_text.count(" ") > 15:
                    continue
                key = (ref_text.lower(), page_no)
                if key not in seen:
                    seen.add(key)
                    citations.append(ExtractedCitation(
                        citation_type="internal_ref",
                        raw_text=match.group(0),
                        normalized_ref=ref_text,
                        page_no=page_no,
                        char_offset=match.start(),
                        confidence=0.7,
                    ))

    return citations


def _clean_url(url: str) -> str:
    """Clean URL by removing trailing punctuation."""
    # Remove common trailing characters that get captured
    while url and url[-1] in ".,;:)]}\"'":
        url = url[:-1]
    return url
