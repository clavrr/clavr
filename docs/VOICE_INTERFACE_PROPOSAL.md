# Voice Interface Integration Proposal

## Executive Summary

This document provides a comprehensive proposal for adding voice interface capabilities to the Clavr Agent system. The voice interface will enable hands-free and mobile scenarios, significantly expanding market reach for professionals on the go.

## Use Cases (from Requirements)

1. **Mobile Scheduling**: "Clavr, schedule a standup with John and Lauren tomorrow at 11 AM and send them the prep doc from last week's email."
2. **Hands-Free Triage**: "Check my urgent emails, summarize the top one, and create a task for me to reply after dinner."
3. **Quick Task Capture**: "Quick task: Call the professor about the syllabus changes by Friday."
4. **Real-Time Analysis**: "Prepare me for the budget review starting in five minutes. What were the key action items from the last meeting?"

## Architecture Overview

### Current System Architecture

```
User Query (Text) → API Router → Auth → ClavrAgent → Orchestrator → Tools → Response (Text)
```

### Proposed Voice Architecture

```
Voice Input → WebSocket → STT Service → Text Query → ClavrAgent → Orchestrator → Tools → Response (Text) → TTS Service → Audio Output
```

## Implementation Strategy

### Phase 1: Core Voice Infrastructure

#### 1.1 WebSocket Endpoint
**Location**: `api/routers/voice.py`

Create a new router for voice interactions using WebSocket for bidirectional real-time communication.

**Key Features**:
- WebSocket connection for continuous voice interaction
- Session management (reuse existing auth middleware)
- Audio chunk streaming (receive audio, send audio)
- Connection lifecycle management

**Implementation**:
```python
@router.websocket("/api/voice/stream")
async def voice_stream(websocket: WebSocket, ...):
    await websocket.accept()
    # Handle audio chunks, convert to text, process, convert to audio, send
```

#### 1.2 Speech-to-Text (STT) Integration
**Options**:
1. **Google Cloud Speech-to-Text** (Recommended)
   - High accuracy
   - Real-time streaming support
   - Good language model support
   - Already using Google APIs (OAuth, Gmail, Calendar)

2. **OpenAI Whisper API**
   - Excellent accuracy
   - Good for multiple languages
   - Simple API

3. **AssemblyAI**
   - Real-time streaming
   - Good accuracy
   - Competitive pricing

**Recommendation**: Start with Google Cloud Speech-to-Text for consistency with existing Google integrations.

**Location**: `src/integrations/voice/stt_service.py`

#### 1.3 Text-to-Speech (TTS) Integration
**Options**:
1. **Google Cloud Text-to-Speech**
   - Natural voices
   - SSML support
   - Consistent with existing stack

2. **ElevenLabs**
   - Very natural voices
   - Emotional intonation
   - Good for conversational AI

3. **OpenAI TTS**
   - Good quality
   - Simple API
   - Competitive pricing

**Recommendation**: Start with Google Cloud Text-to-Speech, consider ElevenLabs for premium experience.

**Location**: `src/integrations/voice/tts_service.py`

### Phase 2: Voice-Optimized Agent Integration

#### 2.1 Voice Query Preprocessing
**Location**: `src/agent/parsers/voice/voice_parser.py`

**Features**:
- Voice-specific intent detection (e.g., "Quick task:", "Check my...")
- Noise filtering and cleanup
- Context preservation across voice turns
- Interruption handling

**Key Optimizations**:
- Shorter, more concise responses for voice
- Confirmation patterns ("Got it, I've scheduled...")
- Progressive feedback ("Let me check...", "Found it...")
- Error recovery with voice-friendly messages

#### 2.2 Voice Response Formatter
**Location**: `src/agent/formatting/voice_formatter.py`

**Features**:
- Convert text responses to voice-optimized format
- Remove visual-only elements (markdown, tables)
- Add conversational fillers for natural flow
- Break long responses into digestible chunks
- Add confirmation phrases

**Example Transformations**:
- "You have 3 events" → "You've got 3 things coming up"
- "Task created: [details]" → "I've created that task for you"
- Tables → "First, [item]. Second, [item]..."

### Phase 3: Real-Time Streaming Integration

#### 3.1 Streaming Voice Responses
**Integration Point**: Extend `ClavrAgent.stream_execute()` for voice

**Features**:
- Stream workflow events as voice updates
- Convert text chunks to audio in real-time
- Progressive audio playback
- Interruption handling (user can interrupt with new query)

**Implementation**:
- Use existing `stream_execute()` method
- Add voice-specific event handlers
- Convert text chunks to audio chunks
- Stream audio chunks via WebSocket

#### 3.2 Voice Workflow Events
**Location**: `src/agent/events/voice_events.py`

