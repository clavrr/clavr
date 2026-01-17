-- Migration: Create user_writing_profiles table
-- Purpose: Store user email writing style profiles for personalized AI responses
-- Created: 2024
-- Dependencies: users table (from earlier migrations)

-- Create user_writing_profiles table
CREATE TABLE IF NOT EXISTS user_writing_profiles (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    
    -- Profile data (JSON from ProfileBuilder.build_profile())
    -- Contains: writing_style, response_patterns, preferences, common_phrases
    profile_data JSONB NOT NULL,
    
    -- Metadata
    sample_size INTEGER DEFAULT 0,  -- Number of emails analyzed
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC') NOT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC') NOT NULL,
    last_rebuilt_at TIMESTAMP WITHOUT TIME ZONE,  -- Last time profile was rebuilt
    
    -- Quality indicators
    confidence_score DOUBLE PRECISION,  -- 0.0-1.0, based on sample size and consistency
    needs_refresh BOOLEAN DEFAULT FALSE  -- Flag for background updates
);

-- Create indexes for common queries
CREATE INDEX IF NOT EXISTS idx_user_writing_profiles_user_id ON user_writing_profiles(user_id);
CREATE INDEX IF NOT EXISTS idx_user_writing_profiles_needs_refresh ON user_writing_profiles(needs_refresh);

-- Add updated_at trigger (to auto-update timestamp on changes)
CREATE OR REPLACE FUNCTION update_user_writing_profiles_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP AT TIME ZONE 'UTC';
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_user_writing_profiles_updated_at
    BEFORE UPDATE ON user_writing_profiles
    FOR EACH ROW
    EXECUTE FUNCTION update_user_writing_profiles_updated_at();

-- Comments for documentation
COMMENT ON TABLE user_writing_profiles IS 'User email writing style profiles for personalized AI responses';
COMMENT ON COLUMN user_writing_profiles.profile_data IS 'JSON data from ProfileBuilder containing writing_style, response_patterns, preferences, common_phrases';
COMMENT ON COLUMN user_writing_profiles.sample_size IS 'Number of sent emails analyzed to build this profile';
COMMENT ON COLUMN user_writing_profiles.confidence_score IS 'Profile quality score (0.0-1.0) based on sample size and consistency';
COMMENT ON COLUMN user_writing_profiles.needs_refresh IS 'Flag indicating profile should be rebuilt with updated sent emails';
