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

Zitationsketten:
- Der Kontext kann "cited_documents" enthalten - Dokumente, die von den Hauptquellen zitiert werden
- Diese können als zusätzliche Belege dienen, besonders für Definitionen oder Referenzmaterial
- Bei Verwendung von Zitationsketten-Quellen, vermerke "(via Zitat)" in der Quelle
- Beispiel: "Gemäß ISO 27001 [3] (zitiert in [1])..."

Regeln:
- Nur Aussagen, die durch Belege gedeckt sind
- Jeder Beleg muss eine Window-Quelle, Anchor-Quelle oder cited_document referenzieren
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
      "confidence": 0.95,
      "via_citation": false
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

_INSUFFICIENT_EVIDENCE_BASE = "Nicht genügend belastbare Belege im Korpus gefunden."

_INSUFFICIENT_SUGGESTIONS = """

Mögliche nächste Schritte:
• Versuchen Sie eine spezifischere Formulierung der Frage
• Prüfen Sie, ob relevante Dokumente bereits im System erfasst sind
• Erweitern Sie die Suche auf verwandte Themen oder Begriffe"""


def extract_and_answer(query: str, context: dict[str, Any]) -> dict[str, Any]:
    """Extract evidence and generate cited answer."""
    user = json.dumps({"query": query, "context": context}, ensure_ascii=False)
    content = chat_json(system=_SYSTEM, user=user, temperature=0.0, timeout_s=240)

    try:
        parsed = json.loads(content)
    except Exception:
        return _build_insufficient_response(query=query, raw=content)

    sources = parsed.get("sources", [])
    if len(sources) < 2:
        return _build_insufficient_response(query=query, partial_sources=sources, raw=content)

    # Build CitedAnswer
    cited_answer = CitedAnswer(
        answer=parsed.get("answer", _INSUFFICIENT_EVIDENCE_BASE),
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


def _build_insufficient_response(
    query: str | None = None,
    partial_sources: list[dict[str, Any]] | None = None,
    raw: str | None = None,
) -> dict[str, Any]:
    """Build response when evidence is insufficient."""
    # Build helpful message
    if partial_sources and len(partial_sources) == 1:
        message = (
            f"Nur eine Quelle gefunden. Für eine zuverlässige Antwort werden "
            f"mindestens zwei unabhängige Belege benötigt.{_INSUFFICIENT_SUGGESTIONS}"
        )
    else:
        message = f"{_INSUFFICIENT_EVIDENCE_BASE}{_INSUFFICIENT_SUGGESTIONS}"

    # Include partial source if available
    sources = []
    if partial_sources:
        sources = [
            SourceCitation(
                index=i + 1,
                doc_id=s.get("doc_id", ""),
                title=s.get("title", "Unbekannt"),
                location=s.get("location", ""),
                snippet=s.get("snippet", ""),
                confidence=s.get("confidence", 0.0),
                uri=s.get("uri"),
            )
            for i, s in enumerate(partial_sources)
        ]

    result = asdict(CitedAnswer(
        answer=message,
        confidence="low",
        sources=sources,
        evidence_count=len(sources),
        insufficient_evidence=True,
    ))
    if raw:
        result["raw"] = raw
    return result
