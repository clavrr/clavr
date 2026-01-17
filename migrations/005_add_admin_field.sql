-- Add is_admin field to users table

ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT FALSE NOT NULL;

-- Create index for admin queries
CREATE INDEX IF NOT EXISTS idx_users_is_admin ON users(is_admin);

-- Note: After running this migration, manually set admin users:
-- UPDATE users SET is_admin = TRUE WHERE email = 'admin@example.com';









