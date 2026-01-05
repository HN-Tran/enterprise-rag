"""Query complexity analysis for dynamic context sizing."""

from __future__ import annotations

import re


def analyze_complexity(query: str, plan: dict | None = None) -> float:
    """Analyze query complexity and return a multiplier (0.5 - 1.5+).

    Factors considered:
    - Query length and structure
    - Comparison keywords (vs, compared to, difference)
    - Multiple entities or time periods
    - Aggregation requests (total, sum, average)
    - Question complexity indicators

    Args:
        query: The user's query
        plan: Optional query plan with rewrites and categories

    Returns:
        Complexity score: 0.5 (simple) to 1.5+ (complex)
    """
    score = 1.0
    query_lower = query.lower()

    # Length factor - longer queries often need more context
    word_count = len(query.split())
    if word_count <= 5:
        score -= 0.2  # Simple, short query
    elif word_count >= 15:
        score += 0.2  # Detailed query

    # Comparison indicators - need multiple sources
    comparison_patterns = [
        r"\bvs\.?\b",
        r"\bversus\b",
        r"\bim vergleich\b",
        r"\bverglichen\b",
        r"\bunterschied\b",
        r"\bdifferenz\b",
        r"\bgegenüber\b",
        r"\bcompared\b",
        r"\bdifference\b",
    ]
    for pattern in comparison_patterns:
        if re.search(pattern, query_lower):
            score += 0.3
            break

    # Multiple time periods - need temporal context
    year_matches = re.findall(r"\b20\d{2}\b", query)
    if len(year_matches) >= 2:
        score += 0.25

    # Aggregation requests - need comprehensive data
    aggregation_patterns = [
        r"\bgesamt\b",
        r"\bsumme\b",
        r"\bdurchschnitt\b",
        r"\bmittelwert\b",
        r"\btotal\b",
        r"\ball[e]?\b",
        r"\bübersicht\b",
        r"\bzusammenfassung\b",
    ]
    for pattern in aggregation_patterns:
        if re.search(pattern, query_lower):
            score += 0.15
            break

    # Multi-part questions (und, sowie, außerdem)
    multi_part_patterns = [
        r"\bund\b.*\?",
        r"\bsowie\b",
        r"\baußerdem\b",
        r"\bzusätzlich\b",
        r"\bwelche.*und.*welche\b",
    ]
    for pattern in multi_part_patterns:
        if re.search(pattern, query_lower):
            score += 0.2
            break

    # "Why" and "How" questions - need explanatory context
    if re.match(r"^(warum|wieso|weshalb|why|how|wie)\b", query_lower):
        score += 0.15

    # List requests - need multiple items
    list_patterns = [
        r"\bliste\b",
        r"\baufzählung\b",
        r"\bnenne\b.*\balle\b",
        r"\bwelche\b.*\bgibt es\b",
    ]
    for pattern in list_patterns:
        if re.search(pattern, query_lower):
            score += 0.2
            break

    # Use query plan info if available
    if plan:
        # More rewrites suggest complex query
        rewrites = plan.get("rewrites", [])
        if len(rewrites) >= 4:
            score += 0.1

        # Multiple categories suggest cross-domain query
        categories = plan.get("categories", [])
        if len(categories) >= 2:
            score += 0.15

    # Clamp to reasonable range
    return max(0.5, min(2.0, score))


def get_complexity_label(score: float) -> str:
    """Get human-readable complexity label."""
    if score <= 0.7:
        return "simple"
    elif score <= 1.1:
        return "normal"
    elif score <= 1.4:
        return "complex"
    else:
        return "very_complex"
