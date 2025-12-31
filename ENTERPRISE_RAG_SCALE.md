# Enterprise RAG at Scale: Perplexity-Style Document Intelligence

Focus: **Finding the right information with accurate source attribution across a growing enterprise document corpus.**

Not multi-tenant SaaS. Not user scaling. **Document corpus scaling with retrieval quality.**

## Core Value Proposition

```
User Query
    ↓
┌─────────────────────────────────────────────────────┐
│  "What are our compliance requirements for         │
│   handling customer PII under GDPR?"               │
└─────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────┐
│  ANSWER with SOURCES (Perplexity-style)            │
│                                                     │
│  Based on your internal documentation:             │
│                                                     │
│  Customer PII under GDPR must be...                │
│  [detailed answer synthesized from multiple docs]  │
│                                                     │
│  ─────────────────────────────────────────────────  │
│  Sources:                                          │
│  [1] GDPR_Compliance_Policy_2024.pdf (p.12-14)    │
│      "Personal data must be processed lawfully..." │
│      Confidence: 95%                               │
│                                                     │
│  [2] Data_Handling_Procedures.docx (§3.2)         │
│      "PII retention period shall not exceed..."    │
│      Confidence: 91%                               │
│                                                     │
│  [3] IT_Security_Guidelines.pdf (p.45)            │
│      "Encryption requirements for PII storage..."  │
│      Confidence: 87%                               │
│                                                     │
│  Related Documents:                                │
│  → Privacy_Impact_Assessment_Template.xlsx         │
│  → Employee_Training_GDPR.pptx                     │
└─────────────────────────────────────────────────────┘
```

## What Makes This Different from Basic RAG

| Basic RAG | Enterprise RAG (Perplexity-style) |
|-----------|-----------------------------------|
| Return top-k chunks | Synthesize answer from multiple sources |
| No source linking | Precise citations with page/section |
| Single retrieval pass | Multi-stage retrieval + graph expansion |
| Keyword/vector only | Hybrid + entity + relationship traversal |
| Flat document store | Structured knowledge with cross-references |
| "Here's what I found" | "Here's the answer, here's the evidence" |

## Architecture for Scale + Quality

```
                         ┌─────────────────┐
                         │   User Query    │
                         └────────┬────────┘
                                  │
                    ┌─────────────▼─────────────┐
                    │    Query Understanding    │
                    │  • Intent classification  │
                    │  • Entity extraction      │
                    │  • Query expansion        │
                    └─────────────┬─────────────┘
                                  │
         ┌────────────────────────┼────────────────────────┐
         │                        │                        │
         ▼                        ▼                        ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  Hybrid Search  │    │  Entity Search  │    │  Graph Search   │
│                 │    │                 │    │                 │
│ • BM25 keywords │    │ • Named entities│    │ • Cross-doc     │
│ • Vector embed  │    │ • Concepts      │    │   references    │
│ • Category boost│    │ • Regulations   │    │ • Citation chain│
└────────┬────────┘    └────────┬────────┘    └────────┬────────┘
         │                      │                      │
         └──────────────────────┼──────────────────────┘
                                │
                    ┌───────────▼───────────┐
                    │   Candidate Fusion    │
                    │  • Deduplicate        │
                    │  • Score normalization│
                    │  • Source diversity   │
                    └───────────┬───────────┘
                                │
                    ┌───────────▼───────────┐
                    │      Reranking        │
                    │  • Cross-encoder      │
                    │  • Query relevance    │
                    │  • Recency boost      │
                    └───────────┬───────────┘
                                │
                    ┌───────────▼───────────┐
                    │   Context Assembly    │
                    │  • Expand to full     │
                    │    sections           │
                    │  • Include neighbors  │
                    │  • Add related docs   │
                    └───────────┬───────────┘
                                │
                    ┌───────────▼───────────┐
                    │  Answer Generation    │
                    │  • Multi-source       │
                    │    synthesis          │
                    │  • Citation insertion │
                    │  • Confidence scoring │
                    └───────────┬───────────┘
                                │
                    ┌───────────▼───────────┐
                    │   Response + Sources  │
                    └───────────────────────┘
```

## Key Components for Enterprise Scale

### 1. Document Organization (Beyond Flat Storage)

```
Current:
documents → pages → windows → anchors (flat hierarchy)

Enhanced:
documents
    ├── metadata (title, date, author, version, category)
    ├── structure (sections, headings, tables)
    ├── entities (extracted: people, orgs, regulations, concepts)
    ├── cross-references (cites, supersedes, related_to)
    └── temporal (version history, superseded_by)
```

