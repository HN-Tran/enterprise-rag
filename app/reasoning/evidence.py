"""Evidence extraction + strict answering."""

from __future__ import annotations

import json
from typing import Any

from app.llm import chat_json

_SYSTEM = """\
Du bist ein Evidence Extractor + Answerer für Enterprise-RAG (Deutsch).
Regeln:
- Nur Aussagen, die durch Belege gedeckt sind.
- Jeder Beleg muss entweder eine Window-Quelle oder Anchor-Quelle referenzieren.
- Antworte ausschließlich als JSON im Schema:

{
  "evidence": [
    {
      "claim": "...",
      "source_type": "window" | "anchor",
      "doc_id": "...",
      "title": "...",
      "page_start": 1,
      "page_end": 2,
      "anchor_id": 123,
      "page_no": 5,
      "quote": "..."
    }
  ],
  "final_answer": "..."
}

Wenn weniger als 2 belastbare Belege vorhanden sind:
- final_answer = "Nicht genügend belastbare Belege im Korpus."
"""

def extract_and_answer(query: str, context: dict[str, Any]) -> dict[str, Any]:
    user = json.dumps({"query": query, "context": context}, ensure_ascii=False)
    content = chat_json(system=_SYSTEM, user=user, temperature=0.0, timeout_s=240)

    try:
        parsed = json.loads(content)
    except Exception:
        return {"evidence": [], "final_answer": "Nicht genügend belastbare Belege im Korpus.", "raw": content}

    if len(parsed.get("evidence", [])) < 2:
        parsed["final_answer"] = "Nicht genügend belastbare Belege im Korpus."
    return parsed
