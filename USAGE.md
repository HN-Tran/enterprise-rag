# Usage Guide

## Prerequisites

- Docker & Docker Compose
- Python 3.12 with [uv](https://docs.astral.sh/uv/)
- LLM/Embedding endpoints (OpenAI-compatible)

## 1. Initial Setup

```bash
# Start infrastructure (Postgres, Neo4j, Redis, Jaeger)
docker compose up -d

# Install dependencies
uv sync

# Initialize database schema
uv run python scripts/init_db.py

# Configure environment
cp .env.example .env
```

Edit `.env` with your endpoints:
```bash
# Required: Embedding service
EMBED_BASE_URL=http://localhost:11434/v1
EMBED_MODEL=qwen3-embedding-8b

# Required: LLM for query planning + answering
LLM_BASE_URL=http://localhost:11434/v1
LLM_MODEL=qwen3-32b-instruct

# Reranker - TEI with cross-encoder (runs via docker-compose)
RERANK_ENABLED=true
RERANK_BASE_URL=http://localhost:9001
RERANK_MODEL=BAAI/bge-reranker-v2-m3
```

## 2. Ingest Documents

Supported formats: **PDF, DOCX, XLSX, HTML**

```bash
# Single folder
uv run python scripts/ingest_folder.py --folder /path/to/documents

# Recursive (include subfolders)
uv run python scripts/ingest_folder.py --folder /path/to/documents --recursive
```

## 3. Generate Embeddings

After ingestion, generate vector embeddings for search:

```bash
uv run python scripts/embed_windows.py --batch-size 64
```

## 4. Query Documents

### CLI

```bash
uv run python scripts/query.py --q "Was sind die Anforderungen für Datenschutz?"
```

### API Server

```bash
# Start server
uv run uvicorn enterprise_rag.api:app --host 0.0.0.0 --port 8080
```

Query via HTTP:
```bash
curl -X POST http://localhost:8080/search \
  -H "Content-Type: application/json" \
  -d '{"query": "Was sind die DSGVO Anforderungen?"}'
```

## 5. API Reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Basic liveness check |
| `/health/ready` | GET | Readiness check (Postgres, Redis, Neo4j) |
| `/health/cache` | GET | Cache hit/miss statistics |
| `/search` | POST | Query documents |
| `/search/stream` | POST | Query with streaming response (SSE) |
| `/ingest` | POST | Ingest a single document |
| `/ingest/{job_id}` | GET | Check async ingestion status |

### Search Request

```json
{
  "query": "Your question here",
  "categories": ["optional", "filter"],
  "top_k": 10
}
```

### Search Response

```json
{
  "answer": "Generated answer with [1], [2] citations...",
  "confidence": "high",
  "sources": [
    {
      "id": "doc_abc123",
      "title": "Document Title",
      "pages": "12-14",
      "relevance": 0.92
    }
  ],
  "related_documents": [...]
}
```

### Streaming Response

For real-time answer generation, use the streaming endpoint:

```bash
curl -N -X POST http://localhost:8080/search/stream \
  -H "Content-Type: application/json" \
  -d '{"query": "Was sind die DSGVO Anforderungen?"}'
```

The response is Server-Sent Events (SSE) with these event types:
- `meta`: Query complexity and timing info
- `sources`: Retrieved source documents
- `chunk`: Answer text chunks (streamed as generated)
- `done`: Completion signal
- `error`: Error information if something fails

## 6. Monitoring

### Health Checks

```bash
# Basic health
curl http://localhost:8080/health

# Full readiness (checks all services)
curl http://localhost:8080/health/ready

# Cache statistics
curl http://localhost:8080/health/cache
```

### Distributed Tracing

Jaeger UI: http://localhost:16686

View request traces, latency breakdown, and service dependencies.

### Logs

Structured JSON logs when `LOG_JSON=true` (default). Example:

```json
{"event": "search_complete", "query": "...", "latency_ms": 234, "results": 10}
```

## 7. Background Workers (Optional)

For async ingestion (when `ASYNC_INGEST=true`):

```bash
# Start worker process
uv run python scripts/worker.py
```

Workers process ingestion and embedding jobs from Redis queue.

## 8. Evaluation

```bash
# Run evaluation suite
uv run python scripts/evaluate.py --test-file tests/eval_cases.json --verbose

# Create sample test cases
uv run python scripts/evaluate.py --create-sample
```

## Configuration Reference

Key settings in `.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `WINDOW_PAGES` | 2 | Pages per sliding window |
| `WINDOW_STRIDE` | 1 | Window overlap |
| `CANDIDATES_BM25` | 120 | BM25 retrieval candidates |
| `CANDIDATES_VEC` | 120 | Vector retrieval candidates |
| `RERANK_KEEP` | 18 | Results after reranking |
| `MAX_PER_DOC` | 2 | Max results per document |
| `CATEGORY_BOOST` | 1.20 | Boost for category matches |
| `DB_POOL_MIN` | 5 | Min database connections |
| `DB_POOL_MAX` | 20 | Max database connections |
| `CACHE_EMBED_TTL` | 86400 | Embedding cache TTL (seconds) |
| `CACHE_QUERY_TTL` | 3600 | Query cache TTL (seconds) |
| `MODEL_PROFILE` | (empty) | Model profile: small, medium, large |
| `DYNAMIC_CONTEXT` | true | Enable dynamic context sizing |
| `LLM_MAX_ANSWER_TOKENS` | 500 | Max tokens for answer generation |
| `RERANK_CHARS_PER_DOC` | 1500 | Chars sent to reranker per doc |

## Troubleshooting

### "vector type not found in database"

Run database initialization:
```bash
uv run python scripts/init_db.py
```

### Connection refused to Postgres

Check `.env` has correct port (default docker: 55432):
```bash
PG_DSN=postgresql://rag:rag@localhost:55432/ragdb
```

### Slow queries

1. Ensure embeddings are generated: `uv run python scripts/embed_windows.py`
2. Check Redis is running: `docker compose ps`
3. Review Jaeger traces for bottlenecks
