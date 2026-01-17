-- Migration: Create audit_logs table for security event tracking (SQLite version)
-- Date: 2025-11-16
-- Description: Add comprehensive audit logging for authentication and security events

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    event_type VARCHAR(50) NOT NULL,
    event_data TEXT,  -- JSON stored as TEXT in SQLite
    ip_address VARCHAR(45),
    user_agent VARCHAR(500),
    success INTEGER DEFAULT 1,  -- SQLite uses INTEGER for boolean (0=false, 1=true)
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
