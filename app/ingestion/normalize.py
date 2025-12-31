"""Normalization and conservative cleanup."""

from __future__ import annotations

import re

_WS = re.compile(r"\s+")


def norm_text(text: str) -> str:
    """Normalize whitespace without destroying semantics."""
    text = text.replace("\x00", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _WS.sub(" ", text)
    return text.strip()


def clamp(text: str, max_chars: int) -> str:
    """Clamp text to a max char budget (hard safety)."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip()
