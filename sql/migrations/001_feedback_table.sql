-- Migration: Add feedback table for storing user feedback in PostgreSQL
-- Run with: psql $PG_DSN -f sql/migrations/001_feedback_table.sql

CREATE TABLE IF NOT EXISTS feedback (
    feedback_id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    query TEXT NOT NULL,
    answer TEXT NOT NULL,
    rating VARCHAR(10) NOT NULL,  -- 'up' or 'down'
    comment TEXT,
    category VARCHAR(100),
    embedding_model VARCHAR(50),
    sources JSONB,
    history JSONB,
    settings JSONB
);

CREATE INDEX IF NOT EXISTS idx_feedback_created ON feedback(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_feedback_rating ON feedback(rating);
