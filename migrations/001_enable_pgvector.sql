-- Migration: Enable pgvector extension for PostgreSQL
-- This migration enables the pgvector extension required for vector database functionality
-- Run this as a PostgreSQL superuser if automatic extension creation fails

-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Verify extension is installed
SELECT extname, extversion 
FROM pg_extension 
WHERE extname = 'vector';

