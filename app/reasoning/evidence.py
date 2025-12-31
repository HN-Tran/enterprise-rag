"""Evidence extraction + strict answering with Perplexity-style citations."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from app.llm import chat_json
from app.models import CitedAnswer, SourceCitation

_SYSTEM = """\
Du bist ein Evidence Extractor + Answerer für Enterprise-RAG (Deutsch).

WICHTIG - Zitierregeln:
- Verwende Quellenverweise [1], [2], [3] etc. in deiner Antwort
- Jede faktische Aussage MUSS mit mindestens einer Quelle belegt sein
- Nummeriere die Quellen in der Reihenfolge ihrer ersten Verwendung

Regeln:
- Nur Aussagen, die durch Belege gedeckt sind
- Jeder Beleg muss eine Window-Quelle oder Anchor-Quelle referenzieren
- Bewerte die Konfidenz jeder Quelle (0.0-1.0)
- Antworte ausschließlich als JSON im Schema:

{
  "sources": [
    {
      "index": 1,
      "doc_id": "...",
      "title": "Dokumenttitel",
      "location": "Seite 12-14",
      "snippet": "Relevantes Zitat aus der Quelle...",
      "confidence": 0.95
    }
  ],
  "answer": "Laut [1] gilt... Zusätzlich zeigt [2], dass...",
  "overall_confidence": "high" | "medium" | "low"
}

Konfidenz-Bewertung:
- high: 3+ starke Belege, klare Übereinstimmung
- medium: 2 Belege oder teilweise Übereinstimmung
- low: Schwache Belege oder Unsicherheit

Wenn weniger als 2 belastbare Belege vorhanden sind:
- answer = "Nicht genügend belastbare Belege im Korpus gefunden."
- overall_confidence = "low"
"""

_INSUFFICIENT_EVIDENCE = "Nicht genügend belastbare Belege im Korpus gefunden."


def extract_and_answer(query: str, context: dict[str, Any]) -> dict[str, Any]:
    """Extract evidence and generate cited answer."""
    user = json.dumps({"query": query, "context": context}, ensure_ascii=False)
    content = chat_json(system=_SYSTEM, user=user, temperature=0.0, timeout_s=240)

    try:
        parsed = json.loads(content)
    except Exception:
        return _build_insufficient_response(raw=content)

    sources = parsed.get("sources", [])
    if len(sources) < 2:
        return _build_insufficient_response(raw=content)

    # Build CitedAnswer
    cited_answer = CitedAnswer(
        answer=parsed.get("answer", _INSUFFICIENT_EVIDENCE),
        confidence=parsed.get("overall_confidence", "low"),
        sources=[
            SourceCitation(
                index=s.get("index", i + 1),
                doc_id=s.get("doc_id", ""),
                title=s.get("title", "Unbekannt"),
                location=s.get("location", ""),
                snippet=s.get("snippet", ""),
                confidence=s.get("confidence", 0.0),
                uri=s.get("uri"),
            )
            for i, s in enumerate(sources)
        ],
        evidence_count=len(sources),
        insufficient_evidence=False,
    )

    return asdict(cited_answer)


def _build_insufficient_response(raw: str | None = None) -> dict[str, Any]:
    """Build response when evidence is insufficient."""
    result = asdict(CitedAnswer(
        answer=_INSUFFICIENT_EVIDENCE,
        confidence="low",
        sources=[],
        evidence_count=0,
        insufficient_evidence=True,
    ))
    if raw:
        result["raw"] = raw
    return result
