# Voice API Endpoints (Real-time Gemini Live)

This document describes the WebSocket-based real-time voice interface for Clavr, leveraging the Gemini Live API for low-latency, natural interactions.

## Base WebSocket URL

```
ws://localhost:8000/api/voice/ws/transcribe
```

## Authentication

Authentication is required and can be performed in two ways:

1. **Query Parameter**:
   ```
   ws://localhost:8000/api/voice/ws/transcribe?token=YOUR_SESSION_TOKEN
   ```

2. **Auth Message (First Message)**:
   Connect to the WebSocket and immediately send:
   ```json
   {
     "type": "auth",
     "token": "YOUR_SESSION_TOKEN"
   }
   ```

---

## Communication Protocol

The voice interface uses a hybrid binary/text protocol over WebSockets.

### 1. Client to Server (Input)

#### Audio Stream (Binary)
Send raw PCM audio chunks as binary messages.
- **Sample Rate**: 16,000 Hz
- **Format**: 16-bit Linear PCM (S16_LE)
- **Channels**: Mono

#### Control Messages (JSON Text)
- `{"type": "auth", "token": "..."}`: Initial authentication.
- `{"type": "stop"}`: Gracefully stop the current session.

### 2. Server to Client (Output)

#### Status Updates (JSON Text)
- `{"type": "ready", "message": "Connected to Gemini Live"}`: Sent once authenticated and ready.
- `{"type": "error", "message": "..."}`: Sent if an error occurs.

#### Agent Response (JSON Text)
Incoming text chunks from the agent are streamed back to the client as they are generated.

---

## Request/Response Flow

```
Client → Connect to WebSocket (with token)
          ↓
Server ←  Event: "ready"
          ↓
Client → Stream Binary Audio (PCM Chunks)
          ↓
Server → Process via VoiceService + Gemini Live
          ↓
Server ← Stream Text Response (JSON Chunks)
          ↓
Client → Play Audio (via Client-side TTS or Gemini Stream)
```

## Implementation Notes

- **Noise Gating**: The server implements an energy-based noise gate (RMS threshold) to ignore silence and background noise.
- **Audio Transcoding**: The server uses `StreamingTranscoder` to handle various input formats if necessary, though raw PCM is preferred for lowest latency.
- **Tool Integration**: The voice agent has full access to Clavr tools (Calendar, Email, Ghost Drafts, etc.) and can execute actions based on voice commands.
- **Personalization**: The voice script is dynamically personalized based on the user's name and recent proactive insights.

---

## Client Examples (JavaScript)

```javascript
const socket = new WebSocket('ws://localhost:8000/api/voice/ws/transcribe?token=' + sessionToken);

socket.onopen = () => {
  console.log('Voice connection opened');
};

socket.onmessage = (event) => {
  const data = JSON.parse(event.data);
  if (data.type === 'ready') {
    startStreamingAudio(socket);
  } else if (data.text) {
    console.log('Agent:', data.text);
    // Optionally play via TTS if text-only
  }
};

function startStreamingAudio(socket) {
  navigator.mediaDevices.getUserMedia({ audio: true })
    .then(stream => {
      const audioContext = new AudioContext({ sampleRate: 16000 });
      const source = audioContext.createMediaStreamSource(stream);
      const processor = audioContext.createScriptProcessor(4096, 1, 1);

      processor.onaudioprocess = (e) => {
        const inputData = e.inputBuffer.getChannelData(0);
        // Convert Float32 to Int16
        const pcmData = convertFloat32ToInt16(inputData);
        socket.send(pcmData.buffer);
      };

      source.connect(processor);
      processor.connect(audioContext.destination);
    });
}
```
