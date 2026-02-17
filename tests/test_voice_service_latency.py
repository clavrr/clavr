import pytest
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch
from src.services.voice_service import VoiceService
from src.database.models import User

@pytest.mark.asyncio
async def test_voice_service_parallel_initialization_latency():
    """
    Verify that VoiceService initializes components in parallel.
    We mock dependencies with delays and check if total time is approx max(delays)
    rather than sum(delays).
    """
    # Setup
    mock_db = AsyncMock()
    mock_config = MagicMock()
    mock_user = User(id=1, email="test@test.com", name="Test User")
    
    # Mock Clients
    mock_elevenlabs_client = MagicMock()
    mock_elevenlabs_client.warmup = AsyncMock()
    # Mock warmup to take time
    async def slow_warmup():
        await asyncio.sleep(0.1)
    mock_elevenlabs_client.warmup.side_effect = slow_warmup
    
    mock_elevenlabs_client.stream_audio = AsyncMock()
    async def empty_gen(*args, **kwargs):
        if False: yield
    mock_elevenlabs_client.stream_audio.return_value = empty_gen()

    # Define delays
    # Context: 0.1s
    # Config: 0.05s
    # Tools (Thread): 0.1s
    # Warmup: 0.1s
    # Expected total: ~0.1s (parallel) vs 0.35s (serial)

    async def slow_context(*args, **kwargs):
        await asyncio.sleep(0.1)
        return "context"
        
    async def fast_config(*args, **kwargs):
        await asyncio.sleep(0.05)
        return {}
        
    async def mocked_to_thread(func, *args, **kwargs):
        # Simulate thread execution time
        await asyncio.sleep(0.1) 
        return [MagicMock(name="tool")]

    # Patches
    # Note: We patch asyncio.to_thread in the voice_service module scope
    with patch("src.services.voice_service.asyncio.to_thread", side_effect=mocked_to_thread) as mock_thread, \
         patch.object(VoiceService, "get_voice_context", side_effect=slow_context), \
         patch.object(VoiceService, "get_voice_configuration", side_effect=fast_config), \
         patch("src.services.voice_service.ElevenLabsLiveClient", return_value=mock_elevenlabs_client), \
         patch.dict("os.environ", {"ELEVENLABS_AGENT_ID": "test_agent_id"}):

        # Init Service
        service = VoiceService(mock_db, mock_config)
        
        # Measure Execution Time
        start_time = time.time()
        
        mock_ws = AsyncMock()
        
        await service.process_voice_stream(
            user=mock_user,
            audio_generator=empty_gen(),
            websocket=mock_ws
        )
        
        duration = time.time() - start_time
        
        print(f"Execution took {duration:.3f}s")
        
        # Assert parallel execution
        # Should be close to max(0.1, 0.1, 0.05) = 0.1
        # Allow up to 0.25s for overhead, but definitely less than serial sum (0.35s)
        assert duration < 0.25, f"Expected < 0.25s, got {duration:.3f}s"
        
        # Verify calls
        mock_thread.assert_called_once() # Ensures to_thread was used
        service.get_voice_context.assert_called_once()
        service.get_voice_configuration.assert_called_once()
        mock_elevenlabs_client.warmup.assert_called_once()
