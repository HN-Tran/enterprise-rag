# Architecture Review: Enterprise RAG System

This document provides an assessment of the current architecture's strengths, limitations, and recommendations for production scale.

## Strengths

### Retrieval Quality
- **Hybrid search** (BM25 + vector) is best practice - covers both lexical and semantic matching
- **Reranking step** significantly improves precision over raw retrieval
- **Evidence validation** (≥2 pieces required) reduces hallucination risk
- **Diversification** (max 2 per doc) prevents result clustering

### Architecture
- Clean separation of concerns: ingestion → retrieval → reasoning
- PostgreSQL + pgvector is a mature, battle-tested choice
- SHA256 deduplication at all levels prevents storage waste
- Sliding windows with configurable overlap handle context well
- Type-safe codebase (mypy strict) reduces runtime bugs

## Implemented Improvements

### Performance ✅
- **Connection pooling**: psycopg_pool in `enterprise_rag/db.py`
- **Redis caching**: Query plans and embeddings cached in Redis
- **Async job queue**: RQ-based ingestion and embedding workers
- **TEI cross-encoder reranking**: Fast CPU-based reranking with bge-reranker-v2-m3
- **Streaming responses**: Server-Sent Events for real-time answer delivery

### Observability ✅
- **Structured logging**: structlog with JSON output
- **Distributed tracing**: OpenTelemetry with Jaeger
- **Health endpoints**: `/health`, `/health/ready`, `/health/cache`

### Flexibility ✅
- **Model profiles**: small/medium/large presets for different LLM capabilities
- **Dynamic context sizing**: Adjusts limits based on query complexity
- **Deterministic query planning**: temperature=0.0 for reproducible results

## Remaining Concerns for Scale

### Database Bottlenecks
- Single PostgreSQL instance with no sharding strategy
- Binary-quantized vectors trade recall for speed - may hurt quality at scale
- HNSW index rebuild on large updates can be slow

### Still Missing for Production
- No authentication, rate limiting, or multi-tenancy
- External dashboards (Grafana) not yet configured
- Alerting for quality degradation (Alertmanager) not yet configured

### Architectural Questions
- Neo4j as "optional" is ambiguous - either it adds value (make it required) or it doesn't (remove it)

## Recommendations

| Priority | Status | Change |
|----------|--------|--------|
| High | ✅ Done | Redis for query/embedding caching |
| High | ✅ Done | Async ingestion queue (RQ) |
| High | ✅ Done | Connection pooling (psycopg_pool) |
| Medium | ✅ Done | Evaluation harness (precision/recall metrics) |
| Medium | ✅ Done | Observability (OpenTelemetry, structured logs) |
| Medium | Partial | Make blend ratio configurable per query |
| Low | Pending | Consider dedicated vector DB at 50M+ vectors |
| Medium | Pending | Authentication and rate limiting |

## Scalability Limits

### pgvector Scaling Reality

The system uses **binary quantization** (`embedding_bq` column), which significantly improves scalability:

```
Full precision (4096 dims): 4096 × 4 bytes = 16 KB per vector
Binary quantized:           4096 bits      = 512 bytes per vector (32x smaller)
```

**Storage requirements with binary quantization:**

| Vectors | Storage (vectors only) | With HNSW overhead |
|---------|------------------------|-------------------|
| 1M | ~512 MB | ~1-1.5 GB |
| 10M | ~5 GB | ~10-15 GB |
| 50M | ~25 GB | ~50-75 GB |

**RAM-based capacity estimates:**

| System RAM | Available for HNSW | Comfortable Limit | Max (degraded perf) |
|------------|-------------------|-------------------|---------------------|
| 16 GB | ~8-10 GB | 3-5M vectors | ~8M vectors |
| 32 GB | ~20-24 GB | 10-15M vectors | ~20M vectors |
| 64 GB | ~48-56 GB | 25-35M vectors | ~50M vectors |
| 128 GB | ~100-112 GB | 50-70M vectors | ~100M vectors |

*Available RAM = Total - OS (~2GB) - PostgreSQL base (~2-4GB) - shared_buffers (25% of RAM)*

**16 GB RAM edge case:**
- OS + PostgreSQL overhead: ~4-6 GB
- shared_buffers (recommended 4GB): ~4 GB
- Remaining for HNSW: ~6-8 GB
- At ~1.5 GB per 1M binary-quantized vectors → **3-5M vectors comfortable**
- Beyond 5M: index may spill to disk, query latency increases significantly
- Concurrent queries will compete for limited memory

**Performance factors (not hard limits):**
- RAM: HNSW index performs best when fitting in memory
- Index build time: Hours at 10M+, plan for maintenance windows
- Concurrent load: Single query fine at 50M; 100 concurrent queries degrades
- PostgreSQL tuning: shared_buffers, effective_cache_size, maintenance_work_mem

### Current Architecture Capacity

With binary quantization and proper hardware (64GB+ RAM):
- **Documents**: Hundreds of thousands to millions
- **Vectors**: 10-30M comfortably, 50M+ with tuning
- **QPS**: Low-to-medium (~10 sustained) due to LLM query planning latency
- **Ingestion**: Batch-oriented, not continuous

### Bottleneck Thresholds

| Component | Practical Limit | Symptom | Mitigation |
|-----------|-----------------|---------|------------|
| pgvector HNSW | 50M+ vectors | Slow index rebuilds, memory pressure | Dedicated vector DB (Qdrant/Milvus) |
| Query planning | ~10 QPS | Latency spikes, LLM rate limits | Cache, skip for simple queries |
| Sync embedding | Continuous ingestion | Backlog accumulation | Async queue (Celery/RQ) |
| Single Postgres | ~100 concurrent connections | Connection exhaustion | pgbouncer pooling |

### When to Consider Dedicated Vector DB

Switch from pgvector when:
- Index rebuilds take too long for your maintenance windows
- You need distributed/multi-node architecture
- Concurrent query performance degrades under load
- You exceed 50M vectors with high QPS requirements

**Not because of a hard limit** - pgvector with binary quantization scales well into tens of millions.

## Verdict

**Will it work?** Yes, for moderate to medium scale.

**Will it scale?** Yes for 10K-100K documents. Beyond that, evaluate dedicated vector DB.

**What's right:** The RAG fundamentals - hybrid search, TEI reranking, evidence validation, operational infrastructure.

**What's been added:** Caching, queuing, pooling, observability, streaming, model profiles.

**What's still needed for enterprise:** Authentication, rate limiting, monitoring dashboards, alerting.