**New Event Types**:
- `listening_started`: "I'm listening..."
- `processing`: "Let me check that for you..."
- `tool_selected`: "I'll check your calendar..."
- `partial_result`: "I found 3 emails..."
- `complete`: "All done! I've scheduled..."

### Phase 4: Mobile & Hands-Free Optimizations

#### 4.1 Quick Task Capture Mode
**Feature**: Bypass full orchestration for simple tasks

**Implementation**:
- Detect "Quick task:" prefix
- Route directly to TaskTool
- Skip email/calendar parsing
- Fast response (< 2 seconds)

**Location**: `src/agent/parsers/voice/quick_capture.py`

#### 4.2 Hands-Free Triage Mode
**Feature**: Optimized for email triage scenarios

**Implementation**:
- Prioritize email queries
- Use RAG for fast email search
- Generate concise summaries
- Create tasks with minimal confirmation

**Location**: `src/agent/parsers/voice/triage_mode.py`

#### 4.3 Mobile Scheduling Mode
**Feature**: Optimized for scheduling while mobile

**Implementation**:
- Enhanced contact resolution (voice-friendly names)
- Calendar conflict detection with voice feedback
- Document attachment from email history
- Multi-step confirmation via voice

**Location**: `src/agent/parsers/voice/mobile_scheduling.py`

#### 4.4 Real-Time Analysis Mode
**Feature**: Fast context retrieval for meetings

**Implementation**:
- Prioritize graph-grounded context
- Fast retrieval from memory system
- Concise summaries
- Key points only

**Location**: `src/agent/parsers/voice/realtime_analysis.py`

## Technical Implementation Details

### File Structure

```
api/
  routers/
    voice.py                    # WebSocket voice endpoint
    __init__.py                 # Include voice router

src/
  integrations/
    voice/
      __init__.py
      stt_service.py            # Speech-to-Text service
      tts_service.py            # Text-to-Speech service
      voice_client.py           # Voice client wrapper
      audio_processor.py        # Audio chunk processing

  agent/
    parsers/
      voice/
        __init__.py
        voice_parser.py         # Voice query parser
        quick_capture.py        # Quick task capture
        triage_mode.py          # Email triage mode
        mobile_scheduling.py    # Mobile scheduling mode
        realtime_analysis.py    # Real-time analysis mode

    formatting/
      voice_formatter.py        # Voice response formatter

    events/
      voice_events.py           # Voice-specific events

  services/
    voice/
      __init__.py
      voice_orchestrator.py     # Voice-specific orchestration
      session_manager.py         # Voice session management
```

### Database Schema Changes

**New Table**: `voice_sessions`
```sql
CREATE TABLE voice_sessions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    session_id VARCHAR(255) UNIQUE,
    started_at TIMESTAMP DEFAULT NOW(),
    ended_at TIMESTAMP,
    total_queries INTEGER DEFAULT 0,
    audio_format VARCHAR(50),  -- 'pcm', 'wav', 'mp3'
    sample_rate INTEGER,       -- 16000, 44100, etc.
    language_code VARCHAR(10),   -- 'en-US', 'en-GB', etc.
    created_at TIMESTAMP DEFAULT NOW()
);
```

**New Table**: `voice_interactions`
```sql
CREATE TABLE voice_interactions (
    id SERIAL PRIMARY KEY,
    voice_session_id INTEGER REFERENCES voice_sessions(id),
    query_text TEXT,
    response_text TEXT,
    audio_duration_ms INTEGER,
    processing_time_ms INTEGER,
    intent VARCHAR(50),
    created_at TIMESTAMP DEFAULT NOW()
);
```

### API Endpoints

#### WebSocket Endpoint
```
WS /api/voice/stream
```

**Connection Flow**:
1. Client connects via WebSocket
2. Send authentication token in first message
3. Server validates and establishes session
4. Client sends audio chunks (binary or base64)
5. Server processes and streams audio responses

**Message Format**:
```json
{
  "type": "audio_chunk" | "text_query" | "control",
  "data": "...",
  "session_id": "...",
  "format": "pcm" | "wav" | "mp3",
  "sample_rate": 16000
}
```

**Response Format**:
```json
{
  "type": "audio_chunk" | "text_transcript" | "workflow_event" | "error",
  "data": "...",
  "sequence": 1,
  "is_final": false
}
```

#### REST Endpoint (Fallback)
```
POST /api/voice/query
```

For clients that prefer REST over WebSocket (e.g., simple mobile apps).

**Request**:
```json
{
  "audio": "base64_encoded_audio",
  "format": "wav",
  "language": "en-US"
}
```

