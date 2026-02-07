# Clavr Frontend API Reference

This document provides a comprehensive listing of the API endpoints available for the frontend, including newly added features like Proactive Intelligence, Knowledge Graph, and Voice Interface.

## Base URL
All endpoints are prefixed with `/api`. For example: `https://api.clavr.dev/api/voice/introduction`.

---

## 🎙️ Voice Interface (`/api/voice`)
Endpoints for voice-based interaction and session initialization.

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| **POST** | `/voice/introduction` | **[NEW]** Get initialization data for voice session (user context, integrations, etc.). Fixes 404 error. |
| **WS** | `/voice/ws/transcribe` | WebSocket for real-time bidirectional voice streaming (Gemini Live / ElevenLabs). |

---

## 🔮 Proactive Intelligence (`/api/proactive`)
Endpoints for surfacing insights, meeting prep, and morning briefings.

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| **GET** | `/proactive/insights` | Get urgent insights, meeting prep, and suggestions. Query params: `hours_ahead`, `include_narrative`. |
| **GET** | `/proactive/meeting-prep/{meeting_id}` | Get deep-dive context for a specific meeting (attendees, docs, topics). |
| **GET** | `/proactive/briefing` | Get a full LLM-generated morning briefing narrative. |
| **GET** | `/proactive/topic-context/{topic}` | **[SemSync]** Get 360° cross-stack context for a project/topic (Linear, Drive, Slack, etc.). |
| **POST** | `/proactive/insights/{id}/dismiss` | Dismiss a specific insight. |
| **POST** | `/proactive/insights/{id}/shown` | Mark an insight as shown to track impressions. |

---

## 🕸️ Knowledge Graph (`/api/graph`)
Endpoints for graph-enhanced search and visualization.

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| **POST** | `/graph/search` | Execute hybrid search (Vector + Graph) for richer results. Body: `{"query": "..."}`. |
| **POST** | `/graph/entity/search` | Find all items related to a specific entity (Person, Vendor, Project). |
| **POST** | `/graph/analytics/spending` | Analyze spending patterns via graph relationships. |
| **POST** | `/graph/insights` | Get AI-generated insights about graph connections (spending, contacts). |
| **POST** | `/graph/visualize` | Get nodes/edges for D3.js frontend visualization. |
| **GET** | `/graph/stats` | Get graph statistics (node counts, etc.). |

---

## 📊 Analytics (`/api/analytics`)
Endpoints for memory and relationship analytics.

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| **GET** | `/analytics/relationships` | Top contacts and relationship strength analysis. |
| **GET** | `/analytics/topics` | Trending topics and topic clusters. |
| **GET** | `/analytics/temporal` | Activity patterns by time of day/week. |
| **GET** | `/analytics/cross-app` | Integration usage and cross-app connection stats. |
| **GET** | `/analytics/report` | Full comprehensive analytics report. |

---

## 👻 Ghost Mode (`/api/ghost`)
Endpoints for the "Ghost Collaborator" features.

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| **GET** | `/ghost/drafts` | List pending ghost drafts (auto-generated replies/issues). |
| **POST** | `/ghost/drafts/{id}/approve` | Approve and execute a draft (e.g., post to Linear). |
| **POST** | `/ghost/drafts/{id}/dismiss` | Dismiss a draft. |

---

## 🔌 Integrations (`/api/integrations`)
Endpoints for managing third-party connections.

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| **GET** | `/integrations/status` | List all connected integrations and their status. |
| **GET** | `/integrations/{provider}/auth` | Start OAuth flow (redirects to provider). |
| **POST** | `/integrations/{provider}/disconnect` | Disconnect an integration. |
| **POST** | `/integrations/{provider}/toggle` | Enable/Disable an integration without disconnecting. |

---

## ⚡ Workflows (`/api/workflows`)
Endpoints for triggering background automation.

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| **GET** | `/workflows/` | List available workflow definitions. |
| **GET** | `/workflows/history` | Get execution history. |
| **GET** | `/workflows/morning-briefing` | Trigger morning briefing generation. |
| **GET** | `/workflows/weekly-planning` | Trigger weekly planning workflow. |
| **GET** | `/workflows/end-of-day` | Trigger end-of-day review. |
| **POST** | `/workflows/email-to-action` | Convert email to Task/Event. |
| **POST** | `/workflows/batch-emails` | Process multiple emails. |
| **GET** | `/workflows/status/{id}` | Check status of a running workflow. |

---

## 🤖 Autonomy & Actions (`/api/autonomy`)
Endpoints for managing autonomous agent behavior.

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| **GET** | `/autonomy/settings` | Get autonomy levels for different action types. |
| **PUT** | `/autonomy/settings/{type}` | Update autonomy settings (e.g., require confirmation for email). |
| **GET** | `/autonomy/actions` | List action history (executed & pending). |
| **GET** | `/autonomy/actions/pending` | List actions waiting for user approval. |
| **POST** | `/autonomy/actions/{id}/approve` | Approve a pending autonomous action. |
| **POST** | `/autonomy/actions/{id}/undo` | Undo an executed action (if available). |

---

## 📝 User Profile (`/api/profile`)
Endpoints for the user's writing style profile.

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| **GET** | `/profile` | Get current writing style profile. |
| **POST** | `/profile/build` | Build/Rebuild profile from sent emails. |
| **DELETE** | `/profile` | Delete profile data. |

---

## 💬 Chat & Conversations
Standard endpoints for chat interface.

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| **POST** | `/chat/unified/stream` | Main chat endpoint (streaming response). |
| **GET** | `/conversations` | List recent conversation history. |

---

## 🛡️ Admin (`/api/admin`)
**Requires Admin Privileges.** User management and platform statistics.

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| **GET** | `/admin/users` | List all users (paginated, search). |
| **GET** | `/admin/users/{id}` | Get detailed user info (active sessions, indexing status). |
| **PUT** | `/admin/users/{id}/admin` | Grant/Revoke admin status. |
| **DELETE** | `/admin/users/{id}/sessions` | Force logout (revoke all sessions) for a user. |
| **GET** | `/admin/stats` | Platform-wide statistics (total users, blog posts, etc.). |
| **GET** | `/admin/health/detailed` | Detailed system health (DB, RAG, Activity). |
| **GET** | `/admin/profile-service/stats` | Background profile service monitoring. |
| **POST** | `/admin/profile-service/trigger-update` | Manually trigger profile update cycle. |
