# Retrieval Concepts: How Enterprise RAG Finds Information

This document explains the conceptual architecture of the retrieval pipeline - why each component exists and how they work together.

---

## Document Extraction

### Supported Formats

| Format | Extensions | Library | Notes |
|--------|------------|---------|-------|
| PDF | `.pdf` | PyMuPDF | Text + embedded hyperlinks |
| Word | `.docx` | python-docx | Sections split by headings |
| Excel | `.xlsx`, `.xlsm` | openpyxl | Row-level with header context |
| HTML | `.html`, `.htm`, `.aspx` | trafilatura | Tables included |

### Excel Extraction (Detailed)

Excel files get special handling to make tabular data searchable:

**The Problem:**
- Excel has rows and columns, not prose
- Simple text dump loses structure: `Apple  2.50  100`
- Long columns (2000+ rows) need chunking

**The Solution:**

1. **Header Context**: Each row is formatted with column headers
   ```
   Before: Apple    2.50    100
   After:  Product: Apple | Price: 2.50 | Quantity: 100
   ```

2. **Overlapping Chunks**: Rows are grouped into overlapping pages
   ```
   Page 1: Rows 2-31   (30 rows)
   Page 2: Rows 22-51  (overlaps by 10)
   Page 3: Rows 42-71  (overlaps by 10)
   ...
   ```

3. **Settings**:
   - `ROWS_PER_CHUNK = 30` - rows per page
   - `OVERLAP_ROWS = 10` - overlap between chunks
   - `max_rows = 5000` - maximum rows per sheet
   - `max_cols = 50` - maximum columns

**Example Output:**
```
Sheet: Inventory (Zeilen 2-31)
Product: Apple | Price: 2.50 | Quantity: 100
Product: Banana | Price: 1.80 | Quantity: 250
Product: Cherry | Price: 4.00 | Quantity: 50
...

Sheet: Inventory (Zeilen 22-51)
Product: Banana | Price: 1.80 | Quantity: 250
...
```

**Why This Works:**
- Query "Apple Preis" → BM25 matches "Apple" and "Price" in same row
- Query "Produkte über 100" → Embedding captures semantic meaning
- Overlapping ensures no row is split between chunks

### Ingesting by File Type

To re-ingest only specific file types:

```bash
# Only Excel files
python scripts/ingest_folder.py --folder /path/to/data --type xlsx

# Only PDFs
python scripts/ingest_folder.py --folder /path/to/data --type pdf

# All supported types (default)
python scripts/ingest_folder.py --folder /path/to/data
```

---

## The Core Problem

Enterprise documents are long, complex, and full of mixed content. A single PDF might contain:
- Multiple topics across sections
- Tables, lists, and prose
- References to other documents
- Technical terms and domain jargon

We need to find the *right* information for a user's query, not just *any* matching text.

## Document Processing: Windows and Anchors

### Sliding Windows (for Recall)

Documents are split into overlapping 2-page windows:

```
10-page document → Windows: [1-2], [2-3], [3-4], ... [9-10] = 9 windows
```

**Configuration:**
- `WINDOW_PAGES=2` - Each window spans 2 pages
- `WINDOW_STRIDE=1` - Windows overlap by 1 page
- `MAX_WINDOW_CHARS=24000` - Maximum characters per window

**Why 2 pages?**

| Chunk Size | Pros | Cons |
|------------|------|------|
| Sentence | Precise | No context, noisy retrieval |
| Paragraph | Balanced | May miss cross-paragraph info |
| **2 pages** | Rich context, good recall | Some semantic mixing |
| Full document | Complete context | Embedding too diluted |

**Why overlap?**

If important information spans pages 3-4, overlapping windows ensure it's captured:
- Window [2-3] catches the beginning
- Window [3-4] catches the full content
- Window [4-5] catches the end

No information falls between the cracks.

### Anchors (for Precision)

Fine-grained chunks extracted during ingestion:
- Paragraphs
- Tables
- Lists
- Headings with their content

Anchors don't have embeddings - they're used to add precision after initial retrieval.

## The Retrieval Pipeline

```
                                    ┌─────────────────┐
                                    │   User Query    │
                                    └────────┬────────┘
                                             │
                              ┌──────────────▼──────────────┐
                              │      Query Planning         │
                              │  LLM generates 3-6 rewrites │
                              │  (synonyms, reformulations) │
                              └──────────────┬──────────────┘
                                             │
                    ┌────────────────────────┼────────────────────────┐
                    │                        │                        │
                    ▼                        ▼                        │
          ┌─────────────────┐      ┌─────────────────┐               │
          │      BM25       │      │  Vector Search  │               │
          │  (keyword match)│      │ (semantic match)│               │
          │                 │      │                 │               │
          │  120 candidates │      │  120 candidates │               │
          └────────┬────────┘      └────────┬────────┘               │
                   │                        │                        │
                   └───────────┬────────────┘                        │
                               │                                     │
                    ┌──────────▼──────────┐                         │
                    │    Hybrid Merge     │                         │
                    │  55% vector score   │                         │
                    │  45% BM25 score     │                         │
                    │                     │                         │
                    │    Top 30 results   │                         │
                    └──────────┬──────────┘                         │
                               │                                     │
                    ┌──────────▼──────────┐                         │
                    │      Reranker       │                         │
                    │   (cross-encoder)   │                         │
                    │                     │                         │
                    │    Top 18 results   │                         │
                    └──────────┬──────────┘                         │
                               │                                     │
                    ┌──────────▼──────────┐      ┌───────────────────┘
                    │   Context Packing   │◄─────┤ Category boost
                    │  + Citation Chain   │      │ Anchor enrichment
                    └──────────┬──────────┘      │ Cited documents
                               │
                    ┌──────────▼──────────┐
                    │    LLM Synthesis    │
                    │  Answer + Citations │
                    └─────────────────────┘
```

