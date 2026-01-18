-- Enterprise RAG schema (pgvector) for 4096-d embeddings + production ingest flow
-- Ingest stores text/metadata first, embeddings can be backfilled later.
-- ANN uses HNSW over binary-quantized vectors (bit) with partial index.

CREATE EXTENSION IF NOT EXISTS vector;

-- ---------- updated_at trigger ----------
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS trigger AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ---------- documents ----------
CREATE TABLE IF NOT EXISTS documents (
  doc_id      TEXT PRIMARY KEY,
  title       TEXT NOT NULL,
  source_type TEXT NOT NULL,
  uri         TEXT,
  sha256      TEXT NOT NULL,
  category    TEXT,
  categories  TEXT[],
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

DROP TRIGGER IF EXISTS trg_documents_updated_at ON documents;
CREATE TRIGGER trg_documents_updated_at
BEFORE UPDATE ON documents
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

-- Helpful for dedupe/lookups by hash
CREATE INDEX IF NOT EXISTS idx_documents_sha256 ON documents(sha256);


-- ---------- pages ----------
CREATE TABLE IF NOT EXISTS pages (
  page_id   BIGSERIAL PRIMARY KEY,
  doc_id    TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
  page_no   INT  NOT NULL,
  text      TEXT NOT NULL,

  -- GENERATED: do not write to this column from app code
  tsv       tsvector GENERATED ALWAYS AS (to_tsvector('simple', coalesce(text, ''))) STORED,

  sha256    TEXT NOT NULL,
  UNIQUE (doc_id, page_no)
);

CREATE INDEX IF NOT EXISTS idx_pages_doc        ON pages(doc_id);
CREATE INDEX IF NOT EXISTS idx_pages_doc_page   ON pages(doc_id, page_no);
CREATE INDEX IF NOT EXISTS idx_pages_tsv        ON pages USING GIN (tsv);


-- ---------- windows ----------
CREATE TABLE IF NOT EXISTS windows (
  window_id   BIGSERIAL PRIMARY KEY,
  doc_id      TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
  page_start  INT  NOT NULL,
  page_end    INT  NOT NULL,
  text        TEXT NOT NULL,

  -- GENERATED: do not write to this column from app code
  tsv         tsvector GENERATED ALWAYS AS (to_tsvector('simple', coalesce(text, ''))) STORED,

  -- Embeddings are backfilled later (nullable)
  -- Qwen3 embedding (4096 dims) - high quality, slower
  embedding   vector(4096),

  -- Binary quantization for ANN (nullable until embedding is present)
  embedding_bq bit(4096)
    GENERATED ALWAYS AS (
      CASE
        WHEN embedding IS NULL THEN NULL
        ELSE binary_quantize(embedding)::bit(4096)
      END
    ) STORED,

  -- Nomic embedding (768 dims) - faster, smaller
  embedding_nomic vector(768),

  embedding_nomic_bq bit(768)
    GENERATED ALWAYS AS (
      CASE
        WHEN embedding_nomic IS NULL THEN NULL
        ELSE binary_quantize(embedding_nomic)::bit(768)
      END
    ) STORED,

  sha256      TEXT NOT NULL,

  UNIQUE (doc_id, page_start, page_end),
  CHECK (page_start <= page_end)
);

CREATE INDEX IF NOT EXISTS idx_windows_doc           ON windows(doc_id);
CREATE INDEX IF NOT EXISTS idx_windows_doc_pages     ON windows(doc_id, page_start, page_end);
CREATE INDEX IF NOT EXISTS idx_windows_tsv           ON windows USING GIN (tsv);

-- HNSW ANN index for binary vectors (only rows with embeddings)
CREATE INDEX IF NOT EXISTS idx_windows_emb_bq_hnsw
ON windows
USING hnsw (embedding_bq bit_hamming_ops)
WHERE embedding_bq IS NOT NULL;

-- HNSW ANN index for nomic embeddings
CREATE INDEX IF NOT EXISTS idx_windows_emb_nomic_hnsw
ON windows
USING hnsw (embedding_nomic_bq bit_hamming_ops)
WHERE embedding_nomic_bq IS NOT NULL;


-- ---------- anchors ----------
CREATE TABLE IF NOT EXISTS anchors (
  anchor_id     BIGSERIAL PRIMARY KEY,
  doc_id        TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
  page_no       INT  NOT NULL,
  anchor_type   TEXT NOT NULL,
  start_offset  INT  NOT NULL,
  end_offset    INT  NOT NULL,
  text          TEXT NOT NULL,
  sha256        TEXT NOT NULL,

  CHECK (start_offset >= 0),
  CHECK (end_offset >= start_offset)
);

CREATE INDEX IF NOT EXISTS idx_anchors_doc          ON anchors(doc_id);
CREATE INDEX IF NOT EXISTS idx_anchors_doc_page     ON anchors(doc_id, page_no);

-- Optional: avoid duplicate spans
CREATE UNIQUE INDEX IF NOT EXISTS uq_anchors_span
ON anchors(doc_id, page_no, anchor_type, start_offset, end_offset);


-- ---------- citations ----------
-- Tracks references/links between documents for citation chain traversal
CREATE TABLE IF NOT EXISTS citations (
  citation_id   BIGSERIAL PRIMARY KEY,
  source_doc_id TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
  target_doc_id TEXT REFERENCES documents(doc_id) ON DELETE SET NULL,

  citation_type TEXT NOT NULL,    -- 'url', 'iso', 'law', 'internal_ref'
  raw_text      TEXT NOT NULL,    -- Original text containing the citation
  normalized_ref TEXT NOT NULL,   -- Cleaned/normalized reference
  page_no       INT NOT NULL,
  char_offset   INT,              -- Character offset in page text

  target_uri    TEXT,             -- External URL if applicable
  resolved      BOOLEAN NOT NULL DEFAULT FALSE,
  confidence    REAL NOT NULL DEFAULT 1.0,

  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),

  UNIQUE (source_doc_id, normalized_ref, page_no)
);

CREATE INDEX IF NOT EXISTS idx_citations_source ON citations(source_doc_id);
CREATE INDEX IF NOT EXISTS idx_citations_target ON citations(target_doc_id);
CREATE INDEX IF NOT EXISTS idx_citations_unresolved ON citations(resolved) WHERE resolved = FALSE;
