# Enterprise RAG

[![Python 3.12](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688.svg)](https://fastapi.tiangolo.com/)
[![PostgreSQL 16](https://img.shields.io/badge/PostgreSQL-16-336791.svg)](https://www.postgresql.org/)
[![Neo4j 5](https://img.shields.io/badge/Neo4j-5-008CC1.svg)](https://neo4j.com/)

German-language document retrieval and question answering system with hybrid search, citation-aware answers, and cross-document intelligence.

## Features

- **Hybrid Search** — BM25 full-text + vector similarity with cross-encoder reranking
- **Citation-Aware Answers** — Inline `[1]`, `[2]` references with confidence scoring
- **Cross-Document Intelligence** — Citation graph traversal via Neo4j for linked documents
- **Multi-Format Ingestion** — PDF, DOCX, XLSX, HTML/ASPX with automatic text extraction
- **Streaming API** — Server-Sent Events (SSE) for real-time response streaming
- **Dynamic Context Sizing** — Automatically adjusts context window based on query complexity
- **Category Filtering** — Organize and filter documents by category
- **Document Versioning** — Deduplication and version tracking with archived document support
- **Model Profiles** — Switch between instruct (fast) and reasoning (thorough) modes
- **Web Crawler** — Extract and ingest documents from web pages with pattern-based URL crawling

## Architecture

```
┌─ INGESTION ──────────────────────┐   ┌─ RETRIEVAL ──────────────────────┐
│                                  │   │                                  │
│  File (PDF/DOCX/XLSX/HTML)       │   │  Query                           │
│   │                              │   │   │                              │
│   ├─ Text Extraction             │   │   ├─ Query Planning (LLM)        │
│   ├─ Normalization               │   │   │   └─ BM25 term extraction    │
│   ├─ Sliding-Window Segmentation │   │   │                              │
│   │   ├─ Windows (multi-page)    │   │   ├─ Candidate Generation        │
│   │   └─ Anchors (paragraphs,   │   │   │   ├─ BM25 full-text search   │
│   │       tables, lists)         │   │   │   └─ Vector similarity       │
│   └─ Citation Extraction         │   │   │                              │
│       (URLs, ISO refs, law refs) │   │   ├─ Hybrid Blending (55/45)     │
│                                  │   │   ├─ Cross-Encoder Reranking     │
│   ▼                              │   │   ├─ Per-Document Diversification│
│  PostgreSQL + Neo4j              │   │   └─ Citation Graph Expansion    │
│   ├─ documents, pages, windows   │   │                                  │
│   ├─ anchors, citations          │   └──────────────────────────────────┘
│   ├─ HNSW vector index           │
│   ├─ tsvector full-text index    │   ┌─ REASONING ──────────────────────┐
│   └─ CITES graph edges           │   │                                  │
│                                  │   │  Context Packing                 │
└──────────────────────────────────┘   │   ├─ Windows + Anchors           │
                                       │   └─ Cited Documents (Neo4j)     │
                                       │                                  │
                                       │  Evidence Extraction (LLM)       │
                                       │   ├─ Answer with [1],[2] refs    │
                                       │   ├─ Confidence scoring          │
                                       │   └─ Source attribution          │
                                       │                                  │
                                       │  Streaming Response (SSE)        │
                                       │   ├─ Sources → Thinking → Answer │
                                       │   └─ Instruct / Reasoning mode   │
                                       │                                  │
                                       └──────────────────────────────────┘
```

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.12 |
| Web Framework | FastAPI + Uvicorn |
| Database | PostgreSQL 16 + pgvector (HNSW indexes) |
| Graph Database | Neo4j 5 (citation chains) |
| Cache / Queue | Redis 7 |
| LLM / Embeddings | Ollama (OpenAI-compatible API) |
| Reranker | TEI with BAAI/bge-reranker-v2-m3 |
| Observability | structlog + OpenTelemetry + Jaeger |
| Package Manager | uv |

## Quick Start

### Prerequisites

- Docker & Docker Compose
- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- Running Ollama instance with your chosen models

### Setup

```bash
# Start infrastructure (PostgreSQL, Neo4j, Redis, TEI reranker, Jaeger)
docker compose up -d

# Install Python dependencies
uv sync

# Configure environment
cp .env.example .env
# Edit .env with your LLM/embedding endpoints

# Initialize database schema
uv run python scripts/init_db.py
```

### Ingest Documents

```bash
# Ingest documents from a folder
uv run python scripts/ingest_folder.py --folder /path/to/docs --recursive

# Backfill embeddings
uv run python scripts/embed_windows.py --batch-size 64

# Crawl and ingest from a web page
uv run python scripts/crawl_url.py --url https://example.com/docs --depth 1
```

### Start the API Server

```bash
uv run uvicorn enterprise_rag.api:app --host 0.0.0.0 --port 8080
```

### Query

```bash
# CLI query
uv run python scripts/query.py --q "Was ist die aktuelle Richtlinie?" --k 8

# API request
curl -X POST http://localhost:8080/search \
  -H "Content-Type: application/json" \
  -d '{"query": "Was ist die aktuelle Richtlinie?", "k": 8}'
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness check |
| `GET` | `/health/ready` | Readiness check (PostgreSQL, Redis, Neo4j) |
| `POST` | `/ingest` | Ingest a single document |
| `GET` | `/ingest/{job_id}` | Check async ingestion job status |
| `POST` | `/crawl` | Crawl a web page for document links |
| `POST` | `/crawl/stream` | Streaming crawl progress (SSE) |
| `POST` | `/search` | Search with structured JSON response |
| `POST` | `/search/stream` | Search with streaming SSE response |
| `POST` | `/feedback` | Submit user feedback |

### Search Request

```json
{
  "query": "Was ist die aktuelle Richtlinie?",
  "k": 8,
  "categories": ["security"],
  "llmModel": "instruct",
  "embeddingModel": "qwen"
}
```

### Streaming Response (SSE)

```
event: meta
data: {"complexity": "simple", "hit_count": 42}

event: sources
data: [{"title": "Richtlinie 2024", "page_start": 3, ...}]

event: chunk
data: {"text": "Die aktuelle Richtlinie besagt..."}

event: done
data: {}
```

## Configuration

Configuration is managed via environment variables. Copy `.env.example` for a full reference.

### Key Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `PG_DSN` | `localhost:5432` | PostgreSQL connection string |
| `LLM_MODEL` | `qwen3-32b-instruct` | Primary LLM model |
| `LLM_CONTEXT_LENGTH` | `16000` | LLM context window size |
| `EMBED_MODEL` | `qwen3-embedding-8b` | Embedding model |
| `EMBED_DIM` | `4096` | Embedding dimensions |
| `RERANK_ENABLED` | `true` | Enable cross-encoder reranking |
| `CANDIDATES_BM25` | `120` | BM25 candidate pool size |
| `CANDIDATES_VEC` | `120` | Vector candidate pool size |
| `RERANK_KEEP` | `18` | Results kept after reranking |
| `WINDOW_PAGES` | `2` | Pages per sliding window |
| `WINDOW_STRIDE` | `1` | Window slide step |
| `DYNAMIC_CONTEXT` | `true` | Dynamic context sizing |

### Model Profiles

Set `MODEL_PROFILE` to apply presets:

| Profile | Context | Max Tokens | Use Case |
|---------|---------|------------|----------|
| `small` | 8K | 300 | Fast responses |
| `medium` | 16K | 500 | Balanced (default) |
| `large` | 32K | 800 | Comprehensive answers |

## Project Structure

```
├── enterprise_rag/
│   ├── api.py                     # FastAPI endpoints
│   ├── config.py                  # Settings and model profiles
│   ├── models.py                  # Shared data models
│   ├── db.py                      # PostgreSQL connection pool
│   ├── llm.py                     # LLM / embedding / reranker clients
│   ├── cache.py                   # Redis caching
│   ├── neo4j_amp.py               # Neo4j graph operations
│   ├── log.py                     # Structured logging
│   ├── telemetry.py               # OpenTelemetry tracing
│   ├── ingestion/
│   │   ├── extractors.py          # PDF/DOCX/XLSX/HTML extraction
│   │   ├── normalize.py           # Text cleanup
│   │   ├── segment.py             # Sliding-window chunking
│   │   ├── citations.py           # Reference extraction
│   │   ├── versioning.py          # Document deduplication
│   │   ├── crawler.py             # Web crawler
│   │   └── ingest.py              # Ingestion orchestration
│   ├── retrieval/
│   │   ├── hybrid.py              # Search orchestration
│   │   ├── query_plan.py          # LLM query rewriting
│   │   ├── postgres_retrieval.py  # BM25 + vector search
│   │   ├── rerank.py              # Cross-encoder reranking
│   │   ├── citation_expand.py     # Citation graph traversal
│   │   └── complexity.py          # Query complexity analysis
│   └── reasoning/
│       ├── pack.py                # Context packing
│       └── evidence.py            # Answer generation
├── scripts/
│   ├── init_db.py                 # Database initialization
│   ├── ingest_folder.py           # Bulk document ingestion
│   ├── embed_windows.py           # Embedding backfill
│   ├── query.py                   # CLI query interface
│   ├── crawl_url.py               # Web crawler CLI
│   ├── evaluate.py                # Evaluation suite
│   └── worker.py                  # Async job worker
├── sql/
│   └── schema.sql                 # Database schema
├── tests/                         # Test suite
├── docker-compose.yml             # Infrastructure services
├── pyproject.toml                 # Dependencies
└── .env.example                   # Configuration template
```

## Development

```bash
# Install with dev dependencies
uv sync --extra dev

# Code formatting
black --line-length 100 .

# Linting
ruff check .

# Type checking
mypy .

# Run tests
pytest

# Run single test
pytest tests/test_specific.py::test_function

# Run evaluation suite
uv run python scripts/evaluate.py --test-file tests/eval_cases.json --verbose
```

### Optional System Dependencies

For legacy `.doc` file support:

```bash
sudo apt install antiword    # Recommended
# or
sudo apt install catdoc      # Alternative
```
