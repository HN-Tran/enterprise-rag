"""Hybrid retrieval orchestration: plan -> candidates -> union -> rerank -> diversify."""

from __future__ import annotations

from typing import Any

from app.config import settings
from app.db import get_conn
from app.retrieval.postgres_retrieval import bm25_candidates, vector_candidates
from app.retrieval.query_plan import plan_query
from app.retrieval.rerank import rerank_windows
from app.retrieval.citation_expand import expand_with_citations


def _hydrate_docs(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    doc_ids = sorted({r["doc_id"] for r in rows})
    if not doc_ids:
        return rows
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT doc_id, title, uri, category, categories FROM documents WHERE doc_id = ANY(%s)",
                (doc_ids,),
            )
            dmap = {r["doc_id"]: r for r in cur.fetchall()}

    out = []
    for r in rows:
        d = dmap.get(r["doc_id"], {})
        r2 = dict(r)
        r2["title"] = d.get("title")
        r2["uri"] = d.get("uri")
        r2["category"] = d.get("category")
        r2["categories"] = d.get("categories") or []
        out.append(r2)
    return out


def _union_candidates(bm: list[dict[str, Any]], vc: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[int, dict[str, Any]] = {}
    for r in bm:
        wid = int(r["window_id"])
        merged.setdefault(wid, dict(r))
        merged[wid]["bm25"] = float(r["score"] or 0.0)
    for r in vc:
        wid = int(r["window_id"])
        merged.setdefault(wid, dict(r))
        merged[wid]["vec"] = float(r["score"] or 0.0)

    items = list(merged.values())
    for it in items:
        it.setdefault("bm25", 0.0)
        it.setdefault("vec", 0.0)
        it["blend"] = 0.55 * it["vec"] + 0.45 * it["bm25"]
    items.sort(key=lambda x: x["blend"], reverse=True)
    return items


def _diversify(rows: list[dict[str, Any]], max_per_doc: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for r in rows:
        did = r["doc_id"]
        c = counts.get(did, 0)
        if c < max_per_doc:
            out.append(r)
            counts[did] = c + 1
    return out


def retrieve(query: str, expand_citations: bool = True) -> dict[str, Any]:
    plan = plan_query(query)
    rewrites: list[str] = plan.get("rewrites", [query])
    bm25_q: str = plan.get("bm25_query", query)
    cats: list[str] = plan.get("categories", [])

    # Candidate generation across rewrites:
    bm_all: list[dict[str, Any]] = []
    vc_all: list[dict[str, Any]] = []

    for rq in rewrites[:6]:
        bm_all.extend(bm25_candidates(rq, cats, settings.CANDIDATES_BM25))
        vc_all.extend(vector_candidates(rq, settings.CANDIDATES_VEC))

    merged = _union_candidates(bm_all, vc_all)

    # Rerank top pool
    pool = merged[: max(settings.RERANK_KEEP * 10, 80)]
    reranked = rerank_windows(query, pool)[: settings.RERANK_KEEP]

    reranked = _hydrate_docs(reranked)
    reranked = _diversify(reranked, settings.MAX_PER_DOC)

    # Expand with citation chain context
    cited_context: list[dict[str, Any]] = []
    if expand_citations and settings.USE_NEO4J:
        hit_doc_ids = [h["doc_id"] for h in reranked]
        cited_context = expand_with_citations(
            hit_doc_ids,
            max_depth=getattr(settings, "CITATION_EXPAND_DEPTH", 2),
            max_cited=getattr(settings, "CITATION_MAX_DOCS", 4),
        )

    return {
        "query": query,
        "plan": plan,
        "hits": reranked,
        "cited_context": cited_context,
    }
