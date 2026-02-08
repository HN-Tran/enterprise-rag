"""Evidence extraction + strict answering with Perplexity-style citations."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from enterprise_rag.config import get_effective_limits, get_llm_profile, settings
from enterprise_rag.llm import chat_json, chat_stream
from enterprise_rag.models import CitedAnswer, SourceCitation

_SYSTEM = """\
Du bist ein präziser Frage-Antwort-Assistent. Du antwortest NUR mit validem JSON.

KRITISCH: Du MUSST als reines JSON antworten. Kein Markdown, keine Erklärungen außerhalb des JSON.

ANTWORTLÄNGE:
- Wertfragen (Zahlen, Namen, Daten, Ja/Nein): Kurz und knapp, nur der Wert mit Quelle.
  Beispiel: "Der Umsatz 2024 beträgt 1,2 Mio. EUR [1]."
- Erklärungsfragen (Warum, Wie, Was bedeutet): Ausführlich und korrekt erklären.
  Beispiel: "Das Verfahren funktioniert wie folgt: ... [1]. Dabei ist zu beachten, dass ... [2]."
- Viele Werte/Argumente: Wenn die Antwort viele Einzelwerte oder Argumente enthält, \
die nicht alle im Text passen, verweise auf die Quelle: "Details siehe [1], Seite 12-14."

REGELN:
1. Antworte in der GLEICHEN SPRACHE wie die Frage (Deutsch → Deutsch)
2. Verwende Quellenverweise [1], [2] im "answer" Text
3. Gib NUR das JSON zurück, nichts anderes
4. Wenn die Quellen KEINE klare, sichere Antwort ermöglichen: \
Verwende die Standardantwort (siehe unten). Lieber keine Antwort als eine unsichere.

AUSGABEFORMAT (exakt dieses JSON-Schema verwenden):

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

Wenn KEINE belastbaren Belege vorhanden sind ODER die Antwort nicht sicher ableitbar ist:
- answer = "Nicht genügend belastbare Belege im Korpus gefunden."
- overall_confidence = "low"
- Gib trotzdem die besten verfügbaren sources zurück, damit der Nutzer selbst nachschlagen kann.

Bei nur einem Beleg: Antworte trotzdem, aber setze overall_confidence = "low".
"""

_INSUFFICIENT_EVIDENCE_BASE = "Nicht genügend belastbare Belege im Korpus gefunden."

_INSUFFICIENT_SUGGESTIONS = """