```sql
-- Enhanced document metadata
ALTER TABLE documents ADD COLUMN doc_type TEXT;  -- policy, procedure, guideline, regulation
ALTER TABLE documents ADD COLUMN effective_date DATE;
ALTER TABLE documents ADD COLUMN supersedes UUID REFERENCES documents(doc_id);
ALTER TABLE documents ADD COLUMN version TEXT;
ALTER TABLE documents ADD COLUMN department TEXT;
ALTER TABLE documents ADD COLUMN classification TEXT;  -- internal, confidential, public

-- Document relationships
CREATE TABLE document_references (
    source_doc_id UUID REFERENCES documents(doc_id),
    target_doc_id UUID REFERENCES documents(doc_id),
    reference_type TEXT,  -- cites, supersedes, implements, related_to
    context TEXT,  -- surrounding text where reference found
    PRIMARY KEY (source_doc_id, target_doc_id, reference_type)
);

-- Temporal awareness
CREATE INDEX idx_doc_effective ON documents(effective_date DESC);
CREATE INDEX idx_doc_supersedes ON documents(supersedes);
```

### 2. Entity-Centric Retrieval

**Why:** "Find all documents about GDPR compliance" should find docs that mention GDPR, reference GDPR articles, discuss DSGVO (German), or implement GDPR requirements—even if they don't use the exact keyword.

```python
# app/retrieval/entity_retrieval.py

class EntityRetriever:
    """
    Retrieve based on entities, not just keywords/vectors.
    """

    def __init__(self, neo4j: Neo4jAmp, postgres: Connection):
        self.neo4j = neo4j
        self.postgres = postgres

    def extract_query_entities(self, query: str) -> list[Entity]:
        """
        Extract entities from query using NER + concept mapping.
        """
        # NER extraction
        ner_entities = self.ner_model.extract(query)

        # Map to canonical forms
        # "GDPR" → "GDPR", "DSGVO" → "GDPR", "data protection regulation" → "GDPR"
        canonical = []
        for ent in ner_entities:
            mapped = self.entity_resolver.resolve(ent)
            canonical.append(mapped)

        return canonical

    def retrieve_by_entities(
        self,
        entities: list[Entity],
        limit: int = 50,
    ) -> list[DocumentScore]:
        """
        Find documents strongly associated with these entities.
        """
        query = """
        UNWIND $entities AS entity_name
        MATCH (e:Entity {canonical_name: entity_name})-[m:MENTIONED_IN]->(d:Document)
        WITH d, sum(m.count) AS total_mentions, collect(e.canonical_name) AS matched_entities
        RETURN d.doc_id, d.title, total_mentions, matched_entities
        ORDER BY total_mentions DESC
        LIMIT $limit
        """
        return self.neo4j.query(query, entities=[e.canonical_name for e in entities], limit=limit)

    def expand_related_documents(
        self,
        doc_ids: list[str],
        hops: int = 1,
    ) -> list[str]:
        """
        Find documents related through citations/references.
        """
        query = """
        UNWIND $doc_ids AS did
        MATCH (d:Document {doc_id: did})-[:CITES|REFERENCES|RELATED_TO*1..$hops]-(related:Document)
        WHERE related.doc_id NOT IN $doc_ids
        RETURN DISTINCT related.doc_id
        """
        return self.neo4j.query(query, doc_ids=doc_ids, hops=hops)
```

### 3. Multi-Stage Retrieval Pipeline

```python
# app/retrieval/enterprise_retrieval.py

class EnterpriseRetriever:
    """
    Multi-stage retrieval combining:
    1. Hybrid search (existing)
    2. Entity-based retrieval
    3. Graph expansion
    4. Temporal filtering
    """

    async def retrieve(
        self,
        query: str,
        filters: RetrievalFilters | None = None,
    ) -> RetrievalResult:

        # Stage 1: Query Understanding
        query_analysis = await self.analyze_query(query)
        # → entities, intent, time_scope, categories

        # Stage 2: Parallel Retrieval (3 strategies)
        hybrid_task = self.hybrid_search(query, query_analysis)
        entity_task = self.entity_search(query_analysis.entities)
        graph_task = self.graph_search(query_analysis.entities)

        hybrid_results, entity_results, graph_results = await asyncio.gather(
            hybrid_task, entity_task, graph_task
        )

        # Stage 3: Fusion
        fused = self.fuse_results(
            hybrid=hybrid_results,      # weight: 0.5
            entity=entity_results,      # weight: 0.3
            graph=graph_results,        # weight: 0.2
        )

        # Stage 4: Temporal Filtering (if applicable)
        if query_analysis.prefers_recent:
            fused = self.boost_recent(fused)
        if query_analysis.prefers_authoritative:
            fused = self.boost_authoritative(fused)  # official policies > drafts

        # Stage 5: Rerank with Cross-Encoder
        reranked = await self.rerank(query, fused[:100])

        # Stage 6: Context Expansion
        # Don't just return the chunk - return surrounding context
        expanded = await self.expand_context(reranked[:20])

        # Stage 7: Find Related Documents (for "See Also")
        related = await self.find_related(
            doc_ids=[r.doc_id for r in expanded[:5]],
            exclude_ids=[r.doc_id for r in expanded],
        )

        return RetrievalResult(
            primary=expanded,
            related=related,
            entities_found=query_analysis.entities,
            query_intent=query_analysis.intent,
        )
```

