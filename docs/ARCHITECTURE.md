# Enterprise RAG — Architecture & Approach

## Classification: Advanced RAG with Agentic Query Planning

Enterprise RAG is an **Advanced RAG** system that goes beyond naive retrieve-and-generate by incorporating multi-step LLM decision-making, hybrid retrieval strategies, and cross-document intelligence. The query planning component introduces **agentic characteristics** where the LLM autonomously decides how to search.

### RAG Taxonomy

```
Naive RAG          → Query → Retrieve → Generate
  (single embedding lookup, no preprocessing)

Advanced RAG       → Query → Plan → Multi-Retrieve → Rerank → Pack → Generate  ← We are here
  (query rewriting, hybrid search, reranking, dynamic context)

Agentic RAG        → Query → Agent Loop (Plan → Retrieve → Evaluate → Re-plan) → Generate
  (iterative retrieval, self-reflection, tool selection, autonomous decision loops)
```

## Current Approach

### 1. Agentic Query Planning

The LLM acts as an autonomous planner that decides *how* to search:

```
User Query: "Vergleich der DSGVO Anforderungen 2023 und 2024"
                              │
                              ▼
                    ┌─ LLM Query Planner ─┐
                    │                     │
                    │  Decisions:          │
                    │  • Generate rewrites │
                    │  • Extract BM25 terms│
                    │  • Infer categories  │
                    └─────────────────────┘
                              │
                              ▼
                    Plan Output:
                    {
                      "rewrites": [
                        "DSGVO Anforderungen 2023",
                        "DSGVO Anforderungen 2024",
                        "Datenschutz Vergleich 2023 2024"
                      ],
                      "bm25_query": "DSGVO Anforderungen Datenschutz 2023 2024",
                      "categories": ["datenschutz"]
                    }
```

This is the most agentic component — the LLM autonomously decides query strategy rather than following a fixed template.

### 2. Hybrid Retrieval Pipeline

Two parallel retrieval paths with distinct strategies:

```
                    ┌─────────────────────────────────────┐
                    │         Query Plan                   │
                    └──────────┬──────────────────────────┘
                               │
                 ┌─────────────┴─────────────┐
                 │                           │
                 ▼                           ▼
        ┌─ BM25 Path ──┐          ┌─ Vector Path ────────┐
        │               │          │                      │
        │ Single        │          │ Multiple rewrites    │
        │ optimized     │          │ embedded in parallel │
        │ keyword query │          │ (batch API call)     │
        │               │          │                      │
        │ ts_rank_cd    │          │ Cosine similarity    │
        │ scoring       │          │ via HNSW index       │
        └───────┬───────┘          └──────────┬───────────┘
                │                              │
                └──────────┬───────────────────┘
                           │
                           ▼
                  ┌─ Union + Dedup ─┐
                  │                 │
                  │ Blend scores:   │
                  │ 55% vector      │
                  │ 45% BM25        │
                  │                 │
                  │ Category boost  │
                  │ (1.20x match)   │
                  └────────┬────────┘
                           │
                           ▼
                  ┌─ Cross-Encoder ─┐
                  │   Reranking     │
                  │                 │
                  │ TEI with        │
                  │ bge-reranker    │
                  │ -v2-m3          │
                  └────────┬────────┘
                           │
                           ▼
                  ┌─ Diversification ┐
                  │                  │
                  │ Max 2 results    │
                  │ per document     │
                  └────────┬─────────┘
                           │
                           ▼
                  ┌─ Citation Graph ─┐
                  │   Expansion      │
                  │                  │
                  │ Neo4j CITES      │
                  │ edge traversal   │
                  └──────────────────┘
```

### 3. Dynamic Context Sizing

The system analyzes query complexity and scales retrieval limits accordingly:

| Signal | Example | Effect |
|--------|---------|--------|
| Comparison keywords | "im Vergleich", "vs" | +complexity |
| Multiple time periods | "2023 und 2024" | +complexity |
| Aggregation requests | "alle", "gesamt" | +complexity |
| Multi-part questions | "und", "sowie" | +complexity |
| List requests | "Liste", "Aufzählung" | +complexity |

Complexity score maps to a multiplier (0.5x – 1.5x) applied to context packing limits, evidence windows, and answer token budget.

### 4. Evidence Extraction