**Response**:
```json
{
  "transcript": "Schedule a meeting...",
  "response_text": "I've scheduled...",
  "response_audio": "base64_encoded_audio",
  "intent": "calendar",
  "confidence": 0.95
}
```

### Configuration

**Add to `config/default.yaml`**:
```yaml
voice:
  enabled: true
  stt:
    provider: "google"  # "google" | "openai" | "assemblyai"
    language: "en-US"
    sample_rate: 16000
    encoding: "LINEAR16"
    streaming: true
  tts:
    provider: "google"  # "google" | "elevenlabs" | "openai"
    voice: "en-US-Neural2-D"  # Google voice name
    language: "en-US"
    speaking_rate: 1.0
    pitch: 0.0
  audio:
    format: "pcm"
    sample_rate: 16000
    channels: 1
    chunk_size_ms: 100
  optimization:
    quick_capture_enabled: true
    triage_mode_enabled: true
    mobile_scheduling_enabled: true
    realtime_analysis_enabled: true
    max_response_length: 500  # characters for voice
    confirmation_phrases: true
```

### Environment Variables

```bash
# Google Cloud Speech-to-Text
GOOGLE_CLOUD_SPEECH_API_KEY=your-api-key
GOOGLE_CLOUD_SPEECH_PROJECT_ID=your-project-id

# Google Cloud Text-to-Speech
GOOGLE_CLOUD_TTS_API_KEY=your-api-key

# Alternative: OpenAI Whisper/TTS
OPENAI_API_KEY=your-api-key

# Alternative: ElevenLabs
ELEVENLABS_API_KEY=your-api-key

# Voice Service Configuration
VOICE_ENABLED=true
VOICE_STT_PROVIDER=google
VOICE_TTS_PROVIDER=google
```

## Integration with Existing Systems

### 1. Authentication
- Reuse existing `SessionMiddleware` and `get_current_user_required`
- WebSocket connections authenticate via token in initial handshake
- Session tokens validated same as REST endpoints

### 2. ClavrAgent Integration
- Voice queries route through existing `ClavrAgent.execute()` or `stream_execute()`
- No changes needed to core agent logic
- Voice-specific optimizations in parser layer

### 3. Orchestrator Integration
- Existing orchestrator handles voice queries transparently
- Voice formatter post-processes responses
- Workflow events adapted for voice context

### 4. Tools Integration
- All existing tools (EmailTool, CalendarTool, TaskTool) work unchanged
- Voice parser extracts same structured parameters
- Responses formatted for voice output

### 5. Memory System
- Conversation memory tracks voice interactions
- Voice sessions linked to user sessions
- Context preserved across voice turns

## Performance Considerations

### Latency Targets
- **STT Processing**: < 500ms for initial transcript
- **Query Processing**: < 2s for simple queries, < 5s for complex
- **TTS Generation**: < 1s for response audio
- **End-to-End**: < 3s for simple, < 8s for complex

### Optimization Strategies
1. **Streaming STT**: Process audio chunks as they arrive
2. **Progressive TTS**: Generate audio while processing query
3. **Caching**: Cache common queries and responses
4. **Parallel Processing**: STT + query processing overlap
5. **Audio Compression**: Use efficient codecs (Opus, AAC)

### Scalability
- WebSocket connections: Use connection pooling
- STT/TTS APIs: Rate limiting and queuing
- Audio processing: Async processing with worker queues
- Database: Index voice_sessions and voice_interactions tables

## Security Considerations

1. **Authentication**: All voice connections require valid session token
2. **Audio Privacy**: Audio chunks encrypted in transit (WSS)
3. **Data Retention**: Configurable retention for voice sessions
4. **Access Control**: User can only access their own voice sessions
5. **Rate Limiting**: Voice-specific rate limits (different from text)

## Testing Strategy

### Unit Tests
- STT service with sample audio
- TTS service with sample text
- Voice parser with sample queries
- Voice formatter with sample responses

### Integration Tests
- WebSocket connection flow
- End-to-end voice query processing
- Streaming audio responses
- Error handling and recovery

### Performance Tests
- Latency measurements
- Concurrent connection handling
- Audio processing throughput
- Memory usage under load

## Deployment Plan

### Phase 1: MVP (4-6 weeks)
1. WebSocket endpoint with basic STT/TTS
2. Simple voice query processing
3. Basic voice response formatting
4. REST fallback endpoint

### Phase 2: Optimizations (3-4 weeks)
1. Quick capture mode
2. Triage mode
3. Mobile scheduling mode
4. Real-time analysis mode

### Phase 3: Advanced Features (4-6 weeks)
1. Streaming audio responses
2. Progressive feedback
3. Interruption handling
4. Multi-turn conversations
5. Voice session management

