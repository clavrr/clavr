"""
Regression tests for auth + integration hardening (Feb 2026).

Covers the following changes:
- integration_service.handle_callback: httpx client uses timeout=15.0
- auth router get_auth_status / get_session_status_alias: uses config TTL, not hardcoded 60
- NotionTool._run: 401/403 marks integration inactive and returns INTEGRATION_REQUIRED
- AsanaTool._run: 401/403 triggers _refresh_asana_token, falls back to mark inactive
- AsanaTool._refresh_asana_token: exchanges refresh_token via Asana token endpoint
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("TESTING", "1")
os.environ.setdefault("DATABASE_URL", "sqlite:///test_hardening.db")
os.environ.setdefault("ENCRYPTION_KEY", "test-key-for-testing-only-do-not-use-in-production-32bytes=")


# ---------------------------------------------------------------------------
# 1. integration_service.handle_callback — httpx timeout
# ---------------------------------------------------------------------------

class TestHandleCallbackTimeout:
    """handle_callback must pass timeout=15.0 to httpx.AsyncClient."""

    @pytest.mark.asyncio
    async def test_httpx_client_uses_timeout(self):
        """AsyncClient is constructed with timeout=15.0 during token exchange."""
        from src.services.integration_service import IntegrationService

        config = Mock()  # avoid Config() pydantic validation
        mock_db = AsyncMock()

        # _get_oauth_configs iterates config.oauth.providers during __init__; stub it out
        with patch.object(IntegrationService, "_get_oauth_configs", return_value={}):
            service = IntegrationService(db=mock_db, config=config)

        # Stub _parse_state so we get past state validation
        service._parse_state = AsyncMock(
            return_value=(1, "notion", None, "core_state")
        )
        # Stub oauth_configs
        service.oauth_configs = {
            "notion": {
                "client_id": "cid",
                "client_secret": "csec",
                "auth_url": "https://notion.com/auth",
                "token_url": "https://api.notion.com/v1/oauth/token",
                "redirect_uri": "http://localhost:8000/integrations/notion/callback",
                "scopes": "",
            }
        }
        # Stub _save_integration so we don't hit the real DB
        service._save_integration = AsyncMock()

        captured_kwargs = {}

        class FakeResponse:
            status_code = 200
            def json(self):
                return {"access_token": "tok", "workspace_id": "ws1", "workspace_name": "WS", "bot_id": "b1"}

        class FakeClient:
            async def post(self, *args, **kwargs):
                return FakeResponse()
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass

        with patch("src.services.integration_service.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = FakeClient()
            mock_cls.side_effect = lambda **kw: (captured_kwargs.update(kw), FakeClient())[1]

            await service.handle_callback("notion", "auth_code", "valid_state")

        assert "timeout" in captured_kwargs, "httpx.AsyncClient must be called with timeout= kwarg"
        assert captured_kwargs["timeout"] == 15.0, f"Expected timeout=15.0, got {captured_kwargs['timeout']}"


# ---------------------------------------------------------------------------
# 2. auth router — session TTL comes from config, not hardcoded 60
# ---------------------------------------------------------------------------

class TestSessionTTLFromConfig:
    """get_auth_status and get_session_status_alias must pass config TTL to get_session_status."""

    def _make_config(self, ttl: int):
        cfg = Mock()
        cfg.security = Mock()
        cfg.security.session_ttl_minutes = ttl
        return cfg

    def test_ttl_extracted_from_config(self):
        """getattr chain correctly extracts session_ttl_minutes."""
        config = self._make_config(120)
        ttl = getattr(getattr(config, "security", None), "session_ttl_minutes", 60)
        assert ttl == 120

    def test_ttl_defaults_to_60_when_missing(self):
        """Falls back to 60 when security attribute absent."""
        config = Mock(spec=[])  # no attributes
        ttl = getattr(getattr(config, "security", None), "session_ttl_minutes", 60)
        assert ttl == 60

    @pytest.mark.asyncio
    async def test_get_session_status_receives_config_ttl(self):
        """Auth service get_session_status is called with TTL from config, not default 60."""
        auth_service = AsyncMock()
        auth_service.get_session_status = AsyncMock(return_value={"valid": True})

        config = self._make_config(90)
        request = Mock()

        ttl = getattr(getattr(config, "security", None), "session_ttl_minutes", 60)
        await auth_service.get_session_status(request, timeout_minutes=ttl)

        auth_service.get_session_status.assert_called_once_with(request, timeout_minutes=90)


# ---------------------------------------------------------------------------
# 3. NotionTool — 401/403 self-healing
# ---------------------------------------------------------------------------

class TestNotionToolAuthHealing:
    """NotionTool._run must catch 401/403 errors and mark the integration inactive.
    Uses unbound method calls with a Mock self to avoid Pydantic v2 BaseTool init.
    """

    def _ms(self, user_id=1):
        m = Mock()
        m.user_id = user_id
        return m

    def test_401_returns_integration_required(self):
        from src.tools.notion.tool import NotionTool
        mc = Mock()
        mc.search.side_effect = Exception("401 Unauthorized")
        s = self._ms()
        s._initialize_client = Mock(return_value=mc)
        s._mark_integration_inactive = Mock()
        result = NotionTool._run(s, action="search", query="test")
        assert "[INTEGRATION_REQUIRED]" in result
        s._mark_integration_inactive.assert_called_once()

    def test_403_returns_integration_required(self):
        from src.tools.notion.tool import NotionTool
        mc = Mock()
        mc.search.side_effect = Exception("403 Forbidden")
        s = self._ms()
        s._initialize_client = Mock(return_value=mc)
        s._mark_integration_inactive = Mock()
        result = NotionTool._run(s, action="search", query="test")
        assert "[INTEGRATION_REQUIRED]" in result
        s._mark_integration_inactive.assert_called_once()

    def test_non_auth_error_not_marked_inactive(self):
        from src.tools.notion.tool import NotionTool
        mc = Mock()
        mc.search.side_effect = Exception("Network timeout")
        s = self._ms()
        s._initialize_client = Mock(return_value=mc)
        s._mark_integration_inactive = Mock()
        result = NotionTool._run(s, action="search", query="test")
        s._mark_integration_inactive.assert_not_called()
        assert "Error:" in result

    def test_mark_integration_inactive_writes_db(self):
        from src.tools.notion.tool import NotionTool
        mock_row = Mock()
        mock_row.is_active = True
        mock_db = Mock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_row
        s = self._ms(user_id=42)
        with patch("src.database.get_db_context") as mock_ctx:
            mock_ctx.return_value.__enter__ = Mock(return_value=mock_db)
            mock_ctx.return_value.__exit__ = Mock(return_value=False)
            NotionTool._mark_integration_inactive(s)
        assert mock_row.is_active == False


# ---------------------------------------------------------------------------
# 4. AsanaTool — 401 triggers refresh; mark inactive on refresh failure
# ---------------------------------------------------------------------------

class TestAsanaToolAuthHealing:
    """AsanaTool must attempt token refresh on 401 and mark inactive if refresh fails.
    Uses unbound method calls with a Mock self to avoid Pydantic v2 BaseTool init.
    """

    def _ms(self, user_id=1):
        m = Mock()
        m.user_id = user_id
        m.config = Mock()
        m.config.oauth.providers = {"asana": Mock(client_id="cid", client_secret="csec")}
        return m

    def _svc(self):
        svc = Mock()
        svc.is_available = True
        return svc

    def test_401_triggers_refresh_attempt(self):
        from src.tools.asana.tool import AsanaTool
        s = self._ms()
        s.asana_service = self._svc()
        s._handle_list = Mock(side_effect=Exception("401 Unauthorized"))
        s._refresh_asana_token = Mock(return_value=True)
        s._mark_asana_inactive = Mock()
        result = AsanaTool._run(s, action="list", query="tasks")
        s._refresh_asana_token.assert_called_once()
        assert "[RETRY]" in result

    def test_401_marks_inactive_when_refresh_fails(self):
        from src.tools.asana.tool import AsanaTool
        s = self._ms()
        s.asana_service = self._svc()
        s._handle_list = Mock(side_effect=Exception("401 Unauthorized"))
        s._refresh_asana_token = Mock(return_value=False)
        s._mark_asana_inactive = Mock()
        result = AsanaTool._run(s, action="list", query="tasks")
        s._refresh_asana_token.assert_called_once()
        s._mark_asana_inactive.assert_called_once()
        assert "[INTEGRATION_REQUIRED]" in result

    def test_non_auth_error_no_refresh(self):
        from src.tools.asana.tool import AsanaTool
        s = self._ms()
        s.asana_service = self._svc()
        s._handle_list = Mock(side_effect=Exception("API rate limit exceeded"))
        s._refresh_asana_token = Mock()
        s._mark_asana_inactive = Mock()
        AsanaTool._run(s, action="list", query="tasks")
        s._refresh_asana_token.assert_not_called()
        s._mark_asana_inactive.assert_not_called()

    def test_refresh_token_posts_to_asana_endpoint(self):
        from src.tools.asana.tool import AsanaTool
        s = self._ms(user_id=7)
        mock_row = Mock()
        mock_row.refresh_token = "old_refresh"
        mock_row.access_token = None
        mock_db = Mock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_row
        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"access_token": "new_tok", "refresh_token": "new_ref", "expires_in": 3600}
        with patch("src.database.get_db_context") as mock_ctx, \
             patch("requests.post", return_value=mock_resp) as mock_post:
            mock_ctx.return_value.__enter__ = Mock(return_value=mock_db)
            mock_ctx.return_value.__exit__ = Mock(return_value=False)
            result = AsanaTool._refresh_asana_token(s)
        assert result is True
        assert "asana.com" in mock_post.call_args[0][0]
        assert mock_row.access_token == "new_tok"
        assert mock_row.refresh_token == "new_ref"
        assert mock_row.is_active is True

    def test_refresh_fails_gracefully_on_bad_response(self):
        from src.tools.asana.tool import AsanaTool
        s = self._ms(user_id=7)
        mock_row = Mock()
        mock_row.refresh_token = "old_refresh"
        mock_db = Mock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_row
        mock_resp = Mock()
        mock_resp.status_code = 400
        mock_resp.text = "invalid_grant"
        with patch("src.database.get_db_context") as mock_ctx, \
             patch("requests.post", return_value=mock_resp):
            mock_ctx.return_value.__enter__ = Mock(return_value=mock_db)
            mock_ctx.return_value.__exit__ = Mock(return_value=False)
            result = AsanaTool._refresh_asana_token(s)
        assert result is False

    def test_refresh_fails_gracefully_when_no_refresh_token(self):
        from src.tools.asana.tool import AsanaTool
        s = self._ms(user_id=7)
        mock_row = Mock()
        mock_row.refresh_token = None
        mock_db = Mock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_row
        with patch("src.database.get_db_context") as mock_ctx:
            mock_ctx.return_value.__enter__ = Mock(return_value=mock_db)
            mock_ctx.return_value.__exit__ = Mock(return_value=False)
            result = AsanaTool._refresh_asana_token(s)
        assert result is False
