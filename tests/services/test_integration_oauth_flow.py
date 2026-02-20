"""Unit tests for hardened integration OAuth callback flow."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.database.models import OAuthState
from src.services.integration_service import IntegrationCallbackResult, IntegrationService


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _DummyResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = "ok"

    def json(self):
        return self._payload


class _DummyHttpClient:
    def __init__(self, payload, recorder):
        self._payload = payload
        self._recorder = recorder

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return False

    async def post(self, url, data=None, headers=None, auth=None):
        self._recorder["url"] = url
        self._recorder["data"] = data
        self._recorder["headers"] = headers
        self._recorder["auth"] = auth
        return _DummyResponse(self._payload)


@pytest.fixture
def integration_config():
    providers = {
        "notion": SimpleNamespace(
            client_id="notion-client",
            client_secret="notion-secret",
            auth_url="https://api.notion.com/v1/oauth/authorize",
            token_url="https://api.notion.com/v1/oauth/token",
            scopes=None,
            redirect_uri="https://api.example.com/integrations/notion/callback",
            owner="user",
        ),
        "asana": SimpleNamespace(
            client_id="asana-client",
            client_secret="asana-secret",
            auth_url="https://app.asana.com/-/oauth_authorize",
            token_url="https://app.asana.com/-/oauth_token",
            scopes="default",
            redirect_uri="https://api.example.com/integrations/asana/callback",
            owner=None,
        ),
    }

    return SimpleNamespace(
        oauth=SimpleNamespace(providers=providers),
        security=SimpleNamespace(secret_key="test-secret-key"),
    )


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.execute = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_asana_auth_url_contains_secure_state_and_pkce(mock_db, integration_config):
    service = IntegrationService(db=mock_db, config=integration_config)

    auth_url = await service.get_auth_url(
        provider="asana",
        user_id=17,
        redirect_to="/integrations",
    )

    query = parse_qs(urlparse(auth_url).query)
    state = query["state"][0]

    assert state.startswith("int_")
    assert "|" in state
    assert query["code_challenge_method"][0] == "S256"
    assert query["code_challenge"][0]

    saved_state = mock_db.add.call_args[0][0]
    assert isinstance(saved_state, OAuthState)
    assert saved_state.state == state.split("|", 1)[0]
    assert saved_state.used is False


@pytest.mark.asyncio
async def test_handle_callback_returns_typed_result_and_marks_state_used(
    mock_db,
    integration_config,
    monkeypatch,
):
    service = IntegrationService(db=mock_db, config=integration_config)

    auth_url = await service.get_auth_url(
        provider="asana",
        user_id=9,
        redirect_to="/dashboard",
    )
    state = parse_qs(urlparse(auth_url).query)["state"][0]
    state_core = state.split("|", 1)[0]

    oauth_state = OAuthState(
        state=state_core,
        expires_at=datetime.utcnow() + timedelta(minutes=5),
        used=False,
    )
    mock_db.execute = AsyncMock(return_value=_ScalarResult(oauth_state))

    token_payload = {
        "access_token": "new-access-token",
        "refresh_token": "refresh-token",
        "scope": "tasks:read",
    }
    recorder = {}
    monkeypatch.setattr(
        "src.services.integration_service.httpx.AsyncClient",
        lambda: _DummyHttpClient(token_payload, recorder),
    )

    service._save_integration = AsyncMock()  # type: ignore[method-assign]

    callback_result = await service.handle_callback(
        provider="asana",
        code="auth-code",
        state=state,
    )

    assert isinstance(callback_result, IntegrationCallbackResult)
    assert callback_result.provider == "asana"
    assert callback_result.user_id == 9
    assert callback_result.redirect_to == "/dashboard"
    assert callback_result.token_data["access_token"] == "new-access-token"

    assert recorder["data"]["code_verifier"]
    assert oauth_state.used is True


@pytest.mark.asyncio
async def test_secure_state_replay_is_rejected(mock_db, integration_config):
    service = IntegrationService(db=mock_db, config=integration_config)

    auth_url = await service.get_auth_url(provider="notion", user_id=2)
    state = parse_qs(urlparse(auth_url).query)["state"][0]

    mock_db.execute = AsyncMock(return_value=_ScalarResult(None))

    with pytest.raises(ValueError, match="Invalid or expired state"):
        await service.handle_callback(
            provider="notion",
            code="auth-code",
            state=state,
        )


class TestIntegrationOAuthRegression:
    """Regression tests for OAuth edge-cases and security guarantees."""

    @pytest.mark.asyncio
    async def test_secure_state_provider_mismatch_is_rejected(self, mock_db, integration_config):
        """Regression: callback provider must match signed provider in secure state."""
        service = IntegrationService(db=mock_db, config=integration_config)

        auth_url = await service.get_auth_url(provider="asana", user_id=42)
        state = parse_qs(urlparse(auth_url).query)["state"][0]

        with pytest.raises(ValueError, match="Provider mismatch in state"):
            await service.handle_callback(
                provider="notion",
                code="auth-code",
                state=state,
            )

    @pytest.mark.asyncio
    async def test_secure_state_tampered_redirect_blob_is_rejected(self, mock_db, integration_config):
        """Regression: tampered redirect payload must fail before token exchange."""
        service = IntegrationService(db=mock_db, config=integration_config)

        auth_url = await service.get_auth_url(
            provider="asana",
            user_id=18,
            redirect_to="/integrations",
        )
        state = parse_qs(urlparse(auth_url).query)["state"][0]
        state_core = state.split("|", 1)[0]
        tampered_state = f"{state_core}|__8"

        with pytest.raises(ValueError, match="Invalid redirect target in state"):
            await service.handle_callback(
                provider="asana",
                code="auth-code",
                state=tampered_state,
            )

    @pytest.mark.asyncio
    async def test_secure_state_is_one_time_use_end_to_end(self, mock_db, integration_config, monkeypatch):
        """Regression: same secure state cannot be reused after first successful callback."""
        service = IntegrationService(db=mock_db, config=integration_config)

        auth_url = await service.get_auth_url(
            provider="asana",
            user_id=22,
            redirect_to="/dashboard",
        )
        state = parse_qs(urlparse(auth_url).query)["state"][0]
        state_core = state.split("|", 1)[0]

        oauth_state = OAuthState(
            state=state_core,
            expires_at=datetime.utcnow() + timedelta(minutes=5),
            used=False,
        )
        mock_db.execute = AsyncMock(side_effect=[_ScalarResult(oauth_state), _ScalarResult(None)])

        recorder = {}
        monkeypatch.setattr(
            "src.services.integration_service.httpx.AsyncClient",
            lambda: _DummyHttpClient({"access_token": "token-1"}, recorder),
        )

        service._save_integration = AsyncMock()  # type: ignore[method-assign]

        first = await service.handle_callback(
            provider="asana",
            code="auth-code-1",
            state=state,
        )

        assert first.user_id == 22
        assert oauth_state.used is True

        with pytest.raises(ValueError, match="Invalid or expired state"):
            await service.handle_callback(
                provider="asana",
                code="auth-code-2",
                state=state,
            )

    @pytest.mark.asyncio
    async def test_asana_pkce_verifier_matches_auth_url_challenge(self, mock_db, integration_config, monkeypatch):
        """Regression: PKCE verifier used during token exchange must match auth-url challenge."""
        service = IntegrationService(db=mock_db, config=integration_config)

        auth_url = await service.get_auth_url(provider="asana", user_id=31)
        query = parse_qs(urlparse(auth_url).query)
        state = query["state"][0]
        expected_challenge = query["code_challenge"][0]
        state_core = state.split("|", 1)[0]

        oauth_state = OAuthState(
            state=state_core,
            expires_at=datetime.utcnow() + timedelta(minutes=5),
            used=False,
        )
        mock_db.execute = AsyncMock(return_value=_ScalarResult(oauth_state))

        recorder = {}
        monkeypatch.setattr(
            "src.services.integration_service.httpx.AsyncClient",
            lambda: _DummyHttpClient({"access_token": "token-2"}, recorder),
        )

        service._save_integration = AsyncMock()  # type: ignore[method-assign]

        await service.handle_callback(
            provider="asana",
            code="auth-code",
            state=state,
        )

        code_verifier = recorder["data"]["code_verifier"]
        assert service._build_pkce_challenge(code_verifier) == expected_challenge

    @pytest.mark.asyncio
    async def test_notion_token_exchange_uses_basic_auth_contract(self, mock_db, integration_config, monkeypatch):
        """Regression: Notion token exchange must use HTTP basic auth and omit client creds from form body."""
        service = IntegrationService(db=mock_db, config=integration_config)

        auth_url = await service.get_auth_url(provider="notion", user_id=7)
        state = parse_qs(urlparse(auth_url).query)["state"][0]
        state_core = state.split("|", 1)[0]

        oauth_state = OAuthState(
            state=state_core,
            expires_at=datetime.utcnow() + timedelta(minutes=5),
            used=False,
        )
        mock_db.execute = AsyncMock(return_value=_ScalarResult(oauth_state))

        recorder = {}
        monkeypatch.setattr(
            "src.services.integration_service.httpx.AsyncClient",
            lambda: _DummyHttpClient({"access_token": "notion-token"}, recorder),
        )

        service._save_integration = AsyncMock()  # type: ignore[method-assign]

        await service.handle_callback(
            provider="notion",
            code="auth-code",
            state=state,
        )

        assert recorder["auth"] == ("notion-client", "notion-secret")
        assert "client_id" not in recorder["data"]
        assert "client_secret" not in recorder["data"]
