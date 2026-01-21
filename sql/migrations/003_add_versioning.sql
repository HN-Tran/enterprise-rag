-- Migration 003: Document versioning and crawler metadata
-- Adds version tracking (is_current, archived_at) and crawler fields (source_url, download_url)

-- Versioning fields
ALTER TABLE documents ADD COLUMN IF NOT EXISTS is_current BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS archive_reason TEXT;  -- 'filename_pattern', 'folder_pattern', 'orphaned', 'replaced', 'manual'

-- Crawler metadata
ALTER TABLE documents ADD COLUMN IF NOT EXISTS source_url TEXT;      -- Page where link was found
ALTER TABLE documents ADD COLUMN IF NOT EXISTS download_url TEXT;    -- Direct file URL
ALTER TABLE documents ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ;  -- Last time found in crawl

-- Indexes for version filtering
CREATE INDEX IF NOT EXISTS idx_documents_is_current ON documents(is_current) WHERE is_current = TRUE;
CREATE INDEX IF NOT EXISTS idx_documents_source_url ON documents(source_url) WHERE source_url IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_documents_download_url ON documents(download_url) WHERE download_url IS NOT NULL;

-- Version overlap audit log
-- Tracks when documents were marked as non-current due to content overlap
CREATE TABLE IF NOT EXISTS version_overlap_log (
    id SERIAL PRIMARY KEY,
    new_doc_id TEXT NOT NULL,
    old_doc_id TEXT NOT NULL,
    embedding_similarity FLOAT NOT NULL,
    text_overlap FLOAT NOT NULL,
    action TEXT NOT NULL,  -- 'auto_archived', 'user_archived', 'ignored'
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_version_overlap_new_doc ON version_overlap_log(new_doc_id);
CREATE INDEX IF NOT EXISTS idx_version_overlap_old_doc ON version_overlap_log(old_doc_id);