Mögliche nächste Schritte:
• Versuchen Sie eine spezifischere Formulierung der Frage
• Prüfen Sie, ob relevante Dokumente bereits im System erfasst sind
• Erweitern Sie die Suche auf verwandte Themen oder Begriffe"""


def _extract_json_from_response(content: str) -> dict | None:
    """Try to extract JSON from response, handling markdown code blocks."""
    import re

    parsed = None

    # Try direct parse first
    try:
        parsed = json.loads(content)
    except Exception:
        pass

    # Try to find JSON in code blocks
    if not parsed:
        json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
        if json_match:
            try:
                parsed = json.loads(json_match.group(1))
            except Exception:
                pass

    # Try to find any JSON object
    if not parsed:
        json_match = re.search(r"\{[^{}]*\}", content, re.DOTALL)
        if json_match:
            try:
                parsed = json.loads(json_match.group())
            except Exception:
                pass

    if not parsed:
        return None

    # Normalize keys - LLM sometimes uses different key names
    if "answer" not in parsed:
        # Try to find answer in other common keys
        for key in list(parsed.keys()):
            if key not in ("sources", "source", "overall_confidence", "confidence"):
                # Use first non-standard key as answer
                val = parsed[key]
                if isinstance(val, str):
                    parsed["answer"] = val
                    break

    if "sources" not in parsed and "source" in parsed:
        parsed["sources"] = parsed["source"]

    if "overall_confidence" not in parsed:
        parsed["overall_confidence"] = parsed.get("confidence", "medium")

    return parsed


def _build_fallback_response(query: str, content: str, context: dict[str, Any]) -> dict[str, Any]:
    """Build response from non-JSON LLM output by using the text directly."""
    # The LLM generated useful content but not in JSON format
    # Use the markdown content as the answer
    sources = []
    for i, w in enumerate(context.get("windows", [])[:3]):
        sources.append(SourceCitation(
            index=i + 1,
            doc_id=w.get("doc_id", ""),
            title=w.get("title", "Unbekannt"),
            location=w.get("location", ""),
            snippet=w.get("text", "")[:settings.EVIDENCE_FALLBACK_SNIPPET_CHARS],
            confidence=0.7,
            uri=w.get("download_url"),
        ))

    return asdict(CitedAnswer(
        answer=content[:settings.EVIDENCE_FALLBACK_ANSWER_CHARS],
        confidence="medium",
        sources=sources,
        evidence_count=len(sources),
        insufficient_evidence=False,
    ))


def _format_context_as_text(
    query: str,
    context: dict[str, Any],
    limits: dict[str, Any] | None = None,
) -> str:
    """Format context as plain text to avoid JSON-in-JSON confusion."""
    if limits is None:
        limits = get_effective_limits()

    max_windows = limits.get("evidence_max_windows", settings.EVIDENCE_MAX_WINDOWS)
    chars_per_window = limits.get("evidence_chars_per_window", settings.EVIDENCE_CHARS_PER_WINDOW)
    max_anchors = limits.get("evidence_max_anchors", settings.EVIDENCE_MAX_ANCHORS)
    chars_per_anchor = limits.get("evidence_chars_per_anchor", settings.EVIDENCE_CHARS_PER_ANCHOR)

    lines = [f"FRAGE: {query}", "", "QUELLEN:"]

    # Windows (main document chunks)
    for w in context.get("windows", [])[:max_windows]:
        idx = w.get("source_index", "?")
        title = w.get("title", "Unbekannt")
        location = w.get("location", "")
        text = w.get("text", "")[:chars_per_window]
        lines.append(f"\n[{idx}] {title} ({location})")
        lines.append(text)

    # Anchors (tables, lists, paragraphs)
    for a in context.get("anchors", [])[:max_anchors]:
        idx = a.get("source_index", "?")
        location = a.get("location", "")
        text = a.get("text", "")[:chars_per_anchor]
        lines.append(f"\n[{idx}] Anchor ({location})")
        lines.append(text)

    return "\n".join(lines)


def extract_and_answer(
    query: str,
    context: dict[str, Any],
    complexity: float = 1.0,
    llm_model: str | None = None,
) -> dict[str, Any]:
    """Extract evidence and generate cited answer.

    Args:
        query: User query
        context: Packed context from pack_context()
        complexity: Query complexity score for dynamic sizing (0.5 - 1.5+)
        llm_model: LLM mode - "instruct", "reasoning", or None (default)
    """
    # Get dynamic limits based on complexity
    limits = get_effective_limits(complexity)

    # Resolve LLM profile
    profile = get_llm_profile(llm_model)

    # Format as plain text to avoid JSON-in-JSON confusion with LLM
    user = _format_context_as_text(query, context, limits) + "\n\nAntworte als JSON."

    # max_tokens prevents infinite generation on complex queries
    max_tokens = limits.get("max_answer_tokens", settings.LLM_MAX_ANSWER_TOKENS)
    content = chat_json(
        system=_SYSTEM,
        user=user,
        temperature=0.0,
        timeout_s=120,  # Reduced timeout since we cap tokens
        force_json=False,
        max_tokens=max_tokens,
        model=profile.model,
        think=profile.think,
    )

    # Try to parse JSON
    parsed = _extract_json_from_response(content)

    if parsed is None:
        # LLM didn't return JSON - use the text response directly
        if len(content) > 100:  # Has substantial content
            return _build_fallback_response(query, content, context)
        return _build_insufficient_response(query=query, raw=content)

    sources = parsed.get("sources", [])
    if len(sources) < 1:
        # No sources in JSON but might have useful answer
        if parsed.get("answer") and len(parsed.get("answer", "")) > 50:
            return _build_fallback_response(query, parsed.get("answer"), context)
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
                uri=s.get("download_url"),
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
                uri=s.get("download_url"),
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


# Streaming support - plain text output with same logic as JSON version
_STREAM_SYSTEM = """\
Du bist ein präziser Frage-Antwort-Assistent.

