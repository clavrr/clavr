-- Migration: Create audit_logs table for security event tracking
-- Date: 2025-11-16
-- Description: Add comprehensive audit logging for authentication and security events

CREATE TABLE IF NOT EXISTS audit_logs (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    event_type VARCHAR(50) NOT NULL,
    event_data JSONB,
    ip_address VARCHAR(45),
    user_agent VARCHAR(500),
    success BOOLEAN DEFAULT true,
    error_message TEXT,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT (NOW() AT TIME ZONE 'utc')
);

-- Indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_audit_logs_user_id ON audit_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_event_type ON audit_logs(event_type);
CREATE INDEX IF NOT EXISTS idx_audit_logs_success ON audit_logs(success);
CREATE INDEX IF NOT EXISTS idx_audit_logs_created_at ON audit_logs(created_at);

-- Composite indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_audit_user_event_time 
    ON audit_logs(user_id, event_type, created_at);

CREATE INDEX IF NOT EXISTS idx_audit_event_success_time 
    ON audit_logs(event_type, success, created_at);

CREATE INDEX IF NOT EXISTS idx_audit_ip_time 
    ON audit_logs(ip_address, created_at);

-- Add comment for documentation
COMMENT ON TABLE audit_logs IS 'Audit log for security and authentication events';
COMMENT ON COLUMN audit_logs.event_type IS 'Type of event: login_success, login_failure, logout, token_refresh_success, etc.';
COMMENT ON COLUMN audit_logs.event_data IS 'Additional event-specific data in JSON format';
COMMENT ON COLUMN audit_logs.ip_address IS 'Client IP address (IPv4 or IPv6)';
COMMENT ON COLUMN audit_logs.success IS 'Whether the event was successful';
