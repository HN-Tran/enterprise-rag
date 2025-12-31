"""Query planning: rewrites + BM25 query + category inference."""

from __future__ import annotations

import json

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


def plan_query(query: str) -> dict:
    content = chat_json(system=_SYSTEM, user=query, temperature=0.1, timeout_s=120)
    try:
        return json.loads(content)
    except Exception:
        return {"rewrites": [query], "bm25_query": query, "acronyms": {}, "categories": []}
