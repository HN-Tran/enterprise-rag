"""FastAPI service with Perplexity-style responses."""

from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel, Field

from enterprise_rag.log import setup_logging
from enterprise_rag.ingestion.ingest import ingest_path
from enterprise_rag.retrieval.hybrid import retrieve
from enterprise_rag.db import get_conn, init_pool, close_pool
from enterprise_rag.cache import init_cache, close_cache, is_cache_available, get_cache_stats
from enterprise_rag.telemetry import setup_telemetry, shutdown_telemetry
from enterprise_rag.tasks import init_queues
from enterprise_rag.tasks.ingestion import enqueue_ingest, get_job_status
from enterprise_rag.config import settings
from enterprise_rag.neo4j_amp import Neo4jAmp
from enterprise_rag.reasoning.pack import pack_context
from enterprise_rag.reasoning.evidence import extract_and_answer


app = FastAPI(
    title="Enterprise RAG",
    description="Perplexity-style document intelligence for enterprise",
    version="0.2.0",
)


class IngestRequest(BaseModel):
    path: str


class SearchRequest(BaseModel):
    query: str
    k: int = Field(default=8, description="Number of sources to retrieve")


# Response models for structured output


class SourceResponse(BaseModel):
    """A cited source with location and confidence."""
    index: int = Field(description="Citation index [1], [2], etc.")
    doc_id: str
    title: str
    location: str = Field(description="Page/section location, e.g., 'Seite 12-14'")
    snippet: str = Field(description="Relevant quote from source")
    confidence: float = Field(ge=0.0, le=1.0, description="Source confidence score")
    uri: str | None = None


class RelatedDocument(BaseModel):
    """A document related to the query but not directly cited."""
    doc_id: str
    title: str
    location: str
    relevance: str = Field(description="Why this document may be relevant")


class AnswerResponse(BaseModel):
    """Perplexity-style answer with citations."""
    answer: str = Field(description="Answer text with [1], [2] inline citations")
    confidence: str = Field(description="Overall confidence: high, medium, or low")
    sources: list[SourceResponse] = Field(default_factory=list)
    related_documents: list[RelatedDocument] = Field(default_factory=list)
    evidence_count: int = 0
    insufficient_evidence: bool = False


class SearchResponse(BaseModel):
    """Full search response."""
    query: str
    answer: AnswerResponse
    retrieval_info: dict = Field(default_factory=dict, description="Query plan and retrieval metadata")


@app.on_event("startup")
def _startup() -> None:
    setup_logging()
    init_pool()
    init_cache()
    init_queues()
    setup_telemetry(app)


@app.on_event("shutdown")
def _shutdown() -> None:
    shutdown_telemetry()
    close_cache()
    close_pool()


# --- Health endpoints ---


def _check_postgres() -> str:
    """Check PostgreSQL connectivity."""
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        return "ok"
    except Exception as e:
        return f"error: {e}"


def _check_redis() -> str:
    """Check Redis connectivity."""
    if not is_cache_available():
        return "disabled"
    try:
        stats = get_cache_stats()
        return "ok" if stats.get("enabled") else "disabled"
    except Exception as e:
        return f"error: {e}"


def _check_neo4j() -> str:
    """Check Neo4j connectivity."""
    if not settings.USE_NEO4J:
        return "disabled"
    try:
        amp = Neo4jAmp.create()
        amp.close()
        return "ok"
    except Exception as e:
        return f"error: {e}"


@app.get("/health")
def health() -> dict:
    """Basic health check - returns ok if API is running."""
    return {"status": "ok"}


@app.get("/health/ready")
def readiness() -> dict:
    """Readiness check - verifies all dependencies are accessible."""
    checks = {
        "postgres": _check_postgres(),
        "redis": _check_redis(),
        "neo4j": _check_neo4j(),
    }
    all_ok = all(v == "ok" or v == "disabled" for v in checks.values())
    return {
        "status": "ok" if all_ok else "degraded",
        "checks": checks,
    }


@app.get("/health/cache")
def cache_stats() -> dict:
    """Cache statistics for monitoring."""
    return get_cache_stats()


@app.post("/ingest")
def ingest(req: IngestRequest) -> dict:
    """Ingest a document.

    If ASYNC_INGEST is enabled and Redis is available, the ingestion
    runs in the background and returns a job_id for status tracking.
    Otherwise, runs synchronously.
    """
    if settings.ASYNC_INGEST:
        return enqueue_ingest(req.path)
    return ingest_path(req.path)


@app.get("/ingest/{job_id}")
def ingest_status(job_id: str) -> dict:
    """Get the status of an ingestion job."""
    return get_job_status(job_id)


@app.post("/search", response_model=SearchResponse)
def search(req: SearchRequest) -> SearchResponse:
    result = retrieve(req.query)
    hits = result["hits"][: req.k]

    # Optional Neo4j anchor expansion for top hits
    anchors: list[dict] = []
    if settings.USE_NEO4J and hits:
        amp = Neo4jAmp.create()
        amp.ensure_schema()
        anchor_ids: list[int] = []
        for h in hits[: min(6, len(hits))]:
            anchor_ids.extend(amp.expand_anchor_ids(h["doc_id"], h["page_start"], h["page_end"]))
        amp.close()

        anchor_ids = sorted(set(anchor_ids))
        if anchor_ids:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT anchor_id, doc_id, page_no, anchor_type, text FROM anchors WHERE anchor_id = ANY(%s)",
                        (anchor_ids,),
                    )
                    anchors = cur.fetchall()

    ctx = pack_context(req.query, hits, anchors)
    answer_raw = extract_and_answer(req.query, ctx)

    # Build cited sources from answer
    sources = [
        SourceResponse(
            index=s.get("index", i + 1),
            doc_id=s.get("doc_id", ""),
            title=s.get("title", "Unbekannt"),
            location=s.get("location", ""),
            snippet=s.get("snippet", ""),
            confidence=s.get("confidence", 0.0),
            uri=s.get("uri"),
        )
        for i, s in enumerate(answer_raw.get("sources", []))
    ]

    # Find related documents (hits not used as primary sources)
    cited_doc_ids = {s.doc_id for s in sources}
    related_documents = []
    for h in hits:
        if h["doc_id"] not in cited_doc_ids:
            page_start = h["page_start"]
            page_end = h["page_end"]
            location = f"Seite {page_start}" if page_start == page_end else f"Seite {page_start}-{page_end}"
            related_documents.append(
                RelatedDocument(
                    doc_id=h["doc_id"],
                    title=h.get("title") or "Unbekannt",
                    location=location,
                    relevance="Gefunden durch Ähnlichkeitssuche",
                )
            )
            if len(related_documents) >= 3:  # Limit to 3 related docs
                break

    # Build structured response
    answer_response = AnswerResponse(
        answer=answer_raw.get("answer", ""),
        confidence=answer_raw.get("confidence", "low"),
        sources=sources,
        related_documents=related_documents,
        evidence_count=answer_raw.get("evidence_count", 0),
        insufficient_evidence=answer_raw.get("insufficient_evidence", False),
    )

    return SearchResponse(
        query=req.query,
        answer=answer_response,
        retrieval_info={
            "plan": result.get("plan"),
            "total_hits": len(result.get("hits", [])),
            "sources_used": len(sources),
        },
    )
