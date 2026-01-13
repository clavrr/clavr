# Voice Interface Configuration Guide

This guide explains how to configure the voice interface features (Speech-to-Text and Text-to-Speech) for the Clavr Agent.

## Overview

The voice interface enables:
- **Speech-to-Text (STT)**: Convert voice input to text
- **Text-to-Speech (TTS)**: Convert text responses to audio
- **Voice normalization**: Clean and correct voice transcripts using LLM
- **Graph-grounded entity preservation**: Prevent over-correction of known contacts/projects

## Prerequisites

1. **Google Cloud Account**: Voice services use Google Cloud Speech-to-Text and Text-to-Speech APIs
2. **Service Account**: Create a service account with the following permissions:
   - `Cloud Speech-to-Text API User`
   - `Cloud Text-to-Speech API User`
3. **Service Account Key**: Download the JSON key file for your service account

## Configuration

### 1. Environment Variables

Set the `GOOGLE_APPLICATION_CREDENTIALS` environment variable to point to your service account key:

```bash
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/your/service-account-key.json
```

**Alternative**: If running on Google Cloud Platform (GCP), credentials are automatically detected from the metadata server. No need to set this variable.

### 2. Config File (`config/config.yaml`)

Add the voice configuration section:

```yaml
voice:
  enabled: true  # Enable/disable voice features
  
  # Speech-to-Text (STT) Configuration
  stt:
    provider: "google"  # Currently only "google" is supported
    language: "en-US"  # Language code (en-US, en-GB, es-ES, etc.)
    sample_rate: 24000  # Audio sample rate in Hz (24000 for webm/opus from browsers)
  
  # Text-to-Speech (TTS) Configuration
  tts:
    provider: "google"  # Currently only "google" is supported
    voice: "en-US-Neural2-D"  # Voice name
    language: "en-US"  # Language code
    speaking_rate: 1.0  # Speaking rate (0.25 to 4.0, 1.0 = normal speed)
    pitch: 0.0  # Pitch adjustment (-20.0 to 20.0 semitones, 0.0 = normal)
```

### 3. Available TTS Voices

Google Cloud TTS offers various neural voices. Common options:

**English (US)**:
- `en-US-Neural2-D` - Male voice (default)
- `en-US-Neural2-F` - Female voice
- `en-US-Neural2-J` - Male voice (alternative)
- `en-US-Studio-M` - Studio-quality male voice
- `en-US-Studio-O` - Studio-quality female voice

**English (GB)**:
- `en-GB-Neural2-B` - Male voice
- `en-GB-Neural2-D` - Female voice

**Other Languages**:
- Spanish: `es-US-Neural2-A`, `es-US-Neural2-B`
- French: `fr-FR-Neural2-A`, `fr-FR-Neural2-B`
- German: `de-DE-Neural2-A`, `de-DE-Neural2-B`
- And many more...

See [Google Cloud TTS Voices](https://cloud.google.com/text-to-speech/docs/voices) for the full list.

### 4. Configuration Parameters

#### STT Configuration

- **provider**: Currently only `"google"` is supported
- **language**: Language code in BCP-47 format (e.g., `"en-US"`, `"en-GB"`, `"es-ES"`)
- **sample_rate**: Audio sample rate in Hz. Use `24000` for WebM/Opus audio from browsers

#### TTS Configuration

- **provider**: Currently only `"google"` is supported
- **voice**: Voice name from Google Cloud TTS (see available voices above)
- **language**: Language code matching the voice
- **speaking_rate**: 
  - Range: 0.25 to 4.0
  - 1.0 = normal speed
  - 0.5 = half speed (slower)
  - 2.0 = double speed (faster)
- **pitch**: 
  - Range: -20.0 to 20.0 semitones
  - 0.0 = normal pitch
  - Negative = lower pitch
  - Positive = higher pitch

## Installation

Install the required Python packages:

```bash
pip install google-cloud-speech google-cloud-texttospeech
```

## Testing

### Test STT

```bash
curl -X POST http://localhost:8000/api/voice/transcribe \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "audio_data": "BASE64_ENCODED_AUDIO",
    "mime_type": "audio/webm"
  }'
```

### Test TTS

The TTS service is automatically used when processing voice queries. The response includes a `response_audio` field with base64-encoded MP3 audio.

## Troubleshooting

### Error: "Google Speech client not initialized"

**Solution**: 
1. Check that `GOOGLE_APPLICATION_CREDENTIALS` is set correctly
2. Verify the service account key file exists and is readable
3. Ensure the service account has the required permissions

### Error: "google-cloud-speech not installed"

**Solution**: 
```bash
pip install google-cloud-speech google-cloud-texttospeech
```

### Error: "Could not transcribe audio"

**Possible causes**:
1. Audio format not supported (use WebM/Opus from browser)
2. Audio too short or corrupted
3. Language mismatch (check `stt.language` in config)

### TTS Audio Not Playing

**Possible causes**:
1. Browser doesn't support base64 audio playback
2. Audio format mismatch (should be MP3)
3. CORS issues (check API CORS settings)

## Advanced Configuration

### Custom Voice Settings per User

You can extend the configuration to support per-user voice preferences by:
1. Storing user preferences in the database
2. Overriding TTS config in the voice router based on user preferences

### Multiple Language Support

To support multiple languages:
1. Detect user's language preference
2. Set `stt.language` and `tts.language` dynamically
3. Choose appropriate TTS voice for the language

## Cost Considerations

Google Cloud Speech-to-Text and Text-to-Speech are paid services:
- **STT**: ~$0.006 per 15 seconds of audio
- **TTS**: ~$0.016 per 1,000 characters

Consider:
- Caching normalized transcripts
- Limiting TTS to important responses
- Using shorter voice-formatted responses

## Security

- **Never commit** service account keys to version control
- Use environment variables for credentials
- Rotate service account keys regularly
- Use IAM roles with minimal required permissions

## Next Steps

1. Set up Google Cloud project and enable APIs
2. Create service account with required permissions
3. Download service account key
4. Set `GOOGLE_APPLICATION_CREDENTIALS` environment variable
5. Configure `config/config.yaml` with voice settings
6. Test voice endpoints

For more information, see:
- [Google Cloud Speech-to-Text Documentation](https://cloud.google.com/speech-to-text/docs)
- [Google Cloud Text-to-Speech Documentation](https://cloud.google.com/text-to-speech/docs)

