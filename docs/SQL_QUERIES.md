# Common SQL Queries

Useful queries for managing and debugging the Enterprise RAG system.

## Document Statistics

```sql
-- Total documents
SELECT COUNT(*) FROM documents;

-- Documents by source type
SELECT source_type, COUNT(*) FROM documents GROUP BY source_type ORDER BY COUNT(*) DESC;

-- Documents by current/archived status
SELECT is_current, COUNT(*) FROM documents GROUP BY is_current;

-- Unique documents by content hash
SELECT COUNT(DISTINCT sha256) FROM documents;
```

## Duplicate Detection

```sql
-- Find duplicate documents (same content, different paths)
SELECT sha256, COUNT(*) as cnt
FROM documents
GROUP BY sha256
HAVING COUNT(*) > 1
ORDER BY cnt DESC
LIMIT 20;

-- Total duplicate count
SELECT SUM(cnt - 1) as duplicate_count FROM (
  SELECT sha256, COUNT(*) as cnt
  FROM documents
  GROUP BY sha256
  HAVING COUNT(*) > 1
) sub;

-- Compare duplicates side by side
SELECT doc_id, title, uri, source_type, created_at, source_url, is_current
FROM documents
WHERE sha256 = '<SHA256_HASH>'
ORDER BY created_at;
```

## Duplicate Cleanup

```sql
-- Delete duplicates, keep OLDEST (first ingested)
DELETE FROM documents d
WHERE EXISTS (
  SELECT 1 FROM documents d2
  WHERE d2.sha256 = d.sha256
  AND d2.created_at < d.created_at
);

-- Delete duplicates, keep NEWEST (last ingested)
DELETE FROM documents d
WHERE EXISTS (
  SELECT 1 FROM documents d2
  WHERE d2.sha256 = d.sha256
  AND d2.created_at > d.created_at
);
```

## Crawler-Related Queries

```sql
-- Documents added via crawler (have source_url)
SELECT COUNT(*) FROM documents WHERE source_url IS NOT NULL;

-- Documents ingested locally (no source_url)
SELECT COUNT(*) FROM documents WHERE source_url IS NULL;

-- Documents by source URL (which pages they came from)
SELECT source_url, COUNT(*)
FROM documents
WHERE source_url IS NOT NULL
GROUP BY source_url
ORDER BY COUNT(*) DESC;

-- Delete all crawled documents (revert crawl)
DELETE FROM documents WHERE source_url IS NOT NULL;
```

## Versioning & Archival

```sql
-- Current (active) documents
SELECT COUNT(*) FROM documents WHERE is_current = TRUE;

-- Archived documents
SELECT COUNT(*) FROM documents WHERE is_current = FALSE;

-- Archived documents by reason
SELECT archive_reason, COUNT(*)
FROM documents
WHERE is_current = FALSE
GROUP BY archive_reason;

-- View version overlap log
SELECT * FROM version_overlap_log ORDER BY created_at DESC LIMIT 20;

-- Restore archived documents (by reason)
UPDATE documents
SET is_current = TRUE, archived_at = NULL, archive_reason = NULL
WHERE archive_reason = 'replaced';

-- Restore a specific document
UPDATE documents
SET is_current = TRUE, archived_at = NULL, archive_reason = NULL
WHERE doc_id = '<DOC_ID>';
```

## Embeddings Status

```sql
-- Windows without embeddings (need processing)
SELECT COUNT(*) FROM windows WHERE embedding IS NULL;

-- Windows with embeddings
SELECT COUNT(*) FROM windows WHERE embedding IS NOT NULL;

-- Documents with incomplete embeddings
SELECT d.doc_id, d.title,
       COUNT(w.window_id) as total_windows,
       COUNT(w.embedding) as embedded_windows
FROM documents d
JOIN windows w ON w.doc_id = d.doc_id
GROUP BY d.doc_id, d.title
HAVING COUNT(w.window_id) > COUNT(w.embedding);
```

## Storage & Size

```sql
-- Table sizes
SELECT
  relname as table_name,
  pg_size_pretty(pg_total_relation_size(relid)) as total_size
FROM pg_catalog.pg_statio_user_tables
ORDER BY pg_total_relation_size(relid) DESC;

-- Document count per table
SELECT
  (SELECT COUNT(*) FROM documents) as documents,
  (SELECT COUNT(*) FROM pages) as pages,
  (SELECT COUNT(*) FROM windows) as windows,
  (SELECT COUNT(*) FROM anchors) as anchors,
  (SELECT COUNT(*) FROM citations) as citations;
```

## Search & Debug

```sql
-- Find document by title (partial match)
SELECT doc_id, title, uri, created_at
FROM documents
WHERE title ILIKE '%search term%'
LIMIT 20;

-- Find document by URI
SELECT * FROM documents WHERE uri ILIKE '%filename%';

-- View windows for a document
SELECT window_id, page_start, page_end, LEFT(text, 100) as text_preview
FROM windows
WHERE doc_id = '<DOC_ID>'
ORDER BY page_start;

-- Full-text search on windows
SELECT w.window_id, d.title, LEFT(w.text, 200) as preview
FROM windows w
JOIN documents d ON d.doc_id = w.doc_id
WHERE w.tsv @@ websearch_to_tsquery('simple', 'search terms')
LIMIT 20;
```

## Maintenance

```sql
-- Vacuum and analyze (run periodically)
VACUUM ANALYZE documents;
VACUUM ANALYZE windows;

-- Reindex if search is slow
REINDEX INDEX idx_windows_tsv;
REINDEX INDEX idx_windows_embedding_hnsw;
```