### Phase 4: Polish & Scale (2-3 weeks)
1. Performance optimization
2. Error handling improvements
3. Documentation
4. Monitoring and analytics

## Monitoring & Analytics

### Metrics to Track
- Voice session duration
- Queries per session
- Average response latency
- STT accuracy rate
- TTS generation time
- Error rates by type
- User satisfaction (if available)

### Logging
- Voice session start/end
- Query transcripts (anonymized)
- Response generation time
- Audio processing metrics
- Error events with context

## Cost Estimation

### STT Costs (Google Cloud)
- $0.006 per 15 seconds
- Estimated: $0.024 per query (1 minute average)
- 1000 queries/day = ~$24/day = ~$720/month

### TTS Costs (Google Cloud)
- $4 per 1M characters
- Estimated: $0.002 per response (500 chars average)
- 1000 queries/day = ~$2/day = ~$60/month

### Total Estimated Cost
- **Low usage** (100 queries/day): ~$85/month
- **Medium usage** (1000 queries/day): ~$780/month
- **High usage** (10000 queries/day): ~$7800/month

**Note**: Costs can be optimized with caching, response length limits, and provider selection.

## Alternative Approaches Considered

### 1. Server-Sent Events (SSE)
- **Pros**: Simpler than WebSocket, works with HTTP
- **Cons**: One-way only, requires polling for audio upload
- **Decision**: WebSocket chosen for bidirectional audio streaming

### 2. REST API with Long Polling
- **Pros**: Simple, works everywhere
- **Cons**: Higher latency, inefficient for real-time
- **Decision**: Not suitable for voice interactions

### 3. gRPC Streaming
- **Pros**: Efficient, type-safe
- **Cons**: More complex, less web-friendly
- **Decision**: WebSocket more accessible for web/mobile clients

## Dependencies

### New Python Packages
```txt
# Speech-to-Text
google-cloud-speech>=2.19.0  # For Google Cloud STT
# OR
openai>=1.0.0  # For OpenAI Whisper

# Text-to-Speech
google-cloud-texttospeech>=2.14.0  # For Google Cloud TTS
# OR
elevenlabs>=0.2.0  # For ElevenLabs
# OR
openai>=1.0.0  # For OpenAI TTS

# WebSocket
websockets>=11.0.0
python-socketio>=5.10.0  # Alternative WebSocket library

# Audio Processing
pydub>=0.25.1  # Audio manipulation
numpy>=1.24.0  # Audio array processing
```

### Infrastructure
- Google Cloud Project (if using Google STT/TTS)
- API keys for chosen providers
- WebSocket-capable reverse proxy (nginx, Caddy)

## Migration Path

### For Existing Users
- Voice interface is additive, no breaking changes
- Existing text-based queries continue to work
- Users opt-in to voice features
- Voice sessions tracked separately from text sessions

### Backward Compatibility
- All existing endpoints remain unchanged
- Voice router is new addition
- No changes to core agent or orchestrator
- Voice features can be disabled via config

## Success Metrics

### Adoption Metrics
- % of users trying voice interface
- Voice queries per user per day
- Voice session duration
- Retention rate (users who try voice and continue using)

### Quality Metrics
- STT accuracy rate
- Query intent detection accuracy
- Response relevance (user feedback)
- Error rate

### Performance Metrics
- Average end-to-end latency
- P95/P99 latency
- Concurrent connection capacity
- Audio processing throughput

## Risks & Mitigations

### Risk 1: High Latency
- **Mitigation**: Streaming STT, progressive TTS, caching, optimization

### Risk 2: STT Accuracy Issues
- **Mitigation**: Multiple provider support, confidence thresholds, fallback to text

### Risk 3: Cost Overruns
- **Mitigation**: Rate limiting, response length limits, caching, cost monitoring

### Risk 4: Scalability Issues
- **Mitigation**: Connection pooling, async processing, horizontal scaling

### Risk 5: Audio Quality Issues
- **Mitigation**: Audio format validation, quality checks, fallback options

## Conclusion

The proposed voice interface integration leverages the existing Clavr Agent architecture while adding voice-specific optimizations for hands-free and mobile scenarios. The implementation is modular, allowing incremental rollout and optimization based on user feedback.

The key advantages of this approach:
1. **Reuses existing infrastructure**: ClavrAgent, orchestrator, tools, memory system
2. **Modular design**: Voice features can be added incrementally
3. **Provider flexibility**: Support for multiple STT/TTS providers
4. **Performance optimized**: Streaming, caching, parallel processing
5. **Scalable**: WebSocket connections, async processing, horizontal scaling

This proposal provides a comprehensive roadmap for implementing voice interface capabilities that will significantly expand the platform's reach and usability.

