-- Migration: Create user_settings table for user preferences
-- Created: 2025-11-13

-- Create user_settings table
CREATE TABLE IF NOT EXISTS user_settings (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL UNIQUE,
    email_notifications BOOLEAN NOT NULL DEFAULT FALSE,
    push_notifications BOOLEAN NOT NULL DEFAULT FALSE,
    dark_mode BOOLEAN NOT NULL DEFAULT TRUE,
    language VARCHAR(10) NOT NULL DEFAULT 'en',
    region VARCHAR(10) NOT NULL DEFAULT 'US',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_user_settings_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- Create index on user_id for faster lookups
CREATE INDEX IF NOT EXISTS idx_user_settings_user_id ON user_settings(user_id);

-- For SQLite compatibility (if using SQLite)
-- Note: SQLite doesn't support SERIAL, use INTEGER PRIMARY KEY AUTOINCREMENT instead
-- CREATE TABLE IF NOT EXISTS user_settings (
--     id INTEGER PRIMARY KEY AUTOINCREMENT,
--     user_id INTEGER NOT NULL UNIQUE,
--     email_notifications BOOLEAN NOT NULL DEFAULT 0,
--     push_notifications BOOLEAN NOT NULL DEFAULT 0,
--     dark_mode BOOLEAN NOT NULL DEFAULT 1,
--     language VARCHAR(10) NOT NULL DEFAULT 'en',
--     region VARCHAR(10) NOT NULL DEFAULT 'US',
--     created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
--     updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
--     FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
-- );
-- CREATE INDEX IF NOT EXISTS idx_user_settings_user_id ON user_settings(user_id);