## Component Deep Dive

### 1. BM25 (Best Match 25)

**What it does:** Keyword matching with term frequency analysis.

**Strengths:**
- Exact term matching ("ISO 27001", "DSGVO §42")
- German compound words ("Datenschutzbeauftragter")
- Fast, no model required
- Highly interpretable

**Weaknesses:**
- No synonym understanding ("Umsatz" ≠ "Einnahmen")
- No semantic similarity
- Fails on paraphrases

**When it wins:** Technical queries with specific terms.

### 2. Vector Search (Embeddings)

**What it does:** Encodes text into high-dimensional vectors, finds similar vectors.

```
Query: "Wie gehen wir mit Kundendaten um?"
        ↓
   [0.12, -0.45, 0.78, ...] (4096 dimensions)
        ↓
   Cosine similarity with document embeddings
        ↓
   Semantically similar documents
```

**Strengths:**
- Semantic understanding ("Umsatz" ≈ "Einnahmen")
- Handles paraphrases and synonyms
- Works across vocabulary gaps

**Weaknesses:**
- Can be "fuzzy" with exact terms
- Meaning gets averaged in long chunks
- Requires embedding model

**When it wins:** Vague or conceptual queries.

### 3. Hybrid Merge

**What it does:** Combines BM25 and vector scores.

```python
final_score = 0.55 * vector_score + 0.45 * bm25_score
```

**Why hybrid?**

| Query Type | BM25 | Vector | Winner |
|------------|------|--------|--------|
| "ISO 27001 Anforderungen" | ✅ Strong | ⚠️ OK | BM25 |
| "Datenschutz allgemein" | ⚠️ Weak | ✅ Strong | Vector |
| "DSGVO Compliance Maßnahmen" | ✅ Good | ✅ Good | Both |

Hybrid ensures neither approach's blind spots hurt retrieval.

### 4. Reranker (Cross-Encoder)

**What it does:** Re-scores query-document pairs with deep understanding.

**Architecture difference:**

```
Bi-encoder (Embeddings):
  Query    → [vector] ─────────────────┐
                                       ├→ cosine similarity → 0.82
  Document → [vector] ─────────────────┘

  (Encoded separately, compared mathematically)

Cross-encoder (Reranker):
  [Query + Document] → transformer → relevance score → 0.94

  (Encoded together, model sees the relationship)
```

**Why cross-encoder is more accurate:**
- Sees query and document together
- Understands word interactions
- Can detect subtle relevance signals

**Why we don't use it for initial search:**
- Too slow (can't pre-compute)
- Must run for every query-document pair
- Only feasible for top 30-50 candidates

**Model:** `BAAI/bge-reranker-v2-m3` via TEI (Text Embeddings Inference)

### 5. Context Packing

**What it does:** Assembles the final context for the LLM.

Includes:
- Top-ranked windows (with source indices)
- Relevant anchors (tables, lists for precision)
- Cited documents (from Neo4j citation graph)

**Dynamic sizing:** Adjusts context size based on query complexity.

## Who Does the Heavy Lifting?

| Stage | Role | Contribution |
|-------|------|--------------|
| BM25 | Recall | Finds keyword matches, strong for German |
| Embeddings | Recall | Finds semantic matches, handles synonyms |
| Hybrid | Balance | Ensures neither misses dominate |
| **Reranker** | **Precision** | **Most accurate relevance scoring** |
| LLM | Synthesis | Generates answer from context |

**Key insight:** BM25 + embeddings maximize *recall* (finding candidates). The reranker maximizes *precision* (picking the best ones).

## Do We Need Embeddings?

Honest assessment:

**Embeddings add 10-20% value:**
- Semantic matching for vague queries
- Synonym and paraphrase handling
- Cross-lingual potential

**BM25 + reranker could work alone:**
- Query rewrites expand synonyms (via LLM)
- Reranker provides semantic understanding
- Simpler infrastructure

**Why we keep both:**
- Insurance against blind spots
- Different query types benefit from each
- Hybrid is proven to outperform single-method

## Configuration Reference

### Retrieval Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `CANDIDATES_BM25` | 120 | BM25 retrieval candidates |
| `CANDIDATES_VEC` | 120 | Vector retrieval candidates |
| `RERANK_KEEP` | 18 | Results after reranking |
| `MAX_PER_DOC` | 2 | Max results per document (diversity) |
| `CATEGORY_BOOST` | 1.20 | Boost for category-matched results |

### Windowing Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `WINDOW_PAGES` | 2 | Pages per sliding window |
| `WINDOW_STRIDE` | 1 | Window slide step (overlap) |
| `MAX_WINDOW_CHARS` | 24000 | Max characters per window |
| `MAX_ANCHOR_CHARS` | 2000 | Max characters per anchor |

### Reranker Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `RERANK_ENABLED` | true | Enable TEI reranker |
| `RERANK_BASE_URL` | http://localhost:9001 | TEI endpoint |
| `RERANK_CHARS_PER_DOC` | 1500 | Characters sent to reranker per doc |

## Summary

```
┌─────────────────────────────────────────────────────────────────┐
│                        RECALL STAGE                             │
│  BM25 + Embeddings → Find all potentially relevant documents    │
│  (Cast a wide net - 120+ candidates each)                       │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      PRECISION STAGE                            │
│  Reranker → Pick the truly relevant ones                        │
│  (Cross-encoder accuracy on top 30)                             │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      SYNTHESIS STAGE                            │
│  LLM → Generate cited answer from best sources                  │
│  (Context packing + evidence extraction)                        │
└─────────────────────────────────────────────────────────────────┘
```

The architecture follows the proven pattern: **cheap methods for recall, expensive methods for precision**.
