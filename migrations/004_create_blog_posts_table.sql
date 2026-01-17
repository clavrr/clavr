-- Create blog_posts table for blog management

CREATE TABLE IF NOT EXISTS blog_posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title VARCHAR(500) NOT NULL,
    slug VARCHAR(500) NOT NULL UNIQUE,
    description TEXT,
    content TEXT NOT NULL,
    category VARCHAR(100) NOT NULL,
    author_id INTEGER,
    featured_image_url TEXT,
    is_published BOOLEAN DEFAULT FALSE,
    published_at TIMESTAMP,
    meta_title VARCHAR(500),
    meta_description TEXT,
    tags JSON,
    read_time_minutes INTEGER DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (author_id) REFERENCES users(id)
);

-- Create indexes for better query performance
CREATE INDEX IF NOT EXISTS idx_blog_slug ON blog_posts(slug);
CREATE INDEX IF NOT EXISTS idx_blog_published ON blog_posts(is_published, published_at);
CREATE INDEX IF NOT EXISTS idx_blog_category ON blog_posts(category);
CREATE INDEX IF NOT EXISTS idx_blog_category_published ON blog_posts(category, is_published);
CREATE INDEX IF NOT EXISTS idx_blog_created_at ON blog_posts(created_at);

-- For PostgreSQL, use proper types
-- Note: This migration works for SQLite. For PostgreSQL, you may want to:
-- - Use SERIAL instead of INTEGER PRIMARY KEY AUTOINCREMENT
-- - Use TIMESTAMP WITH TIME ZONE instead of TIMESTAMP
-- - Use JSONB instead of JSON for tags (better performance)









