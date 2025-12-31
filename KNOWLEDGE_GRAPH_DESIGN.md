# Knowledge Graph Design: Perplexity-Style Source Traversal

This document outlines an enhanced Neo4j schema and ingestion pipeline to enable cross-document traversal and source discovery.

## Enhanced Graph Schema

### Node Types

```cypher
// Core nodes (existing)
(:Document {doc_id, title, uri, categories[], created_at})
(:Page {doc_id, page_no})
(:Anchor {anchor_id, doc_id, type, text})

// New nodes
(:Entity {entity_id, name, type, canonical_name})
// Types: PERSON, ORG, LOCATION, CONCEPT, REGULATION, PRODUCT

(:Claim {claim_id, text, anchor_id})
// Extracted factual statements

(:Reference {ref_id, raw_text, parsed_title, parsed_uri})
// Citations/references extracted from documents
```

### Relationship Types

```cypher
// Existing
(Document)-[:HAS_PAGE]->(Page)
(Page)-[:HAS_ANCHOR]->(Anchor)

// Cross-document relationships
(Document)-[:CITES {context: "..."}]->(Document)
(Document)-[:REFERENCES]->(Reference)
(Reference)-[:RESOLVES_TO]->(Document)  // when we can match the reference

// Entity relationships
(Entity)-[:MENTIONED_IN {count: N, anchors: [...]}]->(Document)
(Entity)-[:APPEARS_ON]->(Page)
(Entity)-[:SAME_AS]->(Entity)  // cross-doc entity resolution
(Entity)-[:RELATED_TO {type: "subsidiary_of"}]->(Entity)

// Claim relationships
(Claim)-[:EXTRACTED_FROM]->(Anchor)
(Claim)-[:SUPPORTED_BY]->(Anchor)  // in other documents
(Claim)-[:CONTRADICTED_BY]->(Anchor)

// Semantic similarity (computed offline)
(Document)-[:SIMILAR_TO {score: 0.85}]->(Document)
(Anchor)-[:SIMILAR_TO {score: 0.90}]->(Anchor)
```

### Indexes

```cypher
// Unique constraints
CREATE CONSTRAINT entity_id IF NOT EXISTS FOR (e:Entity) REQUIRE e.entity_id IS UNIQUE;
CREATE CONSTRAINT claim_id IF NOT EXISTS FOR (c:Claim) REQUIRE c.claim_id IS UNIQUE;
CREATE CONSTRAINT ref_id IF NOT EXISTS FOR (r:Reference) REQUIRE r.ref_id IS UNIQUE;

// Full-text search
CREATE FULLTEXT INDEX entity_name IF NOT EXISTS FOR (e:Entity) ON EACH [e.name, e.canonical_name];
CREATE FULLTEXT INDEX claim_text IF NOT EXISTS FOR (c:Claim) ON EACH [c.text];

// Performance indexes
CREATE INDEX entity_type IF NOT EXISTS FOR (e:Entity) ON (e.type);
CREATE INDEX mention_count IF NOT EXISTS FOR ()-[m:MENTIONED_IN]-() ON (m.count);
```

## Enhanced Ingestion Pipeline

### Current Pipeline
```
File → Extract → Normalize → Segment → Store (Postgres + Neo4j)
```

### Enhanced Pipeline
```
File → Extract → Normalize → Segment
                                ↓
                    ┌───────────┴───────────┐
                    ↓                       ↓
              Store Base              Enrich Graph
              (Postgres)                    ↓
                              ┌─────────────┼─────────────┐
                              ↓             ↓             ↓
                         Extract NER   Parse Citations   Extract Claims
                              ↓             ↓             ↓
                         Link Entities  Resolve Refs    Link Claims
                              ↓             ↓             ↓
                              └─────────────┴─────────────┘
                                            ↓
                                    Store Graph (Neo4j)
                                            ↓
                                  Compute Similarity Edges (async)
```

### New Pipeline Components

#### 1. Entity Extraction (`app/graph/entities.py`)

