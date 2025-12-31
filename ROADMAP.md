# Enterprise RAG Roadmap

**Vision:** Perplexity-style document intelligence for enterprise - finding the right information with precise source attribution across a growing document corpus.

---

## Phase 1: Source Attribution (High Impact, Low Effort) ✅ COMPLETE

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

## Phase 4: Operational Improvements

### 4.1 Performance
- [ ] Add Redis for query/embedding caching
- [ ] Implement connection pooling (pgbouncer)
- [ ] Skip query planning for simple queries
- [ ] Optimize reranking batch sizes

### 4.2 Ingestion
- [ ] Add async job queue (Celery/RQ) for ingestion
- [ ] Background entity extraction
- [ ] Incremental index updates
- [ ] Document update detection (hash-based)

### 4.3 Observability
- [ ] Set up structured logging
- [ ] Add OpenTelemetry tracing
- [ ] Create monitoring dashboards
- [ ] Alerting for quality degradation

---

## Phase 5: Scale Optimization (When Needed)

### 5.1 Database Scaling
- [ ] Evaluate dedicated vector DB at 50M+ vectors
- [ ] Implement read replicas for PostgreSQL
- [ ] Optimize HNSW index parameters
- [ ] Tiered storage (hot/warm/cold)

### 5.2 Advanced Features
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
| Phase 4: Operational Improvements | Medium | Medium | As Needed |
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
