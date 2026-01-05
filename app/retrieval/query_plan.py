"""Query planning: rewrites + BM25 query + category inference."""

from __future__ import annotations

import json
import re

from app.cache import cached_query_plan
from app.llm import chat_json

_SYSTEM = """\
Du bist ein Query Planner für Enterprise-RAG (Deutsch, Behörden-/Unternehmensdokumente).

Gib ausschließlich JSON zurück:
{
  "rewrites": ["...","..."],
  "bm25_query": "...",
  "acronyms": {"SSO":"Single Sign-On"},
  "categories": ["identity_management","security"]
}

Regeln:
- 3-6 rewrites
- bm25_query als keyword-orientierte Query (kurz)
- categories nur wenn plausibel; sonst []
"""


def is_simple_query(query: str) -> bool:
    """Detect queries that don't need LLM rewriting.

    Simple queries are:
    - Short (1-3 words) without question marks
    - Exact phrases in quotes
    - Document IDs or reference numbers
    """
    query = query.strip()

    # Exact phrase in quotes - use as-is
    if query.startswith('"') and query.endswith('"') and query.count('"') == 2:
        return True

    # Document ID patterns (e.g., "doc_abc123", "ISO 27001")
    if re.match(r"^(doc_[a-f0-9]+|[A-Z]{2,5}[\s-]?\d+)$", query, re.IGNORECASE):
        return True

    # Short queries without question marks
    words = query.split()
    if len(words) <= 3 and "?" not in query:
        return True

    return False


def _plan_query_impl(query: str) -> dict:
    """Plan query using LLM (uncached implementation)."""
    content = chat_json(system=_SYSTEM, user=query, temperature=0.1, timeout_s=120)
    try:
        return json.loads(content)
    except Exception:
        return {"rewrites": [query], "bm25_query": query, "acronyms": {}, "categories": []}


# Apply caching decorator
_plan_query_cached = cached_query_plan(_plan_query_impl)


def plan_query(query: str) -> dict:
    """Plan query with optional LLM rewriting.

    Simple queries skip LLM planning entirely. Complex queries use LLM
    with caching to avoid redundant calls.
    """
    # Skip LLM for simple queries
    if is_simple_query(query):
        # For quoted phrases, strip quotes for BM25
        bm25_query = query.strip('"') if query.startswith('"') else query
        return {
            "rewrites": [query],
            "bm25_query": bm25_query,
            "acronyms": {},
            "categories": [],
        }

    # Use cached LLM planning for complex queries
    return _plan_query_cached(query)
