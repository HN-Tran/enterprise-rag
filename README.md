# Enterprise RAG

German-language document retrieval and question answering with precise source attribution.

Built with Python 3.12, FastAPI, PostgreSQL+pgvector, and Neo4j.

## Quick Start

```bash
# 1. Start infrastructure
docker compose up -d

# 2. Install dependencies
uv sync

# 3. Initialize database
uv run python scripts/init_db.py

# 4. Configure environment
cp .env.example .env
# Edit .env with your LLM/embedding endpoints

# 5. Ingest documents
uv run python scripts/ingest_folder.py --folder /path/to/data --recursive

# 6. Generate embeddings
uv run python scripts/embed_windows.py --batch-size 64

# 7. Start API
uv run uvicorn enterprise_rag.api:app --host 0.0.0.0 --port 8080
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Liveness check |
| `/health/ready` | GET | Readiness check (all services) |
| `/search` | POST | Query documents |
| `/ingest` | POST | Ingest document |

```bash
# Example query
curl -X POST http://localhost:8080/search \
  -H "Content-Type: application/json" \
  -d '{"query": "Was sind die DSGVO Anforderungen?"}'
```

## Project Structure

```
enterprise_rag/
├── enterprise_rag/          # Main package
│   ├── api.py               # FastAPI endpoints
│   ├── config.py            # Settings (from .env)
│   ├── db.py                # PostgreSQL + connection pooling
│   ├── cache.py             # Redis caching layer
│   ├── llm.py               # LLM/embedding clients
│   ├── log.py               # Structured logging
│   ├── telemetry.py         # OpenTelemetry tracing
│   ├── neo4j_amp.py         # Neo4j graph operations
│   ├── ingestion/           # Document processing
│   ├── retrieval/           # Search pipeline
│   ├── reasoning/           # Answer generation
│   └── tasks/               # Background job queue
├── scripts/                 # CLI tools
├── sql/                     # Database schema
├── tests/                   # Test suite
└── docker-compose.yml       # Infrastructure
```

## Documentation

- **[USAGE.md](USAGE.md)** - Detailed usage guide
- **[ROADMAP.md](ROADMAP.md)** - Implementation phases
- **[CLAUDE.md](CLAUDE.md)** - Developer guidance
- **[ARCHITECTURE_REVIEW.md](ARCHITECTURE_REVIEW.md)** - System assessment

## Features

**Completed:**
- Hybrid search (BM25 + vector) with reranking
- Citation-aware answers with `[1]`, `[2]` references
- Cross-document citation chain traversal
- Connection pooling and Redis caching
- Async ingestion with job queue
- Structured logging and distributed tracing
- Health endpoints for monitoring

**Deferred:**
- Entity extraction (pending corpus analysis)
- Scale optimization (when needed)

## Requirements

- Python 3.12
- [uv](https://docs.astral.sh/uv/) package manager
- Docker & Docker Compose
- OpenAI-compatible LLM/embedding endpoints