```python
from dataclasses import dataclass

@dataclass
class ExtractedEntity:
    name: str
    type: str  # PERSON, ORG, LOCATION, CONCEPT, REGULATION
    mentions: list[tuple[int, int]]  # (anchor_id, char_offset)
    confidence: float

def extract_entities(text: str, anchor_id: int) -> list[ExtractedEntity]:
    """
    Use NER model to extract entities.
    Options:
    - SpaCy German model (de_core_news_lg)
    - Flair NER
    - LLM-based extraction for domain-specific entities
    """
    pass

def resolve_entity(entity: ExtractedEntity, existing: list[Entity]) -> str:
    """
    Match to existing entity or create new.
    Use embedding similarity + string matching.
    Returns entity_id.
    """
    pass
```

#### 2. Citation Parsing (`app/graph/citations.py`)

```python
@dataclass
class ParsedReference:
    raw_text: str
    title: str | None
    authors: list[str]
    uri: str | None
    doc_type: str  # standard, regulation, internal_doc, web

def extract_references(text: str) -> list[ParsedReference]:
    """
    Extract citations/references from document text.
    Patterns to detect:
    - "siehe [Document Title]"
    - "gemäß ISO 27001"
    - "laut §42 DSGVO"
    - "[1] Author, Title, Year"
    - URLs and internal doc references
    """
    pass

def resolve_reference(ref: ParsedReference, doc_index: SearchIndex) -> str | None:
    """
    Try to match reference to existing document.
    Returns doc_id if found, None otherwise.
    """
    pass
```

#### 3. Claim Extraction (`app/graph/claims.py`)

```python
@dataclass
class ExtractedClaim:
    text: str
    anchor_id: int
    claim_type: str  # factual, procedural, definitional
    entities: list[str]  # entity_ids mentioned

def extract_claims(anchor_text: str, anchor_id: int) -> list[ExtractedClaim]:
    """
    Use LLM to extract factual claims from anchor.

    Prompt:
    "Extract factual claims from this text. Each claim should be
    a single verifiable statement. Return as JSON array."
    """
    pass

def find_supporting_claims(claim: ExtractedClaim, graph: Neo4jAmp) -> list[str]:
    """
    Find anchors in other documents that support/contradict this claim.
    Uses semantic similarity on claim embeddings.
    """
    pass
```

#### 4. Similarity Edge Builder (`app/graph/similarity.py`)

```python
def build_document_similarity_edges(threshold: float = 0.75):
    """
    Offline job: compute document-level similarity.

    For each document pair with cosine similarity > threshold,
    create SIMILAR_TO edge with score.

    Use average of window embeddings or dedicated doc embedding.
    """
    pass

def build_anchor_similarity_edges(threshold: float = 0.85):
    """
    Offline job: compute anchor-level similarity.

    More selective (higher threshold) since anchors are specific.
    Enables finding similar paragraphs across documents.
    """
    pass
```

## Traversal Queries

### Find Related Sources (2-hop)

```cypher
// Given a starting document, find related documents through citations
MATCH (start:Document {doc_id: $doc_id})
OPTIONAL MATCH (start)-[:CITES]->(cited:Document)
OPTIONAL MATCH (start)<-[:CITES]-(citing:Document)
OPTIONAL MATCH (start)-[:SIMILAR_TO]-(similar:Document)
WHERE similar.doc_id <> start.doc_id
RETURN cited, citing, similar
```

### Find Sources for Entity

```cypher
// Find all documents mentioning an entity, ranked by mention count
MATCH (e:Entity {canonical_name: $entity_name})-[m:MENTIONED_IN]->(d:Document)
RETURN d.doc_id, d.title, m.count
ORDER BY m.count DESC
LIMIT 10
```

### Find Supporting Evidence for Claim

```cypher
// Given a claim, find supporting anchors in other documents
MATCH (c:Claim {claim_id: $claim_id})-[:EXTRACTED_FROM]->(source:Anchor)
MATCH (source)<-[:HAS_ANCHOR]-(p:Page)<-[:HAS_PAGE]-(d:Document)
WITH c, d

// Find similar anchors in other documents
MATCH (other_d:Document)-[:HAS_PAGE]->()-[:HAS_ANCHOR]->(other_a:Anchor)
WHERE other_d.doc_id <> d.doc_id
AND other_a.embedding IS NOT NULL

// Would use vector similarity here - pseudo-code
WITH other_a, gds.similarity.cosine(c.embedding, other_a.embedding) AS score
WHERE score > 0.8
RETURN other_a.anchor_id, other_a.text, score
ORDER BY score DESC
LIMIT 5
```

