import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, ANY
from src.services.voice_service import VoiceService
from src.database.models import User

@pytest.mark.asyncio
class TestVoiceServiceRegression:
    """
    Regression and fault tolerance tests for VoiceService.
    Ensures that the parallel initialization logic handles failures gracefully
    and correctly passes data to the client.
    """

    @pytest.fixture
    def mock_service(self):
        with patch("src.services.voice_service.get_context_service") as mock_get_ctx:
            mock_ctx_svc = MagicMock()
            mock_get_ctx.return_value = mock_ctx_svc
            
            mock_db = AsyncMock()
            mock_config = MagicMock()
            service = VoiceService(mock_db, mock_config)
            return service


    @pytest.fixture
    def mock_user(self):
        return User(id=1, email="test@test.com", name="Test User")

    @pytest.fixture
    def mock_elevenlabs_client(self):
        client = MagicMock()
        client.warmup = AsyncMock()
        
        async def empty_gen(*args, **kwargs):
            if False: yield
            
        # stream_audio should be a callable that returns the generator, NOT an AsyncMock
        # (AsyncMock returns a coroutine, which async for cannot iterate)
        client.stream_audio = MagicMock(side_effect=empty_gen)
        client.tools = []
        return client
        
    @pytest.fixture
    def mock_deps(self):
        """Standard dependencies mock."""
        with patch("src.services.voice_service.asyncio.to_thread", new_callable=AsyncMock) as mock_thread, \
             patch.object(VoiceService, "get_voice_context", new_callable=AsyncMock) as mock_context, \
             patch.object(VoiceService, "get_voice_configuration", new_callable=AsyncMock) as mock_config, \
             patch.dict("os.environ", {"ELEVENLABS_AGENT_ID": "test_agent_id"}):
            
            # Default successful returns
            mock_thread.return_value = [MagicMock(name="tool_1")]
            mock_context.return_value = "System Context"
            mock_config.return_value = {"var": "val"}
            
            yield mock_thread, mock_context, mock_config

    async def test_process_voice_stream_success(self, mock_service, mock_user, mock_elevenlabs_client, mock_deps):
        """Happy path: All initialization tasks succeed."""
        mock_thread, mock_context, mock_config = mock_deps
        
        with patch("src.services.voice_service.ElevenLabsLiveClient", return_value=mock_elevenlabs_client):
            await mock_service.process_voice_stream(
                user=mock_user,
                audio_generator=AsyncMock(),
                websocket=AsyncMock()
            )
            
            # Verify Warmup called
            mock_elevenlabs_client.warmup.assert_called_once()


            
            # Verify stream_audio called with correct data
            mock_elevenlabs_client.stream_audio.assert_called_once_with(
                ANY, 
                system_instruction_extras="System Context",
                dynamic_variables={"var": "val"}
            )
            
            # Verify tools injected
            assert len(mock_elevenlabs_client.tools) == 1

    async def test_process_voice_stream_tool_failure(self, mock_service, mock_user, mock_elevenlabs_client, mock_deps):
        """Fault tolerance: Tool loading fails, stream should continue without tools."""
        mock_thread, mock_context, mock_config = mock_deps
        
        # Simulate tool loading failure
        mock_thread.side_effect = Exception("DB Connection Failed")
        
        with patch("src.services.voice_service.ElevenLabsLiveClient", return_value=mock_elevenlabs_client):
            await mock_service.process_voice_stream(
                user=mock_user,
                audio_generator=AsyncMock(),
                websocket=AsyncMock()
            )
            
            # Stream should still start
            mock_elevenlabs_client.stream_audio.assert_called_once()
            
            # Client tools should be empty list (fallback)
            assert mock_elevenlabs_client.tools == []

    async def test_process_voice_stream_context_failure(self, mock_service, mock_user, mock_elevenlabs_client, mock_deps):
        """Fault tolerance: Context loading fails, stream should continue with empty context."""
        mock_thread, mock_context, mock_config = mock_deps
        
        # Simulate context failure
        mock_context.side_effect = Exception("RAG service down")
        
        with patch("src.services.voice_service.ElevenLabsLiveClient", return_value=mock_elevenlabs_client):
            await mock_service.process_voice_stream(
                user=mock_user,
                audio_generator=AsyncMock(),
                websocket=AsyncMock()
            )
            
            # Stream checks
            args, kwargs = mock_elevenlabs_client.stream_audio.call_args
            assert kwargs["system_instruction_extras"] == "" or kwargs["system_instruction_extras"] is None

    async def test_process_voice_stream_config_failure(self, mock_service, mock_user, mock_elevenlabs_client, mock_deps):
        """Fault tolerance: Config loading fails, stream should continue with empty config."""
        mock_thread, mock_context, mock_config = mock_deps
        
        # Simulate config failure
        mock_config.side_effect = Exception("Config error")
        
        with patch("src.services.voice_service.ElevenLabsLiveClient", return_value=mock_elevenlabs_client):
            await mock_service.process_voice_stream(
                user=mock_user,
                audio_generator=AsyncMock(),
                websocket=AsyncMock()
            )
            
            # Stream checks
            args, kwargs = mock_elevenlabs_client.stream_audio.call_args
            assert kwargs["dynamic_variables"] == {}

    async def test_warmup_failure(self, mock_service, mock_user, mock_elevenlabs_client, mock_deps):
        """Fault tolerance: Warmup fails (e.g. network error), stream should continue."""
        mock_thread, mock_context, mock_config = mock_deps
        
        # Simulate warmup failure
        mock_elevenlabs_client.warmup.side_effect = Exception("Network timeout")
        
        with patch("src.services.voice_service.ElevenLabsLiveClient", return_value=mock_elevenlabs_client):
            await mock_service.process_voice_stream(
                user=mock_user,
                audio_generator=AsyncMock(),
                websocket=AsyncMock()
            )
            
            # Stream should still happen (process_voice_stream catches warmup exceptions via asyncio.gather(return_exceptions=True))
            mock_elevenlabs_client.stream_audio.assert_called_once()

    async def test_system_extras_preservation(self, mock_service, mock_user, mock_elevenlabs_client, mock_deps):
        """Extras (e.g. from wake word) should be preserved even if context fails."""
        mock_thread, mock_context, mock_config = mock_deps
        
        mock_context.side_effect = Exception("Context failed")
        
        with patch("src.services.voice_service.ElevenLabsLiveClient", return_value=mock_elevenlabs_client):
            await mock_service.process_voice_stream(
                user=mock_user,
                audio_generator=AsyncMock(),
                websocket=AsyncMock(),
                system_extras="Important Wake Word Info"
            )
            
            args, kwargs = mock_elevenlabs_client.stream_audio.call_args
            assert "Important Wake Word Info" in kwargs["system_instruction_extras"]
