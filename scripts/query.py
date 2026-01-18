from __future__ import annotations

import argparse

from enterprise_rag.retrieval.hybrid import retrieve
from enterprise_rag.retrieval.complexity import analyze_complexity, get_complexity_label
from enterprise_rag.reasoning.pack import pack_context
from enterprise_rag.reasoning.evidence import extract_and_answer


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--q", required=True)
    ap.add_argument("--k", type=int, default=8)
    ap.add_argument("--timing", action="store_true", help="Show timing breakdown")
    args = ap.parse_args()

    result = retrieve(args.q, debug_timing=args.timing)
    hits = result["hits"][: args.k]
    plan = result.get("plan")
    timings = result.get("timings", {})

    # Analyze query complexity for dynamic context sizing
    complexity = analyze_complexity(args.q, plan)
    complexity_label = get_complexity_label(complexity)

    ctx = pack_context(args.q, hits, [])
    ans = extract_and_answer(args.q, ctx, complexity=complexity)

    print("PLAN:", plan)
    print("COMPLEXITY:", f"{complexity:.2f} ({complexity_label})")
    print("HITS:", len(hits))
    print()
    print("=" * 60)
    print("ANSWER:")
    print(ans.get("answer"))
    print()
    print("-" * 60)
    print("SOURCES:")
    for s in ans.get("sources", []):
        idx = s.get("index", "?")
        title = s.get("title", "Unbekannt")
        location = s.get("location", "")
        snippet = s.get("snippet", "")[:100]
        print(f"  [{idx}] {title} ({location})")
        if snippet:
            print(f"      \"{snippet}...\"")
    print()
    print("CONFIDENCE:", ans.get("confidence"))

    if args.timing and timings:
        print()
        print("-" * 60)
        print("RETRIEVAL TIMING:")
        for step, duration in timings.items():
            print(f"  {step}: {duration:.2f}s")
        print(f"  TOTAL retrieval: {sum(timings.values()):.2f}s")


if __name__ == "__main__":
    main()