### 4. Citation-Aware Answer Generation

```python
# app/reasoning/cited_answer.py

SYSTEM_PROMPT = """Du bist ein Enterprise-Dokumentenassistent.
Beantworte Fragen NUR basierend auf den bereitgestellten Quellen.

REGELN:
1. Jede Aussage MUSS mit einer Quellenangabe versehen sein: [1], [2], etc.
2. Wenn die Quellen die Frage nicht beantworten können, sage das klar.
3. Fasse Informationen aus mehreren Quellen zusammen, wenn relevant.
4. Gib am Ende eine Konfidenz-Einschätzung (hoch/mittel/niedrig).
5. Erwähne widersprüchliche Informationen zwischen Quellen.

FORMAT:
<answer>
[Deine Antwort mit Quellenverweisen wie [1], [2]]
</answer>

<confidence>hoch|mittel|niedrig</confidence>

<source_usage>
[1] Hauptaussage aus dieser Quelle
[2] Hauptaussage aus dieser Quelle
</source_usage>
"""

def build_context_with_citations(sources: list[Source]) -> str:
    """
    Build numbered context for LLM.
    """
    context_parts = []
    for i, source in enumerate(sources, 1):
        context_parts.append(f"""
[{i}] {source.document_title}
Seite/Abschnitt: {source.location}
Datum: {source.effective_date or 'Unbekannt'}
---
{source.text}
---
""")
    return "\n".join(context_parts)


async def generate_cited_answer(
    query: str,
    sources: list[Source],
) -> CitedAnswer:
    """
    Generate answer with precise citations.
    """
    context = build_context_with_citations(sources)

    response = await llm.generate(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"QUELLEN:\n{context}\n\nFRAGE: {query}"},
        ],
        temperature=0.0,
    )

    # Parse structured response
    answer = extract_between(response, "<answer>", "</answer>")
    confidence = extract_between(response, "<confidence>", "</confidence>")
    source_usage = extract_between(response, "<source_usage>", "</source_usage>")

    # Build citation objects
    citations = []
    for i, source in enumerate(sources, 1):
        if f"[{i}]" in answer:
            citations.append(Citation(
                index=i,
                document_id=source.doc_id,
                document_title=source.document_title,
                location=source.location,
                snippet=source.text[:200],
                url=source.url,
            ))

    return CitedAnswer(
        answer=answer,
        citations=citations,
        confidence=confidence,
        source_usage=source_usage,
    )
```

### 5. Scaling the Document Corpus

**Growth stages:**

| Documents | Strategy |
|-----------|----------|
| 10K | Current setup works fine |
| 100K | Add category sharding, optimize indexes |
| 1M | Tiered storage (hot/warm/cold), async indexing |
| 10M+ | Distributed vector DB, partition by domain |

**Incremental Ingestion:**

```python
# app/ingestion/incremental.py

class IncrementalIngester:
    """
    Handle growing corpus efficiently:
    - Detect duplicates/updates
    - Incremental index updates
    - Background processing
    """

    async def ingest_document(self, file_path: str) -> IngestResult:
        # 1. Hash for deduplication
        file_hash = compute_hash(file_path)
        existing = await self.find_by_hash(file_hash)

        if existing and not self.is_newer(file_path, existing):
            return IngestResult(status="duplicate", doc_id=existing.doc_id)

        # 2. Extract
        extracted = await self.extract(file_path)

        # 3. Check if this supersedes existing doc
        if existing:
            # Update existing document
            doc_id = existing.doc_id
            await self.update_document(doc_id, extracted)
            await self.reindex_windows(doc_id)
        else:
            # New document
            doc_id = await self.create_document(extracted)
            await self.index_windows(doc_id)

        # 4. Update graph relationships (async)
        await self.queue_graph_update(doc_id)

        # 5. Extract entities (async)
        await self.queue_entity_extraction(doc_id)

        return IngestResult(status="indexed", doc_id=doc_id)

    async def queue_graph_update(self, doc_id: str):
        """
        Background job to:
        - Parse citations/references
        - Link to other documents
        - Update Neo4j relationships
        """
        await self.job_queue.enqueue("update_graph", doc_id=doc_id)

    async def queue_entity_extraction(self, doc_id: str):
        """
        Background job to:
        - Run NER on document
        - Link entities to graph
        - Update entity index
        """
        await self.job_queue.enqueue("extract_entities", doc_id=doc_id)
```

