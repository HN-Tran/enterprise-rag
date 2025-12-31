"""FastAPI service."""

from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from app.log import setup_logging
from app.ingestion.ingest import ingest_path
from app.retrieval.hybrid import retrieve
from app.db import get_conn
from app.config import settings
from app.neo4j_amp import Neo4jAmp
from app.reasoning.pack import pack_context
from app.reasoning.evidence import extract_and_answer


app = FastAPI(title="Enterprise RAG (Postgres + pgvector, optional Neo4j)")


class IngestRequest(BaseModel):
    path: str


class SearchRequest(BaseModel):
    query: str
    k: int = 8


@app.on_event("startup")
def _startup() -> None:
    setup_logging()


@app.post("/ingest")
def ingest(req: IngestRequest) -> dict:
    return ingest_path(req.path)


@app.post("/search")
def search(req: SearchRequest) -> dict:
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
    answer = extract_and_answer(req.query, ctx)

    return {"query": req.query, "plan": result["plan"], "hits": hits, "answer": answer}
