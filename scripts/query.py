from __future__ import annotations

import argparse

from enterprise_rag.retrieval.hybrid import retrieve
from enterprise_rag.reasoning.pack import pack_context
from enterprise_rag.reasoning.evidence import extract_and_answer


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--q", required=True)
    ap.add_argument("--k", type=int, default=8)
    args = ap.parse_args()

    result = retrieve(args.q)
    hits = result["hits"][: args.k]
    ctx = pack_context(args.q, hits, [])
    ans = extract_and_answer(args.q, ctx)

    print("PLAN:", result["plan"])
    print("HITS:", len(hits))
    print("ANSWER:", ans.get("final_answer"))
    if ans.get("evidence"):
        print("EVIDENCE COUNT:", len(ans["evidence"]))


if __name__ == "__main__":
    main()