### Trace Citation Chain

```cypher
// Follow citation chain up to 3 hops
MATCH path = (start:Document {doc_id: $doc_id})-[:CITES*1..3]->(cited:Document)
RETURN path, length(path) as depth
ORDER BY depth
```

### Find Common Entities Across Documents

```cypher
// Find entities shared between two documents
MATCH (d1:Document {doc_id: $doc1})<-[:MENTIONED_IN]-(e:Entity)-[:MENTIONED_IN]->(d2:Document {doc_id: $doc2})
RETURN e.canonical_name, e.type
```

## Integration with Retrieval Pipeline

### Enhanced `hybrid.py`

```python
async def retrieve_with_graph_expansion(
    query: str,
    settings: Settings,
) -> RetrievalResult:
    # 1. Standard hybrid retrieval (existing)
    base_results = await hybrid_retrieve(query, settings)

    # 2. Extract entities from query
    query_entities = extract_entities(query)

    # 3. Graph expansion
    expanded_doc_ids = set()
    for result in base_results.windows[:5]:  # top 5
        # Find citing/cited documents
        related = graph.get_related_documents(result.doc_id, hops=1)
        expanded_doc_ids.update(related)

        # Find documents with shared entities
        doc_entities = graph.get_document_entities(result.doc_id)
        for entity in doc_entities:
            if entity in query_entities:
                related_by_entity = graph.get_documents_by_entity(entity)
                expanded_doc_ids.update(related_by_entity)

    # 4. Fetch and score expanded documents
    expanded_windows = fetch_windows_for_docs(expanded_doc_ids)

    # 5. Rerank combined results
    all_windows = base_results.windows + expanded_windows
    reranked = await rerank(query, all_windows)

    # 6. Build citation trail for transparency
    citation_trails = build_citation_trails(reranked[:10])

    return RetrievalResult(
        windows=reranked,
        citation_trails=citation_trails,
        entities_found=query_entities,
    )
```

### Citation Trail Response

```python
@dataclass
class CitationTrail:
    """Shows how a source was found."""
    source_doc_id: str
    source_title: str
    discovery_path: list[str]  # ["direct_match", "cited_by:doc123", "shared_entity:ISO27001"]
    relevance_score: float
```

## Implementation Phases

### Phase 1: Entity Extraction
- Add SpaCy German NER
- Extract and store entities during ingestion
- Build `MENTIONED_IN` edges
- Enable entity-based document discovery

### Phase 2: Citation Parsing
- Build citation regex patterns for German documents
- Parse standards references (ISO, DIN, DSGVO)
- Create `CITES` and `REFERENCES` edges
- Implement reference resolution

### Phase 3: Claim Extraction
- LLM-based claim extraction from anchors
- Store claims with embeddings
- Build `SUPPORTED_BY` edges via similarity

### Phase 4: Similarity Edges
- Offline job for document similarity
- Offline job for anchor similarity
- Incremental updates on new documents

### Phase 5: Retrieval Integration
- Graph expansion in retrieval pipeline
- Citation trail generation
- Entity-aware query understanding

## Dependencies to Add

```toml
[project.optional-dependencies]
graph = [
    "spacy>=3.7.0",
    "de_core_news_lg @ https://github.com/explosion/spacy-models/releases/download/de_core_news_lg-3.7.0/de_core_news_lg-3.7.0.tar.gz",
    "flair>=0.13.0",  # alternative NER
]
```

## Estimated Complexity

| Component | Effort | Risk |
|-----------|--------|------|
| Entity extraction | Medium | Low - well-established NER |
| Entity resolution | High | Medium - fuzzy matching is hard |
| Citation parsing | Medium | Medium - regex + heuristics |
| Reference resolution | High | High - matching is imperfect |
| Claim extraction | Medium | Medium - LLM quality varies |
| Similarity edges | Low | Low - just compute + store |
| Retrieval integration | Medium | Low - additive change |

## Trade-offs

**Pros:**
- Rich cross-document discovery
- Transparent source chains ("this doc cites that doc")
- Entity-centric search ("find all docs about ISO 27001")
- Better evidence aggregation

**Cons:**
- Significantly more complex ingestion
- NER/entity resolution errors propagate
- Higher compute cost (NER, LLM for claims)
- Graph queries add latency
- More infrastructure to maintain
