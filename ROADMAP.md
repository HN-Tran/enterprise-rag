# Enterprise RAG Roadmap

**Vision:** Perplexity-style document intelligence for enterprise - finding the right information with precise source attribution across a growing document corpus.

---

## Phase 1: Source Attribution (High Impact, Low Effort) ✅ COMPLETE

### Benefits
- **Trustworthy answers**: Users can verify claims against original sources
- **Precise citations**: Page/section references enable quick fact-checking
- **Confidence transparency**: Users know when evidence is strong vs. weak
- **Quality measurement**: Evaluation framework tracks retrieval accuracy

### 1.1 Citation-Aware Responses ✅
- [x] Add citation indices `[1]`, `[2]` to answer generation
- [x] Include page/section location in source references
- [x] Add confidence scoring per source
- [x] Format response with clear source list

### 1.2 Response Quality ✅
- [x] Improve answer formatting with structured output
- [x] Add "Related Documents" section to responses
- [x] Implement confidence thresholds (high/medium/low)
- [x] Better handling of "insufficient evidence" cases

### 1.3 Evaluation Framework ✅
- [x] Build evaluation harness (precision/recall metrics)
- [x] Add retrieval quality benchmarks
- [x] Create regression test suite
- [x] Track citation accuracy metrics

---

## Phase 2: Entity Extraction (Deferred - Pending Data Analysis)

**Status:** On hold until corpus analysis determines if entity extraction adds value.

**Rationale:**
- Hybrid search (BM25 + vector) may already handle synonym matching via embeddings
- GIGO principle - need to verify corpus has extractable entities worth indexing
- Manual dictionary approach doesn't scale

### 2.1 Prerequisites (Do First)
- [ ] Analyze corpus for entity distribution
- [ ] Measure baseline retrieval quality without entities
- [ ] Identify high-value entity types for the domain

