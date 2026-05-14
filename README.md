[English](README.md) · [Deutsch](README_DE.md)

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
┌─ INGESTION ──────────────────────┐    ┌─ RETRIEVAL ──────────────────────┐
│                                  │    │                                  │
│  File (PDF/DOCX/XLSX/HTML)       │    │  Query                           │
│   │                              │    │   │                              │
│   ├─ Text Extraction             │    │   ├─ Query Planning (LLM)        │
│   ├─ Normalization               │    │   │   └─ BM25 term extraction    │
│   ├─ Sliding-Window Segmentation │    │   │                              │
│   │   ├─ Windows (multi-page)    │    │   ├─ Candidate Generation        │
│   │   └─ Anchors (paragraphs,    │    │   │   ├─ BM25 full-text search   │
│   │       tables, lists)         │    │   │   └─ Vector similarity       │
│   └─ Citation Extraction         │    │   │                              │
│       (URLs, ISO refs, law refs) │    │   ├─ Hybrid Blending (55/45)     │
│                                  │    │   ├─ Cross-Encoder Reranking     │
│   ▼                              │    │   ├─ Per-Document Diversification│
│  PostgreSQL + Neo4j              │    │   └─ Citation Graph Expansion    │
│   ├─ documents, pages, windows   │    │                                  │
│   ├─ anchors, citations          │    └──────────────────────────────────┘
│   ├─ HNSW vector index           │
│   ├─ tsvector full-text index    │    ┌─ REASONING ──────────────────────┐
│   └─ CITES graph edges           │    │                                  │
│                                  │    │  Context Packing                 │
└──────────────────────────────────┘    │   ├─ Windows + Anchors           │
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
uv run python scripts/crawl_url.py https://example.com/docs --depth 1
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

## CLI Scripts

### init_db.py

Initialize the database schema from `sql/schema.sql`. No parameters.

```bash
uv run python scripts/init_db.py
```

### ingest_folder.py

Bulk ingest documents from the filesystem.

| Flag | Default | Description |
|------|---------|-------------|
| `--folder` | *required* | Folder to ingest from |
| `--recursive` | `true` | Include subfolders |
| `--type` | *all* | Only ingest specific type (`pdf`, `docx`, `xlsx`, `html`) |
| `--force` | `false` | Re-ingest even if file content hasn't changed |

```bash
uv run python scripts/ingest_folder.py --folder /data/docs --recursive --type pdf
```

### embed_windows.py

Backfill embeddings for all un-embedded windows.

| Flag | Default | Description |
|------|---------|-------------|
| `--batch-size` | `64` | Batch size for embedding |
| `--model` | *env default* | Embedding model profile to use |
| `--all` | `false` | Re-embed all windows, not just missing |
| `--workers` | `4` | Number of parallel workers |

```bash
uv run python scripts/embed_windows.py --batch-size 128 --workers 8
```

### query.py

CLI query interface for testing retrieval.

| Flag | Default | Description |
|------|---------|-------------|
| `--q` | *required* | Query text |
| `--k` | `8` | Number of results to show |
| `--timing` | `false` | Show timing breakdown |

```bash
uv run python scripts/query.py --q "DSGVO Anforderungen" --k 5 --timing
```

### crawl_url.py

Web crawler for extracting and ingesting documents from URLs.

| Flag | Default | Description |
|------|---------|-------------|
| `urls` | *positional* | URLs to crawl for document links |
| `-f`, `--file` | — | Read URLs from a text file (one per line) |
| `--dry-run` | `false` | Preview discovered links without downloading |
| `--download-dir` | *temp dir* | Directory to save downloaded files |
| `-q`, `--quiet` | `false` | Only show summary |
| `--follow-pages` | `false` | Follow HTML page links recursively (BFS) |
| `--depth` | — | Max BFS depth (required with `--follow-pages`) |
| `--max-pages` | *env default* | Max pages to visit during recursive crawl |
| `--pattern` | — | URL pattern with `{}` placeholder |
| `--start` | `1` | First number in pattern mode |
| `--end` | `9999` | Last number in pattern mode |
| `--pad-width` | `4` | Zero-padding width for pattern numbers |
| `--not-found-text` | — | Substring indicating "not found" (required with `--pattern`) |
| `--max-gaps` | `10` | Consecutive misses before stopping pattern crawl |
| `--mark-unseen` | `false` | Mark unmatched documents as orphaned after crawl |

```bash
# Recursive crawl
uv run python scripts/crawl_url.py https://example.com/docs --follow-pages --depth 2

# Pattern-based crawl
uv run python scripts/crawl_url.py --pattern "https://example.com/info?id={}" \
  --start 1 --end 500 --pad-width 1 --not-found-text "nicht gefunden" --dry-run
```

### evaluate.py

Run the evaluation suite against test cases.

| Flag | Default | Description |
|------|---------|-------------|
| `--test-file` | — | Path to test cases JSON file |
| `--output` | — | Path to save results JSON |
| `--create-sample` | `false` | Create a sample test cases file |
| `-v`, `--verbose` | `false` | Show progress during evaluation |

```bash
uv run python scripts/evaluate.py --test-file tests/eval_cases.json --verbose --output results.json
```

### worker.py

Redis queue worker for async ingestion tasks. Accepts queue names as positional arguments.

```bash
uv run python scripts/worker.py                     # All queues (default + embeddings)
uv run python scripts/worker.py default              # Default queue only
uv run python scripts/worker.py embeddings           # Embeddings queue only
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
├── scripts/                       # CLI tools (see CLI Scripts section)
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
```

### Optional System Dependencies

For legacy `.doc` file support:

```bash
sudo apt install antiword    # Recommended
# or
sudo apt install catdoc      # Alternative
```

## Author

HN-Tran — <https://github.com/HN-Tran>

## License

Apache-2.0 — see [`LICENSE`](LICENSE).
