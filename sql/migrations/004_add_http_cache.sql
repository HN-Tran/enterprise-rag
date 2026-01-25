-- Migration: Add HTTP caching headers for conditional requests
-- This allows skipping downloads when server confirms content unchanged

ALTER TABLE documents ADD COLUMN IF NOT EXISTS http_etag TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS http_last_modified TEXT;
