-- Migration: Add OAuth States Table for CSRF Protection
-- Description: Creates oauth_states table to store OAuth CSRF states in database
--              instead of in-memory, fixing issues with server restarts and multi-worker setups
-- Date: 2025-11-17

-- Create oauth_states table
CREATE TABLE IF NOT EXISTS oauth_states (
    id SERIAL PRIMARY KEY,
    state VARCHAR(64) NOT NULL UNIQUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP NOT NULL,
    used BOOLEAN NOT NULL DEFAULT FALSE
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS ix_oauth_states_id ON oauth_states(id);
CREATE INDEX IF NOT EXISTS ix_oauth_states_state ON oauth_states(state);
CREATE INDEX IF NOT EXISTS ix_oauth_states_created_at ON oauth_states(created_at);
CREATE INDEX IF NOT EXISTS ix_oauth_states_expires_at ON oauth_states(expires_at);
CREATE INDEX IF NOT EXISTS ix_oauth_states_used ON oauth_states(used);

-- Composite index for efficient OAuth state validation
CREATE INDEX IF NOT EXISTS idx_oauth_state_validity ON oauth_states(state, used, expires_at);

-- Add comment
COMMENT ON TABLE oauth_states IS 'Stores OAuth CSRF states for database-backed session security';

SELECT 'OAuth states table created successfully' AS status;