### 2.2 Recommended Approach: LangExtract
Tool: [google/langextract](https://github.com/google/langextract)

Why LangExtract over SpaCy:
- LLM-based extraction understands context
- Source grounding maps entities to exact text positions
- No language-specific model needed
- Handles long documents with chunking

### 2.3 Implementation (If Justified)
- [ ] Define entity schemas with few-shot examples
- [ ] Extract during ingestion with source positions
- [ ] Store in Neo4j with `MENTIONED_IN` edges
- [ ] Query expansion using extracted entities

---

## Phase 3: Citation Chain Traversal (Medium Impact, Medium Effort) ✅ COMPLETE

### Benefits
- **Cross-document discovery**: Find related documents through citation networks
- **Authoritative sourcing**: Trace claims back to original standards/regulations
- **Context enrichment**: Include cited documents in answer generation
- **"via Zitat" transparency**: Users see when info comes from referenced sources

### 3.1 Citation Extraction ✅
- [x] Extract URLs from PDF text and embedded hyperlinks (PyMuPDF)
- [x] Parse German references: "siehe", "gemäß", "laut" patterns
- [x] Parse standards references (ISO, DIN, DSGVO)
- [x] Store in PostgreSQL `citations` table

### 3.2 Citation Resolution ✅
- [x] Match URLs to existing document URIs
- [x] Fuzzy title matching for internal references
- [x] Create `CITES` edges in Neo4j for resolved citations
- [x] Graph traversal methods (get_citations_from, get_cited_by)

### 3.3 Retrieval Integration ✅
- [x] Citation chain expansion in retrieval pipeline
- [x] Include cited documents in context packing
- [x] LLM prompt updated for citation chain awareness
- [x] "via Zitat" annotation for transitive citations

### 3.4 Future Enhancements (Not Implemented)
- [ ] External URL fetching and ingestion
- [ ] Document versioning/supersession tracking
- [ ] "See Also" recommendations via similarity
- [ ] Contradiction detection across sources

---

## Phase 4: Operational Improvements ✅ COMPLETE

### Benefits
- **Faster queries**: Redis caching reduces repeat query latency by 90%+
- **Stable under load**: Connection pooling prevents database exhaustion
- **Non-blocking ingestion**: Async job queue allows API to stay responsive
- **Production visibility**: Structured logs + distributed tracing for debugging
- **Health monitoring**: Readiness checks for load balancer integration

### 4.1 Performance ✅
- [x] Add Redis for query/embedding caching (`enterprise_rag/cache.py`)
- [x] Implement connection pooling (psycopg_pool in `enterprise_rag/db.py`)
- [x] Skip query planning for simple queries (`enterprise_rag/retrieval/query_plan.py`)
- [x] Cache query plans and embeddings

### 4.2 Ingestion ✅
- [x] Add async job queue (RQ) for ingestion (`enterprise_rag/tasks/`)
- [x] Background embedding workers (`enterprise_rag/tasks/embeddings.py`)
- [x] Document update detection (hash-based in `enterprise_rag/ingestion/ingest.py`)
- [x] Job status tracking via `/ingest/{job_id}` endpoint

### 4.3 Observability ✅
- [x] Set up structured logging (structlog in `enterprise_rag/log.py`)
- [x] Add OpenTelemetry tracing with Jaeger (`enterprise_rag/telemetry.py`)
- [x] Health endpoints (`/health`, `/health/ready`, `/health/cache`)
- [ ] Create monitoring dashboards (external - Grafana)
- [ ] Alerting for quality degradation (external - Alertmanager)

### 4.4 User Experience ✅
- [x] Streaming responses via Server-Sent Events (`/search/stream`)
- [x] Model profiles (small/medium/large) for different LLM capabilities
- [x] Dynamic context sizing based on query complexity
- [x] TEI cross-encoder reranking (bge-reranker-v2-m3) for fast, accurate reranking

---

## Phase 5: Scale Optimization (When Needed)

### 5.1 Database Scaling
- [ ] Evaluate dedicated vector DB at 50M+ vectors
- [ ] Implement read replicas for PostgreSQL
- [ ] Optimize HNSW index parameters
- [ ] Tiered storage (hot/warm/cold)

### 5.2 Crawler Optimizations
- [x] HTTP conditional requests (ETag/Last-Modified) to skip unchanged files
- [ ] HEAD request prefetch to populate caching headers without downloading
  - Trade-off: Trusts server's ETag/Last-Modified instead of verifying SHA256
  - Use case: Prime cache for existing documents without full re-download
- [ ] Parallel downloads (currently sequential)
- [ ] Resume interrupted crawls

### 5.3 Advanced Features
- [ ] Dynamic blend ratio per query type
- [ ] Conversational context tracking
- [ ] Multi-modal support (tables, images)
- [ ] Contradiction detection across sources

---

## Priority Matrix

| Phase | Impact | Effort | Priority |
|-------|--------|--------|----------|
| Phase 1: Source Attribution | High | Low | ✅ Complete |
| Phase 2: Entity Extraction | Unknown | Medium | Deferred (needs data analysis) |
| Phase 3: Citation Chain Traversal | Medium | Medium | ✅ Complete |
| Phase 4: Operational Improvements | Medium | Medium | ✅ Complete |
| Phase 5: Scale Optimization | Low (until needed) | High | When Required |

---

## Success Metrics

### Retrieval Quality
- Precision@10 > 0.8
- Recall@100 > 0.9
- MRR (Mean Reciprocal Rank) > 0.7
- Citation accuracy > 95%

### User Experience
- P95 query latency < 3s
- Answer confidence correlation with accuracy
- Source coverage in answers > 80%

### Corpus Growth
- Support 100K → 1M documents
- Ingestion throughput > 100 docs/hour
- Incremental updates without full reindex

---

## Related Documents

- `ARCHITECTURE_REVIEW.md` - Current system assessment and scaling limits
- `KNOWLEDGE_GRAPH_DESIGN.md` - Detailed Neo4j schema for cross-document intelligence
- `ENTERPRISE_RAG_SCALE.md` - Full vision for Perplexity-style enterprise RAG
