# Voice API Endpoints

This document describes the API endpoints available for voice integration.

## Base URL

All voice endpoints are prefixed with `/api/voice`:

```
http://localhost:8000/api/voice
```

## Authentication

All endpoints require authentication. Include the authentication token in the request headers:

```
Authorization: Bearer YOUR_TOKEN
```

---

## Endpoints

### 1. POST `/api/voice/transcribe`

**Standard voice transcription endpoint** - Processes voice input and returns complete response.

**Request Headers:**
```
Content-Type: application/json
Authorization: Bearer YOUR_TOKEN
```

**Request Body:**
```json
{
  "audio_data": "base64_encoded_audio_string",
  "mime_type": "audio/webm",
  "session_id": "optional_session_id"
}
```

**Request Fields:**
- `audio_data` (string, required): Base64-encoded audio data from browser MediaRecorder
- `mime_type` (string, optional, default: "audio/webm"): MIME type of audio (e.g., "audio/webm", "audio/webm;codecs=opus")
- `session_id` (string, optional): Session ID for conversation context

**Response:**
```json
{
  "success": true,
  "transcription": "raw transcript from STT",
  "normalized": "cleaned and normalized transcript",
  "response": "agent's text response (voice-formatted)",
  "response_audio": "base64_encoded_mp3_audio",
  "error": null
}
```

**Response Fields:**
- `success` (boolean): Whether the request succeeded
- `transcription` (string, optional): Raw transcript from Speech-to-Text
- `normalized` (string, optional): Normalized/cleaned transcript (only present if different from raw)
- `response` (string, optional): Agent's text response (formatted for voice)
- `response_audio` (string, optional): Base64-encoded MP3 audio of the response
- `error` (string, optional): Error message if `success` is false

**Status Codes:**
- `200` - Success
- `400` - Invalid request
- `401` - Not authenticated
- `500` - Server error

---

### 2. POST `/api/voice/query`

**Alias for `/transcribe`** - Provides the same functionality for backward compatibility.

**Request/Response**: Same as `/api/voice/transcribe`

---

### 3. POST `/api/voice/transcribe/stream`

**Streaming voice transcription endpoint** - Provides real-time updates via Server-Sent Events (SSE).

**Request Headers:**
```
Content-Type: application/json
Authorization: Bearer YOUR_TOKEN
```

**Request Body:** Same as `/api/voice/transcribe`

**Response:** Server-Sent Events (SSE) stream with progressive updates

**Event Types:**
1. `transcribing` - STT in progress
2. `transcribed` - Raw transcript available
3. `normalizing` - Normalization in progress
4. `normalized` - Normalized text available
5. `processing` - Agent processing query
6. `response` - Agent response ready
7. `formatting` - Generating audio response
8. `audio` - Audio response available
9. `complete` - All processing done
10. `error` - Error occurred

**Event Format:**
```
data: {"event": "transcribing", "message": "Converting audio to text..."}

data: {"event": "transcribed", "transcription": "raw transcript text"}

data: {"event": "normalized", "normalized": "cleaned transcript"}

data: {"event": "response", "response": "agent response text"}

data: {"event": "audio", "audio": "base64_encoded_mp3"}

data: {"event": "complete", "message": "All done!"}
```

**Response Headers:**
```
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive
```

**Status Codes:**
- `200` - Success (streaming)
- `400` - Invalid request
- `401` - Not authenticated
- `500` - Server error

---

## Error Response Format

All endpoints return errors in this format:

```json
{
  "success": false,
  "error": "Error message here",
  "transcription": null,
  "normalized": null,
  "response": null,
  "response_audio": null
}
```

**Common Errors:**
- `"Could not transcribe audio"` - STT failed (check audio format, credentials)
- `"Voice processing failed: ..."` - General processing error
- `401 Unauthorized` - Missing or invalid authentication token
- `500 Internal Server Error` - Server-side error

---

## Request/Response Flow

### Standard Endpoint (`/transcribe`)

```
Client → POST /api/voice/transcribe
         ↓
      STT Service → Raw Transcript
         ↓
      Analyzer → Normalized Transcript
         ↓
      Orchestrator → Agent Response
         ↓
      Voice Formatter → Formatted Response
         ↓
      TTS Service → Audio Response
         ↓
      Client ← Complete Response (JSON)
```

### Streaming Endpoint (`/transcribe/stream`)

```
Client → POST /api/voice/transcribe/stream
         ↓
      SSE Stream Started
         ↓
      Event: "transcribing"
         ↓
      Event: "transcribed" (with raw transcript)
         ↓
      Event: "normalizing"
         ↓
      Event: "normalized" (with cleaned transcript)
         ↓
      Event: "processing"
         ↓
      Event: "response" (with agent response)
         ↓
      Event: "formatting"
         ↓
      Event: "audio" (with base64 audio)
         ↓
      Event: "complete"
         ↓
      Stream Closed
```

---

## Notes

- **Audio Format**: Use `audio/webm` (default from browser MediaRecorder)
- **Session Management**: Pass `session_id` to maintain conversation context
- **Error Handling**: Always check `success` field and handle `error` messages
- **Audio Playback**: Use HTML5 Audio API with base64 data URLs for `response_audio`
- **Streaming**: Use EventSource API or fetch with streaming for SSE endpoints