```
Packed Context (windows + anchors + cited documents)
                    │
                    ▼
           ┌─ LLM Generation ─┐
           │                   │
           │  Plain text input │
           │  (not JSON)       │
           │                   │
           │  Inline citations │
           │  [1], [2], [3]    │
           │                   │
           │  Confidence score │
           │  high/medium/low  │
           └───────────────────┘
```

The LLM receives numbered context blocks and generates answers with inline source references. A flexible JSON parser normalizes the output, with a markdown fallback if parsing fails.

### 5. Cross-Document Intelligence

Neo4j stores citation relationships extracted during ingestion:

```
Document A ──CITES──▶ Document B ──CITES──▶ Document C
    │                     │
    │  URL reference       │  ISO standard ref
    │  German law ref      │  Internal reference
```

During retrieval, the citation graph is traversed to surface related documents that weren't directly matched by search — enabling "via Zitat" transitive references.

## What Could Be Next: Toward Agentic RAG

### Iterative Retrieval Loop

Add a judge step that evaluates retrieval quality and decides whether to re-query:

```
                    ┌──────────────────────┐
                    │     Query Plan       │
                    └──────────┬───────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │     Retrieve         │◄────────┐
                    └──────────┬───────────┘         │
                               │                     │
                               ▼                     │
                    ┌──────────────────────┐         │
                    │  Judge: Sufficient?  │         │
                    │  • Coverage check    │─── No ──┘
                    │  • Relevance score   │  (re-plan with
                    │  • Gap detection     │   different terms)
                    └──────────┬───────────┘
                               │ Yes
                               ▼
                    ┌──────────────────────┐
                    │     Generate Answer  │
                    └──────────────────────┘
```

**Impact:** Higher answer quality for complex queries at the cost of additional LLM calls and latency.

### Sub-Question Decomposition

Break complex queries into independent sub-questions, retrieve for each, then synthesize:

```
"Vergleich der DSGVO Anforderungen 2023 und 2024"
                    │
                    ▼
        ┌───────────────────────┐
        │  Decompose into:      │
        │  Q1: DSGVO 2023?      │
        │  Q2: DSGVO 2024?      │
        │  Q3: Key differences? │
        └───────────┬───────────┘
                    │
          ┌─────────┼─────────┐
          ▼         ▼         ▼
       Retrieve  Retrieve  Retrieve
          │         │         │
          └─────────┼─────────┘
                    │
                    ▼
              Synthesize answer
              from all sub-results
```

**Impact:** Better handling of comparison and multi-part questions. The complexity analyzer already detects these patterns but doesn't yet act on them.

### Tool Selection

Let the agent choose which retrieval tool to use based on query type:

```
Query: "Wie viele Dokumente wurden 2024 veröffentlicht?"
                    │
                    ▼
        ┌─ Agent Decision ─────────┐
        │                          │
        │  Available tools:        │
        │  • Vector search         │
        │  • BM25 full-text        │
        │  • SQL aggregation  ◄──  │  (chose this)
        │  • Citation graph        │
        │                          │
        └──────────────────────────┘
```

**Impact:** Enables answering analytical/aggregation queries that don't fit the retrieve-and-generate pattern.

### Self-Reflection

After generating an answer, have the LLM evaluate its own response:

```
Generated Answer
       │
       ▼
┌─ Self-Check ──────────────┐
│                           │
│  • Are all claims cited?  │
│  • Do citations match?    │
│  • Any contradictions?    │
│  • Confidence justified?  │
│                           │
└───────────┬───────────────┘
            │
     ┌──────┴──────┐
     │             │
   Pass          Fail
     │             │
     ▼             ▼
  Return      Re-generate
  answer      with feedback
```

**Impact:** Higher answer accuracy and better calibrated confidence scores. Adds one extra LLM call per query.

## Trade-offs

| Aspect | Current (Advanced) | Agentic Extension |
|--------|-------------------|-------------------|
| Latency | Predictable (single pass) | Variable (1-3 rounds) |
| Cost | Fixed LLM calls per query | 2-4x more LLM calls |
| Debuggability | Linear pipeline, easy to trace | Loop state harder to debug |
| Quality | Good for focused queries | Better for complex/multi-part |
| Reliability | Deterministic pipeline | Non-deterministic loops |

The current Advanced RAG approach prioritizes **predictable latency and debuggability** while still leveraging LLM intelligence at key decision points. Agentic extensions should be added incrementally where they provide measurable quality improvement.
