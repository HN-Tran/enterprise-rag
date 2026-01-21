"""Hybrid retrieval orchestration: plan -> candidates -> union -> rerank -> diversify."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from enterprise_rag.config import settings
from enterprise_rag.db import get_conn
from enterprise_rag.llm import embed_texts
from enterprise_rag.retrieval.postgres_retrieval import bm25_candidates, vector_candidates
from enterprise_rag.retrieval.query_plan import plan_query
from enterprise_rag.retrieval.rerank import rerank_windows
from enterprise_rag.retrieval.citation_expand import expand_with_citations


def _hydrate_docs(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    doc_ids = sorted({r["doc_id"] for r in rows})
    if not doc_ids:
        return rows
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT doc_id, title, download_url, category, categories FROM documents WHERE doc_id = ANY(%s)",
                (doc_ids,),
            )
            dmap = {r["doc_id"]: r for r in cur.fetchall()}

    out = []
    for r in rows:
        d = dmap.get(r["doc_id"], {})
        r2 = dict(r)
        r2["title"] = d.get("title")
        r2["download_url"] = d.get("download_url")
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


def retrieve(
    query: str,
    expand_citations: bool = True,
    debug_timing: bool = False,
    include_archived: bool = False,
) -> dict[str, Any]:
    timings: dict[str, float] = {}

    # Query planning (can be skipped for faster retrieval)
    t0 = time.perf_counter()
    skip_planning = settings.SKIP_QUERY_PLANNING
    if debug_timing:
        print(f"[DEBUG] skip_planning={skip_planning}")
    if skip_planning:
        plan = {"rewrites": [query], "bm25_query": query, "categories": [], "acronyms": {}}
    else:
        plan = plan_query(query)
    timings["plan_query"] = time.perf_counter() - t0

    rewrites: list[str] = plan.get("rewrites", [query])
    bm25_q: str = plan.get("bm25_query", query)
    cats: list[str] = plan.get("categories", [])

    # Limit rewrites
    rewrites = rewrites[:settings.MAX_QUERY_REWRITES]
    if debug_timing:
        print(f"[DEBUG] rewrites={len(rewrites)}, plan had {len(plan.get('rewrites', []))}")

    # Batch embed all rewrites at once (single API call instead of N calls)
    t0 = time.perf_counter()
    embeddings = embed_texts(rewrites)
    timings["embed_texts"] = time.perf_counter() - t0

    # Parallel candidate generation using ThreadPoolExecutor
    bm_all: list[dict[str, Any]] = []
    vc_all: list[dict[str, Any]] = []

    # Use setting default for include_archived if not explicitly passed
    if not include_archived:
        include_archived = settings.INCLUDE_ARCHIVED_BY_DEFAULT

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=len(rewrites) * 2) as executor:
        # Submit all BM25 and vector searches in parallel
        bm25_futures = {
            executor.submit(
                bm25_candidates, rq, cats, settings.CANDIDATES_BM25, include_archived
            ): ("bm25", rq)
            for rq in rewrites
        }
        vec_futures = {
            executor.submit(
                vector_candidates, rq, settings.CANDIDATES_VEC, emb, include_archived
            ): ("vec", rq)
            for rq, emb in zip(rewrites, embeddings)
        }

        # Collect results as they complete
        for future in as_completed(list(bm25_futures.keys()) + list(vec_futures.keys())):
            if future in bm25_futures:
                bm_all.extend(future.result())
            else:
                vc_all.extend(future.result())
    timings["parallel_search"] = time.perf_counter() - t0

    merged = _union_candidates(bm_all, vc_all)

    # Rerank top pool - limit to avoid payload size issues with reranker
    # TEI has max_batch_tokens=16384, so keep pool small
    t0 = time.perf_counter()
    pool = merged[: min(settings.RERANK_KEEP * 2, 30)]
    reranked = rerank_windows(query, pool)[: settings.RERANK_KEEP]
    timings["rerank"] = time.perf_counter() - t0

    reranked = _hydrate_docs(reranked)
    reranked = _diversify(reranked, settings.MAX_PER_DOC)

    # Expand with citation chain context
    cited_context: list[dict[str, Any]] = []
    t0 = time.perf_counter()
    if expand_citations and settings.USE_NEO4J:
        hit_doc_ids = [h["doc_id"] for h in reranked]
        cited_context = expand_with_citations(
            hit_doc_ids,
            max_depth=getattr(settings, "CITATION_EXPAND_DEPTH", 2),
            max_cited=getattr(settings, "CITATION_MAX_DOCS", 4),
        )
    timings["citation_expand"] = time.perf_counter() - t0

    if debug_timing:
        print(f"[TIMING] plan_query: {timings['plan_query']:.2f}s")
        print(f"[TIMING] embed_texts: {timings['embed_texts']:.2f}s")
        print(f"[TIMING] parallel_search: {timings['parallel_search']:.2f}s")
        print(f"[TIMING] rerank: {timings['rerank']:.2f}s")
        print(f"[TIMING] citation_expand: {timings['citation_expand']:.2f}s")
        print(f"[TIMING] TOTAL: {sum(timings.values()):.2f}s")

    return {
        "query": query,
        "plan": plan,
        "hits": reranked,
        "cited_context": cited_context,
        "timings": timings,
    }
