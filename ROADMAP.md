# Enterprise RAG Roadmap

**Vision:** Perplexity-style document intelligence for enterprise - finding the right information with precise source attribution across a growing document corpus.

---

## Phase 1: Source Attribution (High Impact, Low Effort)

### 1.1 Citation-Aware Responses
- [ ] Add citation indices `[1]`, `[2]` to answer generation
- [ ] Include page/section location in source references
- [ ] Add confidence scoring per source
- [ ] Format response with clear source list

### 1.2 Response Quality
- [ ] Improve answer formatting with structured output
- [ ] Add "Related Documents" section to responses
- [ ] Implement confidence thresholds (high/medium/low)
- [ ] Better handling of "insufficient evidence" cases

### 1.3 Evaluation Framework
- [ ] Build evaluation harness (precision/recall metrics)
- [ ] Add retrieval quality benchmarks
- [ ] Create regression test suite
- [ ] Track citation accuracy metrics

---

## Phase 2: Entity-Aware Retrieval (High Impact, Medium Effort)

### 2.1 Entity Extraction
- [ ] Integrate SpaCy German NER (de_core_news_lg)
- [ ] Extract entities during ingestion (PERSON, ORG, CONCEPT, REGULATION)
- [ ] Build `MENTIONED_IN` edges in Neo4j
- [ ] Enable entity-based document discovery

### 2.2 Query Understanding
- [ ] Extract entities from user queries
- [ ] Map synonyms to canonical forms (GDPR ↔ DSGVO)
- [ ] Query expansion using related entities
- [ ] Intent classification (factual, procedural, exploratory)

### 2.3 Entity Resolution
- [ ] Implement fuzzy matching for entity deduplication
- [ ] Build `SAME_AS` edges for cross-document entities
- [ ] Create canonical entity names
- [ ] Handle entity aliases and abbreviations

---

## Phase 3: Cross-Document Intelligence (Medium Impact, High Effort)

### 3.1 Citation Parsing
- [ ] Build citation regex patterns for German documents
- [ ] Parse standards references (ISO, DIN, DSGVO, internal docs)
- [ ] Create `CITES` and `REFERENCES` edges
- [ ] Implement reference resolution to existing documents

### 3.2 Document Relationships
- [ ] Track document supersession (versioning)
- [ ] Build `RELATED_TO` edges via similarity
- [ ] Enable citation chain traversal
- [ ] "See Also" recommendations in responses

### 3.3 Retrieval Integration
- [ ] Graph expansion in retrieval pipeline
- [ ] Multi-source retrieval (hybrid + entity + graph)
- [ ] Result fusion and deduplication
- [ ] Citation trail generation for transparency

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
| Phase 1: Source Attribution | High | Low | **Do First** |
| Phase 2: Entity-Aware Retrieval | High | Medium | **Do Next** |
| Phase 3: Cross-Document Intelligence | Medium | High | Plan Carefully |
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
