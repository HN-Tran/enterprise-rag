-- Migration: Add nomic embedding column for faster query embedding
-- nomic-embed-text has 768 dimensions vs qwen3-embedding-8b's 4096

-- Add nomic embedding column
ALTER TABLE windows ADD COLUMN IF NOT EXISTS embedding_nomic vector(768);

-- Binary quantization for ANN (generated column)
-- Note: PostgreSQL doesn't support IF NOT EXISTS for generated columns
-- This will fail if column exists, which is fine for migrations
DO $$
BEGIN
    ALTER TABLE windows ADD COLUMN embedding_nomic_bq bit(768)
        GENERATED ALWAYS AS (
            CASE
                WHEN embedding_nomic IS NULL THEN NULL
                ELSE binary_quantize(embedding_nomic)::bit(768)
            END
        ) STORED;
EXCEPTION
    WHEN duplicate_column THEN NULL;
END $$;

-- HNSW index for nomic embeddings (only rows with embeddings)
CREATE INDEX IF NOT EXISTS idx_windows_emb_nomic_hnsw
ON windows USING hnsw (embedding_nomic_bq bit_hamming_ops)
WHERE embedding_nomic_bq IS NOT NULL;
