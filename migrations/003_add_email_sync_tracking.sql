-- Add email sync tracking fields to users table

ALTER TABLE users ADD COLUMN last_email_synced_at TIMESTAMP;

-- Add index for faster queries
CREATE INDEX idx_users_last_sync ON users(last_email_synced_at);

-- Update comment
COMMENT ON COLUMN users.last_email_synced_at IS 'Timestamp of last successful email sync for incremental updates';

