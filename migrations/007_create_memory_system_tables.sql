-- Migration: Create Memory System Tables
-- Purpose: Add tables for agent learning and pattern recognition
-- Date: 2025-11-16

-- Create query_patterns table for storing learned query patterns
CREATE TABLE IF NOT EXISTS query_patterns (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    pattern VARCHAR(500) NOT NULL,
    intent VARCHAR(100) NOT NULL,
    success_count INTEGER DEFAULT 0,
    failure_count INTEGER DEFAULT 0,
    confidence REAL DEFAULT 0.5,
    last_used TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for query_patterns
CREATE INDEX IF NOT EXISTS idx_query_patterns_user_id ON query_patterns(user_id);
CREATE INDEX IF NOT EXISTS idx_query_patterns_pattern ON query_patterns(pattern);
CREATE INDEX IF NOT EXISTS idx_query_patterns_intent ON query_patterns(intent);
CREATE INDEX IF NOT EXISTS idx_query_patterns_confidence ON query_patterns(confidence);
CREATE INDEX IF NOT EXISTS idx_query_patterns_user_pattern ON query_patterns(user_id, pattern);

-- Create execution_memory table for storing execution history
CREATE TABLE IF NOT EXISTS execution_memory (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    query TEXT NOT NULL,
    tools_used TEXT NOT NULL,  -- JSON string array
    success BOOLEAN NOT NULL,
    execution_time REAL DEFAULT 0.0,
    step_count INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for execution_memory
CREATE INDEX IF NOT EXISTS idx_execution_memory_user_id ON execution_memory(user_id);
CREATE INDEX IF NOT EXISTS idx_execution_memory_success ON execution_memory(success);
CREATE INDEX IF NOT EXISTS idx_execution_memory_created_at ON execution_memory(created_at);
CREATE INDEX IF NOT EXISTS idx_execution_memory_user_created ON execution_memory(user_id, created_at);

-- Add comments for documentation
COMMENT ON TABLE query_patterns IS 'Stores learned query patterns for agent optimization';
COMMENT ON TABLE execution_memory IS 'Stores execution history for agent learning';
COMMENT ON COLUMN query_patterns.pattern IS 'Normalized pattern extracted from query (e.g., "email_find_and_create")';
COMMENT ON COLUMN query_patterns.intent IS 'Detected intent category (e.g., "email", "tasks", "calendar")';
COMMENT ON COLUMN query_patterns.confidence IS 'Confidence score (0.1-1.0) based on success/failure ratio';
COMMENT ON COLUMN execution_memory.tools_used IS 'JSON array of tools used in execution (e.g., ["email", "tasks"])';