**Hot/Warm/Cold Tiering:**

```python
# app/storage/tiered.py

class TieredStorage:
    """
    Tier documents by access patterns:
    - Hot: Recent, frequently accessed → RAM/SSD
    - Warm: Older, occasionally accessed → SSD
    - Cold: Archive, rarely accessed → Object storage
    """

    def __init__(self):
        self.hot_threshold_days = 90
        self.warm_threshold_days = 365

    async def get_document(self, doc_id: str) -> Document:
        # Check hot cache first
        cached = await self.hot_cache.get(doc_id)
        if cached:
            return cached

        # Load from appropriate tier
        doc = await self.load_from_tier(doc_id)

        # Promote to hot if accessed
        await self.hot_cache.set(doc_id, doc, ttl=3600)

        return doc

    async def tier_document(self, doc_id: str):
        """
        Move document to appropriate tier based on access patterns.
        """
        stats = await self.get_access_stats(doc_id)

        if stats.last_accessed_days < self.hot_threshold_days:
            # Keep in hot tier (primary DB + vector index)
            pass
        elif stats.last_accessed_days < self.warm_threshold_days:
            # Move to warm tier (keep vectors, archive full text)
            await self.move_to_warm(doc_id)
        else:
            # Move to cold tier (remove from vector index, archive everything)
            await self.move_to_cold(doc_id)
```

## Response Format (Perplexity-Style)

```python
# app/models.py

@dataclass
class EnterpriseRAGResponse:
    """
    Perplexity-style response with full source attribution.
    """
    # The synthesized answer
    answer: str

    # Confidence in the answer
    confidence: Literal["high", "medium", "low"]

    # Primary sources used (with citations)
    sources: list[SourceCitation]

    # Related documents (not directly cited but relevant)
    related_documents: list[RelatedDocument]

    # Entities detected in query
    detected_entities: list[Entity]

    # Query understanding
    query_intent: str  # "factual", "procedural", "comparative", "exploratory"

    # Metadata
    retrieval_stats: RetrievalStats


@dataclass
class SourceCitation:
    """
    Precise source attribution.
    """
    citation_index: int          # [1], [2], etc.
    document_id: str
    document_title: str
    document_type: str           # policy, procedure, regulation
    location: str                # "Page 12" or "Section 3.2"
    effective_date: date | None
    snippet: str                 # Relevant excerpt
    confidence_score: float      # How relevant this source is
    url: str | None              # Link to original document


@dataclass
class RelatedDocument:
    """
    Documents related but not directly cited.
    """
    document_id: str
    document_title: str
    relationship: str            # "cites", "superseded_by", "same_topic"
    relevance_score: float
```

## Implementation Priority

### Phase 1: Better Source Attribution (Now)
- [ ] Add citation indices to answer generation
- [ ] Include page/section location in responses
- [ ] Add confidence scoring
- [ ] Format response with clear source list

### Phase 2: Entity-Aware Retrieval (Next)
- [ ] Add NER to ingestion pipeline
- [ ] Store entities in Neo4j
- [ ] Query expansion using entity synonyms
- [ ] Entity-based document discovery

### Phase 3: Cross-Document Intelligence (Then)
- [ ] Parse citations/references during ingestion
- [ ] Build document relationship graph
- [ ] Add "Related Documents" to responses
- [ ] Citation chain traversal

### Phase 4: Scale Optimization (Later)
- [ ] Async entity extraction
- [ ] Tiered storage for large corpus
- [ ] Category-based index sharding
- [ ] Query result caching

## Key Metrics to Track

| Metric | Target | Why |
|--------|--------|-----|
| Answer accuracy | >90% | Core value |
| Source precision | >95% | Citations must be correct |
| Retrieval recall@20 | >85% | Find relevant docs |
| Query latency P95 | <3s | User experience |
| Citation coverage | >80% | Most claims should cite |

## Summary

**Enterprise RAG ≠ NotebookLM clone**

Enterprise RAG = **Perplexity for your internal documents**

Focus on:
1. **Finding the right information** across growing corpus
2. **Precise source attribution** with page/section citations
3. **Cross-document intelligence** through entity/graph
4. **Synthesized answers** that combine multiple sources
5. **Scalable ingestion** that handles document growth

The current foundation (hybrid search, reranking, evidence validation) is solid. Enhance it with:
- Entity extraction + resolution
- Citation parsing + linking
- Better answer formatting with sources
- Related document discovery