ANTWORTLÄNGE:
- Wertfragen (Zahlen, Namen, Daten, Ja/Nein): Kurz und knapp, nur der Wert mit Quelle.
  Beispiel: "Der Umsatz 2024 beträgt 1,2 Mio. EUR [1]."
- Erklärungsfragen (Warum, Wie, Was bedeutet): Ausführlich und korrekt erklären.
  Beispiel: "Das Verfahren funktioniert wie folgt: ... [1]. Dabei ist zu beachten, dass ... [2]."
- Viele Werte/Argumente: Wenn die Antwort viele Einzelwerte oder Argumente enthält, \
die nicht alle im Text passen, verweise auf die Quelle: "Details siehe [1], Seite 12-14."

REGELN:
1. Antworte in der GLEICHEN SPRACHE wie die Frage (Deutsch → Deutsch)
2. Verwende Quellenverweise [1], [2] im Text
3. Gib NUR die Antwort zurück, keine Einleitungen oder Erklärungen
4. Wenn die Quellen KEINE klare, sichere Antwort ermöglichen: \
"Nicht genügend belastbare Belege im Korpus gefunden." Lieber keine Antwort als eine unsichere.

Konfidenz-Bewertung (für deine interne Einschätzung):
- high: 3+ starke Belege, klare Übereinstimmung
- medium: 2 Belege oder teilweise Übereinstimmung
- low: Schwache Belege oder Unsicherheit → dann lieber keine Antwort geben

Bei nur einem Beleg: Antworte trotzdem, aber sei vorsichtig mit Aussagen.
"""


def stream_answer(
    query: str,
    context: dict[str, Any],
    complexity: float = 1.0,
    history: list[dict] | None = None,
    llm_model: str | None = None,
):
    """Stream the answer generation, yielding text chunks.

    For streaming, we use plain text output (not JSON) for better UX.
    Sources are pre-computed from the context.

    Args:
        query: User query
        context: Packed context from pack_context()
        complexity: Query complexity score for dynamic sizing
        history: Previous chat messages for context
        llm_model: LLM mode - "instruct", "reasoning", or None (default)

    Yields:
        dict with either 'chunk' (text fragment) or 'sources' (list of sources)
    """
    # Get dynamic limits based on complexity
    limits = get_effective_limits(complexity)

    # Resolve LLM profile
    profile = get_llm_profile(llm_model)

    # First, yield the sources so the UI can display them
    windows = context.get("windows", [])[:limits.get("evidence_max_windows", 4)]
    sources = [
        {
            "index": w.get("source_index", i + 1),
            "doc_id": w.get("doc_id", ""),
            "title": w.get("title", "Unbekannt"),
            "location": w.get("location", ""),
            "snippet": w.get("text", "")[:200],
            "uri": w.get("download_url"),
            "download_url": w.get("download_url"),
            "source_type": w.get("source_type"),
        }
        for i, w in enumerate(windows)
    ]
    yield {"type": "sources", "sources": sources}

    # Format context as plain text
    user = _format_context_as_text(query, context, limits)

    # Prepend chat history if provided
    if history:
        history_text = "\n\n--- Bisheriger Gesprächsverlauf ---\n"
        for msg in history:
            role_label = "Nutzer" if msg.get("role") == "user" else "Assistent"
            history_text += f"{role_label}: {msg.get('content', '')}\n"
        history_text += "--- Ende des Gesprächsverlaufs ---\n\n"
        user = history_text + user

    # Stream the answer
    max_tokens = limits.get("max_answer_tokens", settings.LLM_MAX_ANSWER_TOKENS)
    for chunk in chat_stream(
        system=_STREAM_SYSTEM,
        user=user,
        temperature=0.0,
        timeout_s=120,
        max_tokens=max_tokens,
        model=profile.model,
        think=profile.think,
    ):
        if chunk["type"] == "reasoning":
            yield {"type": "thinking", "chunk": chunk["content"]}
        else:
            yield {"type": "chunk", "chunk": chunk["content"]}

    # Signal completion
    yield {"type": "done"}
