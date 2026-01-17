# Clavr API Documentation

Complete API reference for the Clavr Intelligent Email AI Agent platform.

**Base URL:** `http://localhost:8000`  
**API Version:** 2.0.0  
**Documentation:** [Interactive Swagger UI](http://localhost:8000/docs)

---

## Table of Contents

1. [Overview](#overview)
2. [Authentication](#authentication)
3. [Endpoints](#endpoints)
   - [Health & Status](#health--status)
   - [Authentication](#authentication-endpoints)
   - [Chat & Queries](#chat--queries)
   - [AI Features](#ai-features)
   - [Profile Management](#profile-management)
   - [Dashboard](#dashboard)
   - [Blog Management](#blog-management)
   - [Admin Endpoints](#admin-endpoints)
   - [Data Export (GDPR)](#data-export-gdpr)
   - [Webhooks](#webhooks)
4. [Ghost Collaborator](#ghost-collaborator)
5. [Proactive Insights](#proactive-insights)
6. [Relationship Analytics](#relationship-analytics)
7. [Knowledge Graph](#knowledge-graph)
8. [Gmail Push Notifications](#gmail-push-notifications)
9. [Voice Interactions](#voice-interactions)
10. [Request/Response Models](#requestresponse-models)
11. [Error Handling](#error-handling)
12. [Rate Limiting](#rate-limiting)

---

## Overview

Clavr is an intelligent email AI agent with proactive intelligence, multi-step reasoning, and autonomous workflow orchestration. The API provides RESTful endpoints for:

- Email management and search
- Calendar and task integration
- AI-powered features (auto-reply, analysis, summarization, meeting prep)
- User writing style profiles
- Dashboard statistics and analytics
- Blog content management (admin)
- Admin user management
- GDPR-compliant data export
- Webhook subscriptions and event notifications
- Knowledge graph and GraphRAG analytics
- Gmail push notifications for real-time email indexing

### Features

- **LangGraph Router** - Multi-step reasoning with context awareness and conversation memory
- **Entity Resolution** - Real email extraction from indexed emails
- **Proactive Intelligence** - Background monitors for conflicts, urgent emails, deadlines
- **Tool Orchestration** - Multi-tool workflows with templates for complex tasks
- **RAG Search** - PostgreSQL/ChromaDB vector store for semantic email search
- **Knowledge Graph** - GraphRAG for spending analysis, vendor insights, and receipt trends
- **Writing Style Profiles** - Personalized AI responses matching your writing style
- **Webhooks** - Real-time event notifications with HMAC signatures
- **Rate Limiting** - Configurable rate limits per minute and per hour
- **CSRF Protection** - Token-based CSRF protection for state-changing operations

---

## Authentication

Clavr uses OAuth 2.0 with Google for authentication. After successful login, API requests must include a session token.

### Session Token

Include the session token in requests using one of the following methods:

**Header:**
```
X-Session-Token: <your-session-token>
```

**Cookie:**
```
Cookie: session_token=<your-session-token>
```

**Bearer Token (Alternate):**
```
Authorization: Bearer <your-session-token>
```

### Getting a Session Token

1. Initiate OAuth flow at `/auth/google/login`
2. Complete authentication with Google
3. Redirect to callback endpoint `/auth/google/callback`
4. Session token is returned and stored
5. Use token in subsequent API requests

---

## Endpoints

### Health & Status

#### `GET /health`

Check system health and configuration status.

**Authentication:** Not required

**Response:**
```json
{
  "status": "healthy",
  "config_loaded": true,
  "rag_available": true,
  "timestamp": "2024-01-01T12:00:00"
}
```

**Status Codes:**
- `200` - System is healthy
- `503` - System is unhealthy

---

#### `GET /`

Root endpoint with API information.

**Authentication:** Not required

**Response:**
```json
{
  "message": "Email AI Agent API",
  "version": "2.0.0",
  "docs": "/docs",
  "health": "/health"
}
```

---

#### `GET /api/stats`
#### `GET /stats`

Get API usage statistics.

**Authentication:** Not required

**Response:**
```json
{
  "total_queries": 0,
  "active_users": 0,
  "uptime_hours": 0,
  "message": "Stats tracking coming soon"
}
```

---

### Authentication Endpoints

#### `GET /auth/google`
#### `GET /auth/google/login`

Initiate Google OAuth flow.

**Authentication:** Not required

**Rate Limit:** 10 requests per minute per IP (for `/auth/google/login`)

**Response:**
- Redirect (302) to Google authorization page

**Flow:**
1. User clicks login
2. Redirects to Google
3. User authorizes
4. Google redirects to `/auth/google/callback`

**Note:** Both endpoints are available. `/auth/google/login` includes rate limiting.

---

#### `GET /auth/google/callback`

Handle OAuth callback from Google.

**Authentication:** Not required

**Rate Limit:** 5 requests per minute per IP

**Query Parameters:**
- `code` (string, required) - Authorization code from Google
- `state` (string, optional) - CSRF state token

**Response:**
- Redirect (302) to frontend with session token

**Flow:**
1. Exchange code for access token
2. Get user info from Google
3. Create/login user in database
4. Create session with token
5. Start background email indexing (for new users)
6. Redirect to frontend with token

---

#### `GET /auth/me`

Get current authenticated user information.

**Authentication:** Required

**Response:**
```json
{
  "id": 1,
  "email": "user@example.com",
  "name": "John Doe",
  "picture_url": "https://...",
  "created_at": "2024-01-01T12:00:00",
  "indexing_status": "completed",
  "email_indexed": true
}
```

**Status Codes:**
- `200` - Success
- `401` - Not authenticated

---

#### `POST /auth/logout`

Logout current user (delete all sessions).

**Authentication:** Required

**Response:**
```json
{
  "message": "Logged out successfully",
  "sessions_deleted": 3
}
```

**Status Codes:**
- `200` - Success
- `401` - Not authenticated

---

#### `GET /auth/status`

Check authentication system status.

**Authentication:** Not required

**Response:**
```json
{
  "oauth_configured": true,
  "redirect_uri": "http://localhost:8000/auth/google/callback",
  "status": "operational"
}
```

---

#### `GET /auth/indexing/progress`

Get email indexing progress for current user.

**Authentication:** Required

**Response:**
```json
{
  "user_id": 1,
  "indexing_status": "in_progress",
  "progress_percent": 65.5,
  "total_emails": 500,
  "emails_indexed": 327,
  "started_at": "2024-01-01T10:00:00Z",
  "estimated_completion": "2024-01-01T10:15:00Z"
}
```

---

#### `POST /auth/refresh-token`

Refresh OAuth access token.

**Authentication:** Required

**Response:**
```json
{
  "success": true,
  "message": "Token refreshed successfully",
  "expires_at": "2024-01-02T12:00:00Z"
}
```

---

#### `GET /auth/profile/stats`

Get user profile statistics.

**Authentication:** Required

**Response:**
```json
{
  "user": {
    "id": 1,
    "email": "user@example.com",
    "name": "John Doe"
  },
  "statistics": {
    "total_emails": 500,
    "total_tasks": 25,
    "total_events": 15
  }
}
```

---

### Chat & Queries

#### `POST /api/chat`

Smart chat endpoint with intelligent routing.

**Authentication:** Optional (enhanced features with auth)

**Request Body:**
```json
{
  "question": "Find urgent emails from last week",
  "max_results": 5
}
```

Or using `query` field:
```json
{
  "query": "What's in my calendar today?",
  "max_results": 10
}
```

**Parameters:**
- `question` (string, optional) - User question
- `query` (string, optional) - Alternative query field
- `max_results` (integer, 1-100, default: 5) - Maximum number of results

**Response:**
```json
{
  "answer": "I found 3 urgent emails from last week...",
  "sources": [
    {
      "index": 1,
      "subject": "URGENT: Project deadline",
      "sender": "manager@example.com",
      "date": "2024-01-05",
      "snippet": "The project deadline is approaching..."
    }
  ],
  "found_results": true
}
```

**Routing Logic:**
- Email actions → Unified query with email tools
- Task actions → Unified query with task tools
- Calendar actions → Unified query with calendar tools
- General questions → RAG-powered email search
- Clarification needed → Request more info

**Status Codes:**
- `200` - Success
- `400` - Invalid request
- `422` - Validation error
- `500` - Processing error

---

#### `POST /api/query`

Unified smart query endpoint with intelligent routing to ClavrAgent using LangGraph orchestration.

**Authentication:** Required

**Request Body:**
```json
{
  "query": "Schedule meeting with John tomorrow at 2pm",
  "max_results": 5
}
```

**Parameters:**
- `query` (string, required, 1-10000 chars) - User query
- `max_results` (integer, 1-100, optional, default: 5) - Maximum results

**Response:**
```json
{
  "query_type": "calendar_action",
  "answer": "I've scheduled a meeting with John for tomorrow at 2:00 PM.",
  "data": {
    "entities": {
      "person": "John",
      "time": "2024-01-02T14:00:00"
    },
    "confidence": 0.95,
    "suggestions": []
  },
  "success": true
}
```

**Query Types:**
- `email` - Email search and management
- `calendar` - Calendar events
- `task` - Task management
- `action` - General actions
- `clarification` - Needs more information

**Features:**
- LangGraph orchestration for multi-step queries
- Conversation memory integration
- Intelligent tool selection and dependency resolution
- Context-aware execution

**Status Codes:**
- `200` - Success
- `400` - Invalid request
- `401` - Not authenticated
- `422` - Validation error
- `500` - Processing error

---

#### `POST /api/query/stream`

Stream query execution with workflow events.

**Authentication:** Required

**Request Body:**
```json
{
  "query": "Find urgent emails and create tasks for them",
  "max_results": 5
}
```

**Response:**
- Streaming response with workflow events showing:
  - Agent reasoning steps
  - Tool calls and results
  - Progress updates
  - Final response text chunks

**Status Codes:**
- `200` - Success (streaming)
- `400` - Invalid request
- `401` - Not authenticated
- `500` - Processing error

---

### AI Features

#### `POST /api/ai/auto-reply`

Generate intelligent reply options for an email.

**Authentication:** Required (session-based)

**Request Body:**
```json
{
  "email_content": "Hello, can we reschedule our meeting?",
  "email_subject": "Meeting reschedule",
  "sender_name": "John Doe",
  "sender_email": "john@example.com",
  "num_options": 3
}
```

**Parameters:**
- `email_content` (string, required) - Email content
- `email_subject` (string, required) - Email subject
- `sender_name` (string, required) - Sender's name
- `sender_email` (string, required) - Sender's email
- `num_options` (integer, optional, default: 3) - Number of reply variations

**Response:**
```json
{
  "success": true,
  "replies": [
    "Hi John, absolutely! When works best for you?",
    "Hello John, no problem at all. What time would work better?",
    "Sure, John. Let me know your availability."
  ],
  "count": 3
}
```

**Reply Variations:**
- Professional tone
- Friendly tone
- Brief/concise tone

**Personalization:**
If you have built a writing style profile (`POST /api/profile/build`), replies will automatically match your writing style (70-85% match).

**Status Codes:**
- `200` - Success
- `400` - Invalid request
- `401` - No active session
- `500` - Generation error

---

#### `POST /api/ai/analyze-email`

Analyze email for sentiment, priority, intent, and urgency.

**Authentication:** Required (session-based)

**Request Body:**
```json
{
  "subject": "Project deadline approaching",
  "body": "We need to finish this project by Friday. Please prioritize.",
  "sender": "manager@example.com"
}
```

**Parameters:**
- `subject` (string, required) - Email subject
- `body` (string, required) - Email body
- `sender` (string, required) - Sender email

**Response:**
```json
{
  "success": true,
  "analysis": {
    "sentiment": "neutral",
    "sentiment_score": 0.1,
    "priority": "high",
    "priority_score": 0.85,
    "intent": "request",
    "action_required": true,
    "is_urgent": true,
    "urgency_reasons": ["deadline mentioned", "action verb present"],
    "category": "work",
    "tags": ["deadline", "priority", "project"],
    "estimated_response_time": "1 hour",
    "requires_human": true,
    "key_points": ["Project deadline Friday", "Priority action needed"],
    "suggested_actions": ["Reply with status update", "Block calendar time"]
  }
}
```

**Status Codes:**
- `200` - Success
- `400` - Invalid request
- `401` - No active session
- `500` - Analysis error

---

#### `POST /api/ai/summarize`

Summarize any document or email.

**Authentication:** Required (session-based)

**Request Body:**
```json
{
  "content": "Long document content...",
  "title": "Q4 Report",
  "doc_type": "text"
}
```

**Parameters:**
- `content` (string, required) - Content to summarize
- `title` (string, optional) - Document title
- `doc_type` (string, optional, default: "text") - Document type

**Response:**
```json
{
  "success": true,
  "summary": {
    "title": "Q4 Report",
    "summary": "The Q4 report shows strong growth...",
    "key_points": ["Revenue up 20%", "New clients added", "Expansion planned"],
    "topics": ["finance", "growth", "strategy"],
    "word_count": 1500,
    "reading_time": "6 minutes",
    "sentiment": "positive",
    "action_items": ["Review budget", "Plan expansion"],
    "important_dates": ["2024-12-31"],
    "important_numbers": ["$1.5M revenue"]
  }
}
```

**Status Codes:**
- `200` - Success
- `400` - Invalid request
- `401` - No active session
- `500` - Summarization error

---

#### `POST /api/ai/meeting-prep`

Generate pre-meeting brief with preparation materials.

**Authentication:** Required (session-based)

**Request Body:**
```json
{
  "meeting_title": "Q4 Planning",
  "meeting_time": "2024-01-15T10:00:00Z",
  "attendees": ["john@example.com", "jane@example.com"],
  "calendar_description": "Strategic planning for Q4"
}
```

**Parameters:**
- `meeting_title` (string, required) - Meeting title
- `meeting_time` (string, required) - ISO format meeting time
- `attendees` (array[string], required) - List of attendee emails
- `calendar_description` (string, optional) - Calendar description

**Response:**
```json
{
  "success": true,
  "brief": {
    "meeting_title": "Q4 Planning",
    "meeting_time": "2024-01-15T10:00:00Z",
    "attendees": ["john@example.com", "jane@example.com"],
    "agenda_items": ["Review Q3 performance", "Set Q4 goals", "Budget discussion"],
    "context_summary": "Previous emails mention...",
    "key_emails": [...],
    "talking_points": ["Revenue growth", "Team expansion"],
    "decisions_needed": ["Budget approval", "Timeline confirmation"],
    "preparation_tasks": ["Review financials", "Prepare projections"]
  }
}
```

**Status Codes:**
- `200` - Success
- `400` - Invalid request
- `401` - No active session
- `500` - Generation error

---

### Profile Management

#### `POST /api/profile/build`

Build or rebuild user's writing style profile from sent emails.

**Authentication:** Required

**Request Body:**
```json
{
  "max_emails": 100,
  "force_rebuild": false
}
```

**Parameters:**
- `max_emails` (integer, 10-500, default: 100) - Maximum number of sent emails to analyze
- `force_rebuild` (boolean, default: false) - Force rebuild even if recently updated

**Response:**
```json
{
  "status": "building",
  "message": "Profile is being built in the background. This may take a few minutes.",
  "profile": {
    "user_id": 1,
    "sample_size": 86,
    "confidence_score": 0.95,
    "created_at": "2024-01-01T12:00:00Z",
    "updated_at": "2024-01-01T12:00:00Z"
  }
}
```

**Note:** Profile building happens in the background. Check status with `GET /api/profile`.

**Status Codes:**
- `200` - Success (build initiated)
- `400` - Invalid request
- `401` - Not authenticated
- `500` - Build initiation failed

---

#### `GET /api/profile`

Get user's current writing style profile.

**Authentication:** Required

**Response:**
```json
{
  "user_id": 1,
  "profile_data": {
    "writing_style": {
      "tone": "professional",
      "formality_score": 5.8,
      "avg_word_count": 563
    },
    "common_phrases": ["Feel free to", "Thank you for"],
    "response_patterns": {...}
  },
  "sample_size": 86,
  "confidence_score": 0.95,
  "created_at": "2024-01-01T12:00:00Z",
  "updated_at": "2024-01-01T12:00:00Z"
}
```

**Status Codes:**
- `200` - Success
- `401` - Not authenticated
- `404` - Profile not found

---

#### `DELETE /api/profile`

Delete user's writing style profile.

**Authentication:** Required

**Response:**
- `204 No Content` - Profile deleted successfully

**Status Codes:**
- `204` - Success
- `401` - Not authenticated
- `404` - Profile not found

---

#### `GET /api/profile/stats`

Get dashboard statistics (alias for `/dashboard/stats`).

**Authentication:** Required

**Response:**
```json
{
  "unread_emails": 5,
  "todays_events": 3,
  "outstanding_tasks": 7,
  "last_updated": "2024-01-01T12:00:00Z"
}
```

---

### Dashboard

#### `GET /dashboard/stats`

Get dashboard statistics for the current user.

**Authentication:** Required

**Response:**
```json
{
  "unread_emails": 5,
  "todays_events": 3,
  "outstanding_tasks": 7,
  "last_updated": "2024-01-01T12:00:00Z",
  "errors": []
}
```

**Status Codes:**
- `200` - Success
- `401` - Not authenticated
- `500` - Failed to fetch stats

---

#### `GET /dashboard/overview`

Get detailed dashboard overview with additional insights.

**Authentication:** Required

**Response:**
```json
{
  "user_info": {
    "id": 1,
    "email": "user@example.com",
    "name": "John Doe"
  },
  "stats": {
    "unread_emails": 5,
    "todays_events": 3,
    "outstanding_tasks": 7
  },
  "services": {
    "email": {"available": true, "last_sync": "2024-01-01T11:00:00Z"},
    "calendar": {"available": true, "last_sync": "2024-01-01T11:00:00Z"},
    "tasks": {"available": true, "last_sync": "2024-01-01T11:00:00Z"}
  },
  "recent_activity": {
    "recent_emails": [...],
    "upcoming_events": [...],
    "urgent_tasks": [...]
  },
  "last_updated": "2024-01-01T12:00:00Z"
}
```

**Status Codes:**
- `200` - Success
- `401` - Not authenticated
- `500` - Failed to fetch overview

---

### Blog Management

Blog management endpoints are admin-only.

#### `POST /blog/posts`

Create a new blog post.

**Authentication:** Required (Admin only)

**Request Body:**
```json
{
  "title": "Blog Post Title",
  "description": "Subtitle/lead paragraph",
  "content": "Full blog post content (HTML or Markdown)",
  "category": "Product|Productivity|Education & AI|Business|Engineering",
  "is_published": false,
  "tags": ["tag1", "tag2"],
  "featured_image_url": "https://...",
  "meta_title": "SEO Title",
  "meta_description": "SEO Description"
}
```

**Response:**
```json
{
  "id": 1,
  "title": "Blog Post Title",
  "slug": "blog-post-title",
  "description": "Subtitle/lead paragraph",
  "content": "Full blog post content",
  "category": "Product",
  "is_published": false,
  "read_time_minutes": 5,
  "created_at": "2024-01-01T12:00:00Z",
  "updated_at": "2024-01-01T12:00:00Z"
}
```

**Status Codes:**
- `201` - Created
- `400` - Invalid request (e.g., duplicate slug)
- `401` - Not authenticated
- `403` - Not admin
- `422` - Validation error

---

#### `GET /blog/posts`

List blog posts with pagination and filtering.

**Authentication:** Not required (public endpoint)

**Query Parameters:**
- `page` (integer, default: 1) - Page number
- `page_size` (integer, 1-100, default: 10) - Items per page
- `category` (string, optional) - Filter by category
- `published_only` (boolean, default: true) - Only return published posts
- `search` (string, optional) - Search in title and content

**Response:**
```json
{
  "posts": [...],
  "total": 50,
  "page": 1,
  "page_size": 10,
  "total_pages": 5
}
```

---

#### `GET /blog/posts/{post_id}`

Get a single blog post by ID.

**Authentication:** Not required

**Response:**
```json
{
  "id": 1,
  "title": "Blog Post Title",
  "slug": "blog-post-title",
  "content": "...",
  "category": "Product",
  "is_published": true,
  "read_time_minutes": 5,
  "created_at": "2024-01-01T12:00:00Z"
}
```

---

#### `GET /blog/posts/slug/{slug}`

Get a blog post by slug (URL-friendly identifier).

**Authentication:** Not required

**Query Parameters:**
- `published_only` (boolean, default: true) - Only return if published

**Response:**
Same as `GET /blog/posts/{post_id}`

---

#### `PUT /blog/posts/{post_id}`

Update a blog post.

**Authentication:** Required (Admin only)

**Request Body:**
```json
{
  "title": "Updated Title",
  "content": "Updated content",
  "is_published": true
}
```

All fields are optional. Only provided fields will be updated.

**Status Codes:**
- `200` - Success
- `400` - Invalid request
- `401` - Not authenticated
- `403` - Not admin
- `404` - Post not found

---

#### `DELETE /blog/posts/{post_id}`

Delete a blog post.

**Authentication:** Required (Admin only)

**Status Codes:**
- `204` - Success
- `401` - Not authenticated
- `403` - Not admin
- `404` - Post not found

---

#### `GET /blog/categories`

Get list of all allowed blog categories.

**Authentication:** Not required

**Response:**
```json
["Product", "Productivity", "Education & AI", "Business", "Engineering"]
```

---

#### `GET /blog/categories/info`

Get detailed information about each blog category.

**Authentication:** Not required

**Response:**
```json
{
  "Product": {
    "description": "Product updates, feature announcements, roadmap",
    "content_types": [...]
  },
  "Productivity": {...}
}
```

---

#### `POST /blog/completion`

Generate text completion suggestions for blog writing.

**Authentication:** Required

**Request Body:**
```json
{
  "prompt": "Email has become...",
  "context": "Title: The Email Crisis\nCategory: Product",
  "max_tokens": 50,
  "temperature": 0.7,
  "cursor_position": 45
}
```

**Parameters:**
- `prompt` (string, required) - Text prompt to complete
- `context` (string, optional) - Context (title, category, existing content)
- `max_tokens` (integer, 5-200, default: 50) - Maximum tokens to generate
- `temperature` (float, 0.0-1.0, default: 0.7) - Creativity level
- `cursor_position` (integer, optional) - Cursor position in prompt

**Response:**
```json
{
  "completion": "both a blessing and a curse...",
  "prompt": "Email has become...",
  "tokens_generated": 12
}
```

**Status Codes:**
- `200` - Success
- `400` - Invalid request
- `401` - Not authenticated
- `500` - Generation failed

---

### Admin Endpoints

All admin endpoints require admin authentication.

#### `GET /admin/users`

List all users with pagination and search.

**Authentication:** Required (Admin only)

**Query Parameters:**
- `page` (integer, default: 1) - Page number
- `page_size` (integer, 1-100, default: 50) - Items per page
- `search` (string, optional) - Search by email or name
- `admin_only` (boolean, default: false) - Filter to admin users only

**Response:**
```json
{
  "users": [
    {
      "id": 1,
      "email": "user@example.com",
      "name": "John Doe",
      "is_admin": false,
      "created_at": "2024-01-01T12:00:00Z",
      "email_indexed": true,
      "indexing_status": "completed",
      "index_count": 500
    }
  ],
  "total": 150,
  "page": 1,
  "page_size": 50,
  "total_pages": 3
}
```

---

#### `GET /admin/users/{user_id}`

Get detailed user information.

**Authentication:** Required (Admin only)

**Response:**
```json
{
  "id": 1,
  "email": "user@example.com",
  "name": "John Doe",
  "is_admin": false,
  "created_at": "2024-01-01T12:00:00Z",
  "email_indexed": true,
  "indexing_status": "completed",
  "index_count": 500,
  "picture_url": "https://...",
  "indexing_started_at": "2024-01-01T10:00:00Z",
  "indexing_completed_at": "2024-01-01T10:15:00Z",
  "active_sessions": 2
}
```

---

#### `GET /admin/users/count`

Get user count statistics.

**Authentication:** Required (Admin only)

**Response:**
```json
{
  "total_users": 150,
  "admin_users": 3,
  "regular_users": 147
}
```

---

#### `PUT /admin/users/{user_id}/admin`

Grant or revoke admin status.

**Authentication:** Required (Admin only)

**Request Body:**
```json
{
  "is_admin": true
}
```

**Response:**
```json
{
  "id": 1,
  "email": "user@example.com",
  "is_admin": true
}
```

---

#### `DELETE /admin/users/{user_id}/sessions`

Revoke all sessions for a user.

**Authentication:** Required (Admin only)

**Response:**
- `204 No Content` - Sessions revoked

---

#### `GET /admin/stats`

Get platform-wide statistics.

**Authentication:** Required (Admin only)

**Response:**
```json
{
  "total_users": 150,
  "active_users_30d": 45,
  "admin_users": 3,
  "total_blog_posts": 25,
  "published_blog_posts": 20,
  "total_conversations": 5000,
  "users_with_indexed_emails": 120,
  "average_index_count": 450.5
}
```

---

#### `GET /admin/health/detailed`

Get detailed health information.

**Authentication:** Required (Admin only)

**Response:**
```json
{
  "status": "healthy",
  "database": "connected",
  "rag_engine": "available",
  "services": {
    "email": "operational",
    "calendar": "operational",
    "tasks": "operational"
  }
}
```

---

#### `GET /admin/profile-service/stats`

Get profile service statistics.

**Authentication:** Required (Admin only)

**Response:**
```json
{
  "total_profiles": 50,
  "profiles_needing_refresh": 5,
  "last_update_run": "2024-01-01T10:00:00Z"
}
```

---

#### `POST /admin/profile-service/trigger-update`

Manually trigger profile service update.

**Authentication:** Required (Admin only)

**Response:**
```json
{
  "success": true,
  "message": "Profile update service triggered"
}
```

---

#### `POST /admin/profile-service/mark-refresh/{user_id}`

Mark a user's profile as needing refresh.

**Authentication:** Required (Admin only)

**Response:**
```json
{
  "success": true,
  "message": "Profile marked for refresh"
}
```

---

### Data Export (GDPR)

GDPR-compliant data export endpoints (Article 20 - Right to Data Portability).

#### `POST /export/request`

Request a data export.

**Authentication:** Required

**Query Parameters:**
- `format` (string, default: "zip") - Export format: `json`, `csv`, or `zip`
- `include_vectors` (boolean, default: false) - Include vector embeddings (large!)
- `include_email_content` (boolean, default: true) - Include full email content

**Response (Small exports - immediate):**
```json
{
  "status": "success",
  "format": "json",
  "data": {...}
}
```

**Response (Large exports - background processing):**
```json
{
  "status": "processing",
  "message": "Export is being generated. Please use the download token to retrieve it.",
  "download_token": "abc123...",
  "download_url": "/api/export/download/abc123...",
  "estimated_time_seconds": 30,
  "expires_in_minutes": 60
}
```

**Status Codes:**
- `200` - Success (immediate export)
- `202` - Accepted (background processing)
- `400` - Invalid format
- `401` - Not authenticated
- `500` - Export failed

---

#### `GET /export/download/{token}`

Download a generated data export using a secure token.

**Authentication:** Not required (token-based)

**Path Parameters:**
- `token` (string, required) - Download token from export request

**Response:**
- File download (JSON, CSV, or ZIP)
- Content-Type: `application/json`, `text/csv`, or `application/zip`

**Status Codes:**
- `200` - Success
- `404` - Export not found or token expired
- `410` - Token expired

---

#### `DELETE /export/request`

Cancel any pending data export requests.

**Authentication:** Required

**Response:**
```json
{
  "status": "success",
  "message": "Cancelled 1 pending export(s)"
}
```

---

#### `GET /export/info`

Get information about available data export options.

**Authentication:** Required

**Response:**
```json
{
  "available_formats": ["json", "csv", "zip"],
  "data_categories": [
    {
      "name": "user_profile",
      "description": "Your account information and settings",
      "included_by_default": true
    },
    {
      "name": "emails",
      "description": "Your email data from Gmail",
      "included_by_default": true
    }
  ],
  "gdpr_compliance": {
    "regulation": "GDPR Article 20",
    "right": "Right to Data Portability"
  },
  "export_limits": {
    "max_emails": 10000,
    "token_expiry_minutes": 60
  }
}
```

---

### Webhooks

Webhook management endpoints for real-time event notifications.

#### `GET /api/webhooks/event-types`

Get list of all available webhook event types.

**Authentication:** Required

**Response:**
```json
[
  {
    "value": "email.received",
    "description": "Email received and indexed"
  },
  {
    "value": "email.sent",
    "description": "Email sent successfully"
  },
  {
    "value": "task.completed",
    "description": "Task marked as completed"
  }
]
```

**Available Event Types:**
- Email: `email.received`, `email.sent`, `email.indexed`
- Calendar: `calendar.event.created`, `calendar.event.updated`, `calendar.event.deleted`
- Tasks: `task.created`, `task.updated`, `task.completed`, `task.deleted`
- Indexing: `indexing.started`, `indexing.completed`, `indexing.failed`
- User: `user.created`, `user.settings.updated`
- System: `export.completed`, `sync.completed`

---

#### `POST /api/webhooks`

Create a webhook subscription.

**Authentication:** Required

**Request Body:**
```json
{
  "url": "https://example.com/webhook",
  "event_types": ["email.received", "task.completed"],
  "description": "Production webhook",
  "retry_count": 3,
  "timeout_seconds": 10
}
```

**Parameters:**
- `url` (string, required) - Webhook endpoint URL
- `event_types` (array[string], required) - List of event types to subscribe to
- `description` (string, optional) - Optional description
- `retry_count` (integer, 0-10, default: 3) - Maximum retry attempts
- `timeout_seconds` (integer, 1-60, default: 10) - Request timeout in seconds

**Response:**
```json
{
  "id": 1,
  "user_id": 1,
  "url": "https://example.com/webhook",
  "event_types": ["email.received", "task.completed"],
  "description": "Production webhook",
  "secret": "abc123...",
  "is_active": true,
  "retry_count": 3,
  "timeout_seconds": 10,
  "created_at": "2024-01-01T12:00:00Z",
  "total_deliveries": 0,
  "successful_deliveries": 0,
  "failed_deliveries": 0
}
```

**Important:** Save the `secret` value! It's only returned during creation and is used to verify webhook signatures.

**Status Codes:**
- `201` - Created
- `400` - Invalid request
- `401` - Not authenticated
- `422` - Validation error

---

#### `GET /api/webhooks`

List all webhook subscriptions for the current user.

**Authentication:** Required

**Response:**
```json
[
  {
    "id": 1,
    "url": "https://example.com/webhook",
    "event_types": ["email.received"],
    "is_active": true,
    "total_deliveries": 150,
    "successful_deliveries": 148,
    "failed_deliveries": 2
  }
]
```

---

#### `GET /api/webhooks/{subscription_id}`

Get webhook subscription details.

**Authentication:** Required

**Response:**
Same as `POST /api/webhooks` response

---

#### `PATCH /api/webhooks/{subscription_id}`

Update a webhook subscription.

**Authentication:** Required

**Request Body:**
```json
{
  "url": "https://new-url.com/webhook",
  "event_types": ["email.received", "email.sent"],
  "is_active": true,
  "retry_count": 5
}
```

All fields are optional. Only provided fields will be updated.

---

#### `DELETE /api/webhooks/{subscription_id}`

Delete a webhook subscription.

**Authentication:** Required

**Status Codes:**
- `204` - Success
- `401` - Not authenticated
- `404` - Subscription not found

---

#### `POST /api/webhooks/{subscription_id}/test`

Test a webhook endpoint.

**Authentication:** Required

**Response:**
```json
{
  "success": true,
  "message": "Test webhook delivered successfully",
  "status_code": 200,
  "response_body": "OK"
}
```

---

#### `GET /api/webhooks/{subscription_id}/deliveries`

Get webhook delivery history.

**Authentication:** Required

**Response:**
```json
[
  {
    "id": 1,
    "subscription_id": 1,
    "event_type": "email.received",
    "event_id": "msg-123456",
    "status": "success",
    "attempt_count": 1,
    "max_attempts": 3,
    "response_status_code": 200,
    "created_at": "2024-01-01T12:00:00Z",
    "completed_at": "2024-01-01T12:00:00Z"
  }
]
```

**Webhook Payload Format:**
```json
{
  "event_type": "email.received",
  "event_id": "msg-123456",
  "timestamp": "2024-01-15T10:30:00Z",
  "data": {
    "message_id": "msg-123456",
    "subject": "Meeting Reminder",
    "from": "john@example.com",
    "to": ["me@example.com"],
    "date": "2024-01-15T10:00:00Z",
    "body_preview": "..."
  }
}
```

**Security:**
- HMAC-SHA256 signatures in `X-Webhook-Signature` header
- Exponential backoff retry (2s → 4s → 8s)
- Delivery tracking with full history

---

### Ghost Collaborator

The Ghost Collaborator proactively drafts issues and tasks based on your conversations in Slack and other integrations.

#### `GET /api/ghost/drafts`

List all pending drafts for the Ghost Collaborator.

**Authentication:** Required

**Response:**
```json
[
  {
    "id": 1,
    "title": "[Integrate] Draft Title",
    "description": "Draft description from Slack thread...",
    "status": "draft",
    "integration_type": "linear",
    "confidence": 0.95,
    "source": "#project-alpha",
    "created_at": "2024-01-01T12:00:00Z"
  }
]
```

---

#### `POST /api/ghost/drafts/{draft_id}/approve`

Approve a draft and post it to the respective integration (e.g., Linear).

**Authentication:** Required

**Response:**
```json
{
  "status": "success",
  "entity_id": "LNR-123",
  "message": "Issue posted to Linear"
}
```

---

#### `POST /api/ghost/drafts/{draft_id}/dismiss`

Dismiss a draft suggestion.

**Authentication:** Required

**Response:**
```json
{
  "status": "success",
  "message": "Draft dismissed"
}
```

---

### Proactive Insights

Real-time intelligent situational awareness and cross-stack synthesis.

#### `GET /api/proactive/insights`

Get urgent insights, meeting preparation, and connection suggestions.

**Authentication:** Required

**Query Parameters:**
- `hours_ahead` (int, default: 4) - Lookahead window for meetings.
- `include_narrative` (bool, default: false) - Generate a rich LLM briefing.

**Response:**
```json
{
  "urgent": [...],
  "meeting_prep": [...],
  "connections": [...],
  "suggestions": [...],
  "briefing_narrative": "Good morning John...",
  "timestamp": "2024-01-01T12:00:00Z"
}
```

---

#### `GET /api/proactive/meeting-prep/{meeting_id}`

Get detailed preparation context for a specific meeting, including attendee history and related docs.

**Authentication:** Required

---

#### `GET /api/proactive/briefing`

Get a full morning briefing with AI-generated narrative and unified reminders (including Ghost drafts).

**Authentication:** Required

---

#### `GET /api/proactive/topic-context/{topic}`

**Semantic Sync**: Get 360° cross-stack context for a project or topic. Synthesizes data from Linear, Gmail, Slack, Notion, and Drive.

**Authentication:** Required

**Example Request:** `GET /api/proactive/topic-context/Project-Alpha`

**Response:**
```json
{
  "topic": "Project Alpha",
  "summary": "Project Alpha is currently in phase 2...",
  "key_facts": ["Deadline: Friday", "Lead: Jane Doe"],
  "sources": {
    "linear": [...],
    "gmail": [...],
    "notion": [...]
  },
  "action_items": [...],
  "generated_at": "2024-01-01T12:00:00Z"
}
```

---

### Relationship Analytics

Graph-driven communication and network analysis.

#### `GET /api/analytics/relationships`

Get top contacts by interaction frequency and relationship strength.

**Authentication:** Required

---

#### `GET /api/analytics/topics`

Get trending topics, clusters, and activity velocity.

**Authentication:** Required

---

#### `GET /api/analytics/report`

Comprehensive full analytics report (Relationships + Topics + Temporal + Cross-App).

**Authentication:** Required

---

### Knowledge Graph

Knowledge graph and GraphRAG endpoints for advanced analytics.

#### `POST /api/graph/search`

Graph-enhanced search combining knowledge graph + vector search.

**Authentication:** Required

**Request Body:**
```json
{
  "query": "Find all receipts from Amazon",
  "use_graph": true,
  "use_vector": true,
  "max_results": 10
}
```

**Parameters:**
- `query` (string, required) - Search query
- `use_graph` (boolean, default: true) - Enable graph traversal
- `use_vector` (boolean, default: true) - Enable vector search
- `max_results` (integer, 1-100, default: 10) - Maximum results

**Response:**
```json
{
  "success": true,
  "query": "Find all receipts from Amazon",
  "results": [
    {
      "node_id": "receipt_123",
      "node_type": "Receipt",
      "properties": {...},
      "relationships": [...]
    }
  ],
  "user_id": 1
}
```

---

#### `POST /api/graph/entity/search`

Find all items related to a specific entity.

**Authentication:** Required

**Request Body:**
```json
{
  "entity_type": "VENDOR",
  "entity_name": "Amazon",
  "relationship_type": "HAS_RECEIPT",
  "max_results": 10
}
```

**Response:**
```json
{
  "success": true,
  "entity_type": "VENDOR",
  "entity_name": "Amazon",
  "count": 15,
  "results": [...]
}
```

---

#### `POST /api/graph/analytics/spending`

GraphRAG-powered spending analysis.

**Authentication:** Required

**Request Body:**
```json
{
  "time_period": "30d",
  "vendor_filter": "Amazon"
}
```

**Response:**
```json
{
  "success": true,
  "user_id": 1,
  "time_period": "30d",
  "analysis": {
    "total_spent": 1250.50,
    "receipt_count": 15,
    "vendor_breakdown": [
      {"vendor": "Amazon", "total": 850.00, "count": 10}
    ],
    "trends": {...},
    "advice": "You spent $X on Amazon this month..."
  }
}
```

---

#### `POST /api/graph/insights`

Get AI-generated insights from your knowledge graph.

**Authentication:** Required

**Request Body:**
```json
{
  "insight_type": "spending"
}
```

**Parameters:**
- `insight_type` (string, default: "general") - Type: `general`, `spending`, or `contacts`

**Response:**
```json
{
  "success": true,
  "insight_type": "spending",
  "insights": {
    "summary": "Your spending patterns show...",
    "recommendations": [...]
  }
}
```

---

#### `POST /api/graph/visualize`

Get graph visualization data.

**Authentication:** Required

**Request Body:**
```json
{
  "center_node": "email_12345",
  "depth": 2,
  "max_nodes": 50
}
```

**Response:**
```json
{
  "success": true,
  "visualization": {
    "nodes": [...],
    "edges": [...]
  }
}
```

---

#### `GET /api/graph/stats`

Get knowledge graph statistics.

**Authentication:** Required

**Response:**
```json
{
  "success": true,
  "stats": {
    "total_nodes": 5000,
    "total_relationships": 12000,
    "nodes_by_type": {
      "Email": 2000,
      "Receipt": 500,
      "Vendor": 50
    }
  },
  "user_id": 1
}
```

---

### Gmail Push Notifications

Real-time email indexing via Gmail push notifications.

#### `POST /api/gmail/push/notification`

Receive Gmail push notification webhook.

**Authentication:** Not required (Gmail sends notifications)

**Headers:**
- `X-Goog-Channel-Id` - Unique channel identifier
- `X-Goog-Channel-Token` - Token to verify notification authenticity
- `X-Goog-Message-Number` - Sequential message number
- `X-Goog-Resource-Id` - Resource identifier
- `X-Goog-Resource-State` - State change type (`add`, `sync`)
- `X-Goog-Resource-Uri` - Resource URI
- `X-Goog-Channel-Expiration` - Expiration timestamp

**Response:**
```json
{
  "status": "received",
  "message": "Notification processed",
  "resource_state": "add"
}
```

**Behavior:**
- Processes `add` notifications (new emails) by triggering background indexing
- Ignores `sync` notifications (synchronization messages)
- Always returns `200 OK` to acknowledge receipt

**Status Codes:**
- `200` - Success

---

#### `GET /api/gmail/push/health`

Health check endpoint for Gmail push notifications.

**Authentication:** Not required

**Response:**
```json
{
  "status": "healthy",
  "service": "gmail-push-notifications",
  "webhook_url": "https://api.example.com/api/gmail/push/notification"
}
```

---

- `WebSocket /api/voice/ws/{session_id}`

When re-enabled, these endpoints will provide:
- Speech-to-text conversion
- Text-to-speech responses
- Real-time voice conversations
- WebSocket support for streaming

---

#### `GET /api/voice/status`

Check voice service status and configuration.

**Authentication:** Not required

**Response:**
```json
{
  "success": true,
  "enabled": true,
  "voice_id": "21m00Tcm4TlvDq8ikWAMtangster",
  "model": "eleven_multilingual_v2",
  "stt_model": "eleven_multilingual_v2",
  "stt_language": "en",
  "message": "Voice service is ready"
}
```

**Status Codes:**
- `200` - Success
- `503` - Voice service not enabled

---

#### `POST /api/voice/introduction`

Generate Clavr's voice introduction.

**Authentication:** Not required

**Query Parameters:**
- `user_name` (string, optional) - User name for personalized greeting

**Response:**
```json
{
  "success": true,
  "introduction_text": "Hey there, I'm Clavr...",
  "audio_data": "base64-encoded-audio",
  "message": "Ready to listen"
}
```

**Status Codes:**
- `200` - Success
- `503` - Voice service not enabled
- `500` - Generation failed

---

#### `POST /api/voice/chat`

Voice chat endpoint - converts speech to text, processes with Clavr, returns speech response.

**Authentication:** Not required (enhanced features with user_id)

**Request Body:**
```json
{
  "audio_data": "base64-encoded-audio",
  "user_id": 1,
  "session_id": "voice_session_123",
  "voice_settings": {
    "stability": 0.5,
    "similarity_boost": 0.75
  }
}
```

**Parameters:**
- `audio_data` (string, required) - Base64 encoded audio
- `user_id` (integer, optional) - User ID for enhanced features
- `session_id` (string, optional) - Session identifier
- `voice_settings` (object, optional) - Voice configuration

**Response:**
```json
{
  "success": true,
  "transcribed_text": "What's in my calendar today?",
  "response_text": "You have 3 meetings today...",
  "audio_response": "base64-encoded-audio",
  "processing_time": 2.45
}
```

**Status Codes:**
- `200` - Success
- `400` - Invalid audio or no speech detected
- `503` - Voice service not enabled
- `500` - Processing failed

---

#### `POST /api/voice/text-to-speech`

Convert text to speech using ElevenLabs.

**Authentication:** Not required

**Query Parameters:**
- `text` (string, required) - Text to convert

**Request Body (Optional):**
```json
{
  "voice_settings": {
    "stability": 0.5,
    "similarity_boost": 0.75,
    "style": 0.0,
    "use_speaker_boost": true
  }
}
```

**Response:**
- Streaming audio file (audio/mpeg)

**Status Codes:**
- `200` - Success
- `400` - Invalid request
- `503` - Voice service not enabled
- `500` - Generation failed

---

#### `GET /api/voice/voices`

Get available voices from ElevenLabs.

**Authentication:** Not required

**Response:**
```json
{
  "voices": [
    {
      "voice_id": "21m00Tcm4TlvDq8ikWAMtangster",
      "name": "Rachel",
      "category": "premade",
      "description": "..."
    }
  ]
}
```

**Status Codes:**
- `200` - Success
- `503` - Voice service not enabled
- `500` - Request failed

---

#### `POST /api/voice/config`

Update voice configuration.

**Authentication:** Not required

**Request Body:**
```json
{
  "voice_id": "21m00Tcm4TlvDq8ikWAMtangster",
  "model": "eleven_multilingual_v2",
  "stability": 0.5,
  "similarity_boost": 0.75,
  "style": 0.0,
  "use_speaker_boost": true
}
```

**Parameters:**
- All parameters optional

**Response:**
```json
{
  "success": true,
  "current_config": {
    "voice_id": "21m00Tcm4TlvDq8ikWAMtangster",
    "model": "eleven_multilingual_v2",
    "sample_rate": 22050,
    "chunk_size": 1024
  },
  "available_voices": {...}
}
```

**Status Codes:**
- `200` - Success
- `503` - Voice service not enabled
- `500` - Update failed

---

#### `GET /api/voice/sessions/{session_id}`

Get voice session information.

**Authentication:** Not required

**Path Parameters:**
- `session_id` (string, required) - Session identifier

**Response:**
```json
{
  "session_id": "voice_session_123",
  "user_id": 1,
  "is_active": true,
  "message_count": 5,
  "created_at": "2024-01-01T12:00:00"
}
```

**Status Codes:**
- `200` - Success
- `404` - Session not found

---

#### `DELETE /api/voice/sessions/{session_id}`

Delete voice session.

**Authentication:** Not required

**Path Parameters:**
- `session_id` (string, required) - Session identifier

**Response:**
```json
{
  "success": true,
  "message": "Voice session voice_session_123 deleted"
}
```

**Status Codes:**
- `200` - Success
- `404` - Session not found

---


## Request/Response Models

### Standard Models

#### Error Response
```json
{
  "success": false,
  "error": "error_code",
  "message": "Human-readable error message",
  "details": [
    {
      "field": "field_name",
      "message": "Field-specific error",
      "code": "error_code"
    }
  ],
  "request_id": "abc12345",
  "timestamp": "2024-01-01T12:00:00"
}
```

#### Success Response
```json
{
  "success": true,
  "data": {...},
  "message": "Optional success message",
  "meta": {
    "request_id": "abc12345",
    "timestamp": "2024-01-01T12:00:00"
  }
}
```

---

## Error Handling

Clavr API uses standardized error responses with the following HTTP status codes:

### Status Codes

- `200 OK` - Request successful
- `302 Found` - Redirect (OAuth flow)
- `400 Bad Request` - Invalid request data
- `401 Unauthorized` - Authentication required
- `403 Forbidden` - Insufficient permissions
- `404 Not Found` - Resource not found
- `409 Conflict` - Resource conflict
- `422 Unprocessable Entity` - Validation error
- `429 Too Many Requests` - Rate limit exceeded
- `500 Internal Server Error` - Server error
- `503 Service Unavailable` - Service unavailable (e.g., voice service)

### Error Types

- `authentication_required` - No valid session
- `authorization_failed` - Insufficient permissions
- `validation_error` - Request validation failed
- `not_found` - Resource not found
- `conflict` - Resource already exists
- `rate_limit_exceeded` - Too many requests
- `internal_server_error` - Unexpected error

### Error Response Format

All errors follow a consistent format:

```json
{
  "success": false,
  "error": "error_code",
  "message": "Human-readable message",
  "details": [
    {
      "field": "field_name",
      "message": "Specific error",
      "code": "error_code"
    }
  ]
}
```

---

## Rate Limiting

Rate limiting is implemented using SlowAPI with configurable limits per minute and per hour.

**Configuration:**
- `RATE_LIMIT_PER_MINUTE` (default: 60) - Requests per minute per IP
- `RATE_LIMIT_PER_HOUR` (default: 1000) - Requests per hour per IP

**Special Rate Limits:**
- OAuth login: 10 requests per minute per IP
- OAuth callback: 5 requests per minute per IP

**Rate Limit Headers:**
```
X-RateLimit-Limit: 60
X-RateLimit-Remaining: 55
X-RateLimit-Reset: 1640995200
```

When rate limit is exceeded, a `429 Too Many Requests` response is returned with details about the limit.

---

## Authentication Details

### Session Management

- Sessions are created upon successful OAuth authentication
- Session tokens are stored in the database
- Sessions expire after a configurable timeout (default: 24 hours)
- Multiple sessions per user are supported

### OAuth Flow

1. **Initiate:** `GET /auth/google/login`
2. **Authorize:** User completes Google authentication
3. **Callback:** `GET /auth/google/callback?code=...`
4. **Create Session:** System creates session with token
5. **Redirect:** Frontend receives token via query parameter
6. **Use Token:** Include in subsequent API requests

### Background Indexing

For new users, email indexing starts automatically in the background:
- Indexes 400-500 recent emails from INBOX
- Updates user status as indexing progresses
- Completes when all emails are indexed

---

## Development

### Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Set up environment variables
cp .env.example .env
# Edit .env with your credentials

# Start the API
python api/main.py
```

### Environment Variables

Required environment variables:
- `GOOGLE_CLIENT_ID` - Google OAuth client ID
- `GOOGLE_CLIENT_SECRET` - Google OAuth client secret
- `GOOGLE_REDIRECT_URI` - OAuth redirect URI
- `GOOGLE_API_KEY` - Google Gemini API key
- `ELEVENLABS_API_KEY` - ElevenLabs API key (optional, for voice)
- `FRONTEND_URL` - Frontend URL for redirects

### API Testing

**Using curl:**
```bash
# Health check
curl http://localhost:8000/health

# Chat query
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"query": "What emails do I have today?"}'

# With authentication
curl -X GET http://localhost:8000/auth/me \
  -H "X-Session-Token: your-token-here"
```

**Using Python:**
```python
import requests

# Chat query
response = requests.post(
    "http://localhost:8000/api/chat",
    json={"query": "What's in my calendar today?"}
)
print(response.json())

# With authentication
response = requests.get(
    "http://localhost:8000/auth/me",
    headers={"X-Session-Token": "your-token-here"}
)
print(response.json())
```

---

## Support

For issues, questions, or contributions:

- **Documentation:** [Full docs directory](docs/)
- **Interactive API Docs:** [Swagger UI](http://localhost:8000/docs)
- **Alternative API Docs:** [ReDoc](http://localhost:8000/redoc)

---

## Changelog

### Version 2.0.0 (Current)
- Complete API refactoring with proper routing
- OAuth authentication with Google
- LangGraph orchestration for multi-step queries
- AI-powered features (auto-reply, analysis, summarization, meeting prep)
- Writing style profiles for personalized responses
- Dashboard statistics and analytics
- Blog content management system (admin)
- Admin user management endpoints
- GDPR-compliant data export (Article 20)
- Webhook subscriptions with HMAC signatures
- Knowledge graph and GraphRAG analytics
- Gmail push notifications for real-time indexing
- Rate limiting with SlowAPI
- CSRF protection middleware
- Comprehensive error handling
- Session management middleware
- Token rotation middleware

---

**Last Updated:** January 2024  
**API Version:** 2.0.0  
**Maintainer:** Clavr Team
