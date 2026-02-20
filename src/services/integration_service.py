"""
IntegrationService - Manages third-party integrations and OAuth flows.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import base64
import hashlib
import hmac
import httpx
import secrets
from urllib.parse import urlencode, quote

import os
from src.database.models import OAuthState, UserIntegration
from src.utils.logger import setup_logger
from src.utils.config import Config
from src.auth.oauth import GMAIL_SCOPES, CALENDAR_SCOPES, TASKS_SCOPES, DRIVE_SCOPES

logger = setup_logger(__name__)


@dataclass
class IntegrationCallbackResult:
    provider: str
    user_id: int
    token_data: Dict[str, Any]
    redirect_to: Optional[str] = None

class IntegrationService:
    STATE_PREFIX = "int"
    STATE_TTL_MINUTES = 10
    STATE_SIGNATURE_LENGTH = 16

    def __init__(self, db: AsyncSession, config: Config):
        self.db = db
        self.config = config
        self.oauth_configs = self._get_oauth_configs()

    def _get_oauth_configs(self) -> Dict[str, Any]:
        """Get OAuth configurations from config object."""
        configs = {}
        if self.config.oauth and self.config.oauth.providers:
            # Convert provider models to dicts
            for name, p in self.config.oauth.providers.items():
                configs[name] = {
                    "client_id": p.client_id,
                    "client_secret": p.client_secret,
                    "auth_url": p.auth_url,
                    "token_url": p.token_url,
                    "scopes": p.scopes,
                    "redirect_uri": p.redirect_uri,
                    "owner": getattr(p, 'owner', None)
                }
            
            # Gmail/Calendar/Tasks use same config as Google (same OAuth credentials and redirect URI)
            # The redirect goes to /auth/google/callback which needs to detect
            # if this is an integration connect vs a login based on state
            if 'google' in configs:
                # Map aliases to their specific granular scopes
                alias_scopes = {
                    'gmail': " ".join(GMAIL_SCOPES),
                    'google_calendar': " ".join(CALENDAR_SCOPES),
                    'google_tasks': " ".join(TASKS_SCOPES),
                    'google_drive': " ".join(DRIVE_SCOPES)
                }
                
                for alias, scopes in alias_scopes.items():
                    if alias not in configs:
                        configs[alias] = configs['google'].copy()
                        configs[alias]['scopes'] = scopes
                        logger.info(f"Initialized {alias} with granular scopes")
        
        return configs

    async def get_auth_url(self, provider: str, user_id: int, user_email: Optional[str] = None, redirect_to: Optional[str] = None) -> str:
        """Generate authorization URL for a provider.
        
        Args:
            provider: Integration provider (e.g., 'gmail')
            user_id: ID of the user linking the integration
            user_email: Optional email hint
            redirect_to: Optional path to redirect back to after flow (e.g., '/dashboard')
        """
        config = self.oauth_configs.get(provider)
        if not config:
            raise ValueError(f"Provider {provider} not supported")
        
        if not config.get("client_id") or not config.get("client_secret"):
            raise ValueError(f"Missing configuration for {provider}")
        
        state = await self._generate_integration_state(
            user_id=user_id,
            provider=provider,
            redirect_to=redirect_to
        )
        state_core = state.split("|", 1)[0]
        
        if provider == "notion":
            url = (
                f"{config['auth_url']}?"
                f"owner=user&"
                f"client_id={config['client_id']}&"
                f"redirect_uri={quote(config['redirect_uri'], safe='')}&"
                f"response_type=code&"
                f"state={quote(state, safe='')}"
            )
            return url
        
        params = {
            "client_id": config["client_id"],
            "redirect_uri": config["redirect_uri"],
            "response_type": "code",
            "state": state
        }
        
        if config.get("scopes"):
            params["scope"] = config["scopes"]

        if provider == "asana":
            code_verifier = self._build_asana_pkce_verifier(state_core)
            params["code_challenge"] = self._build_pkce_challenge(code_verifier)
            params["code_challenge_method"] = "S256"
        
        if provider.startswith("google") or provider == "gmail":
            params["access_type"] = "offline"
            params["prompt"] = "consent"
            if user_email:
                params["login_hint"] = user_email
                
        return f"{config['auth_url']}?{urlencode(params)}"

    def get_provider_hint_from_state(self, state: str) -> str:
        """Extract provider from integration state without consuming it."""
        state_core = (state or "").split("|", 1)[0]

        if state_core.startswith(f"{self.STATE_PREFIX}_"):
            try:
                payload = state_core[len(self.STATE_PREFIX) + 1:]
                _, rest = payload.split("_", 1)
                provider = rest.rsplit("_", 2)[0]
            except (ValueError, IndexError) as exc:
                raise ValueError("Invalid integration state") from exc

            if not provider:
                raise ValueError("Invalid integration state")
            return provider

        if state_core.startswith("user_"):
            parts = state_core.split("_")
            if len(parts) < 3:
                raise ValueError("Invalid integration state")
            return "_".join(parts[2:])

        raise ValueError("State is not an integration flow state")

    async def handle_callback(self, provider: str, code: str, state: str) -> IntegrationCallbackResult:
        """Process OAuth callback and store tokens."""
        user_id, real_provider, redirect_to, state_core = await self._parse_state(
            callback_provider=provider,
            state=state
        )

        config = self.oauth_configs.get(real_provider)
        if not config:
            raise ValueError("Invalid provider")
            
        # Token exchange
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": config["redirect_uri"],
            "client_id": config["client_id"],
            "client_secret": config["client_secret"]
        }
        
        headers = {"Accept": "application/json"}
        auth = None
        if real_provider == "asana":
            data["code_verifier"] = self._build_asana_pkce_verifier(state_core)

        if real_provider == "notion":
            auth = (config["client_id"], config["client_secret"])
            del data["client_id"]
            del data["client_secret"]
            
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(config["token_url"], data=data, headers=headers, auth=auth)
            if response.status_code != 200:
                logger.error(f"Failed to exchange token for {real_provider}: {response.text}")
                raise Exception("Token exchange failed")
                
            token_data = response.json()
            await self._save_integration(user_id, real_provider, token_data, client)

        return IntegrationCallbackResult(
            provider=real_provider,
            user_id=user_id,
            token_data=token_data,
            redirect_to=redirect_to,
        )

    def _get_state_signing_key(self) -> str:
        """Get signing key for integration OAuth state."""
        key = os.getenv("SECRET_KEY")
        if key:
            return key

        if self.config.security and self.config.security.secret_key:
            return self.config.security.secret_key

        raise ValueError("SECRET_KEY is required for integration OAuth state signing")

    def _state_signature(self, user_id: int, provider: str, nonce: str, redirect_to: Optional[str]) -> str:
        payload = f"{user_id}:{provider}:{nonce}:{redirect_to or ''}"
        digest = hmac.new(
            self._get_state_signing_key().encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return digest[: self.STATE_SIGNATURE_LENGTH]

    def _encode_redirect(self, redirect_to: str) -> str:
        return base64.urlsafe_b64encode(redirect_to.encode("utf-8")).decode("utf-8").rstrip("=")

    def _decode_redirect(self, encoded_redirect: str) -> str:
        padding = "=" * (-len(encoded_redirect) % 4)
        return base64.urlsafe_b64decode(f"{encoded_redirect}{padding}").decode("utf-8")

    def _build_asana_pkce_verifier(self, state_core: str) -> str:
        """Derive deterministic PKCE verifier from state core and server secret."""
        seed = f"{state_core}:{self._get_state_signing_key()}".encode("utf-8")
        digest = hashlib.sha256(seed).digest()
        verifier = base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")

        # PKCE verifier must be 43-128 characters.
        if len(verifier) < 43:
            verifier = (verifier + ("A" * 43))[:43]
        return verifier[:128]

    def _build_pkce_challenge(self, code_verifier: str) -> str:
        digest = hashlib.sha256(code_verifier.encode("utf-8")).digest()
        return base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")

    async def _generate_integration_state(self, user_id: int, provider: str, redirect_to: Optional[str]) -> str:
        nonce = secrets.token_urlsafe(5)
        signature = self._state_signature(user_id, provider, nonce, redirect_to)
        state_core = f"{self.STATE_PREFIX}_{user_id}_{provider}_{nonce}_{signature}"

        if len(state_core) > 64:
            raise ValueError("Generated OAuth state exceeds storage limit")

        oauth_state = OAuthState(
            state=state_core,
            expires_at=datetime.utcnow() + timedelta(minutes=self.STATE_TTL_MINUTES),
            used=False,
        )
        self.db.add(oauth_state)
        await self.db.commit()

        if redirect_to:
            return f"{state_core}|{self._encode_redirect(redirect_to)}"

        return state_core

    async def _parse_state(
        self,
        callback_provider: str,
        state: str,
    ) -> Tuple[int, str, Optional[str], str]:
        """Parse integration state and return user/provider/redirect/state_core."""
        if not state:
            raise ValueError("Invalid state")

        state_core, _, redirect_blob = state.partition("|")
        redirect_to = None
        if redirect_blob:
            try:
                redirect_to = self._decode_redirect(redirect_blob)
            except Exception as exc:
                raise ValueError("Invalid redirect target in state") from exc

        if state_core.startswith(f"{self.STATE_PREFIX}_"):
            return await self._parse_secure_state(callback_provider, state_core, redirect_to)

        if state_core.startswith("user_"):
            return self._parse_legacy_state(callback_provider, state_core, redirect_to)

        raise ValueError("Invalid state")

    async def _parse_secure_state(
        self,
        callback_provider: str,
        state_core: str,
        redirect_to: Optional[str],
    ) -> Tuple[int, str, Optional[str], str]:
        try:
            payload = state_core[len(self.STATE_PREFIX) + 1:]
            user_part, remainder = payload.split("_", 1)
            user_id = int(user_part)
            provider, nonce, signature = remainder.rsplit("_", 2)
        except (ValueError, IndexError) as exc:
            raise ValueError("Invalid state") from exc

        if provider != callback_provider:
            raise ValueError("Provider mismatch in state")

        expected_signature = self._state_signature(user_id, provider, nonce, redirect_to)
        if not hmac.compare_digest(signature, expected_signature):
            raise ValueError("Invalid state signature")

        result = await self.db.execute(
            select(OAuthState).where(
                OAuthState.state == state_core,
                OAuthState.used.is_(False),
                OAuthState.expires_at > datetime.utcnow(),
            )
        )
        oauth_state = result.scalar_one_or_none()
        if not oauth_state:
            raise ValueError("Invalid or expired state")

        oauth_state.used = True
        await self.db.commit()

        return user_id, provider, redirect_to, state_core

    def _parse_legacy_state(
        self,
        callback_provider: str,
        state_core: str,
        redirect_to: Optional[str],
    ) -> Tuple[int, str, Optional[str], str]:
        try:
            parts = state_core.split("_")
            user_id = int(parts[1])
            provider = "_".join(parts[2:])
        except (IndexError, ValueError) as exc:
            raise ValueError("Invalid state") from exc

        if provider != callback_provider:
            raise ValueError("Provider mismatch in state")

        return user_id, provider, redirect_to, state_core

    async def _save_integration(self, user_id: int, provider: str, token_data: Dict[str, Any], client: httpx.AsyncClient):
        """Save or update integration in database."""
        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")
        
        expires_at = None
        if "expires_in" in token_data:
            expires_at = datetime.utcnow() + timedelta(seconds=token_data["expires_in"])
            
        metadata = await self._fetch_provider_metadata(provider, access_token, token_data, client)
        
        result = await self.db.execute(
            select(UserIntegration).where(
                UserIntegration.user_id == user_id,
                UserIntegration.provider == provider
            )
        )
        existing = result.scalar_one_or_none()
        
        if existing:
            existing.access_token = access_token
            if refresh_token:
                existing.refresh_token = refresh_token
            existing.expires_at = expires_at
            existing.integration_metadata = metadata
            existing.is_active = True  # Always reactivate upon successful reconnection
            existing.updated_at = datetime.utcnow()
        else:
            new_integration = UserIntegration(
                user_id=user_id,
                provider=provider,
                access_token=access_token,
                refresh_token=refresh_token,
                expires_at=expires_at,
                is_active=True,
                integration_metadata=metadata
            )
            self.db.add(new_integration)
        
        await self.db.commit()

    async def _fetch_provider_metadata(self, provider: str, access_token: str, token_data: Dict[str, Any], client: httpx.AsyncClient) -> Dict[str, Any]:
        """Fetch additional metadata for the integration."""
        metadata = {}
        if provider == "slack":
            metadata.update({
                "team_id": token_data.get("team", {}).get("id"),
                "team_name": token_data.get("team", {}).get("name"),
                "bot_user_id": token_data.get("bot_user_id"),
                "scope": token_data.get("scope")
            })
        elif provider == "notion":
            metadata.update({
                "workspace_id": token_data.get("workspace_id"),
                "workspace_name": token_data.get("workspace_name"),
                "bot_id": token_data.get("bot_id")
            })
        elif provider == "asana":
            user_data = token_data.get("data", {})
            metadata.update({
                "user_id": user_data.get("id"),
                "email": user_data.get("email"),
                "name": user_data.get("name")
            })
        elif provider.startswith("google") or provider.startswith("gmail"):
            try:
                # Add a reasonable timeout for profile fetch
                resp = await client.get(
                    "https://www.googleapis.com/oauth2/v2/userinfo",
                    headers={"Authorization": f"Bearer {access_token}"},
                    timeout=5.0
                )
                if resp.status_code == 200:
                    uinfo = resp.json()
                    metadata.update({
                        "email": uinfo.get("email"),
                        "name": uinfo.get("name"),
                        "picture": uinfo.get("picture"),
                        "scopes": token_data.get("scope") or token_data.get("scopes")
                    })
            except Exception as e:
                logger.warning(f"Failed to fetch Google user info for {provider}: {e}")
        elif provider == "linear":
            try:
                # Use GraphQL to get viewer info
                query = {"query": "{ viewer { id name email } }"}
                resp = await client.post(
                    "https://api.linear.app/graphql",
                    json=query,
                    headers={"Authorization": access_token}, # Linear uses Bearer or raw token? Docs say 'Authorization: <TOKEN>'
                    timeout=5.0
                )
                if resp.status_code == 200:
                    data = resp.json().get("data", {}).get("viewer", {})
                    metadata.update({
                        "user_id": data.get("id"),
                        "name": data.get("name"),
                        "email": data.get("email")
                    })
            except Exception as e:
                logger.warning(f"Failed to fetch Linear metadata: {e}")
        return metadata

    async def disconnect(self, user_id: int, provider: str):
        """Remove an integration."""
        result = await self.db.execute(
            select(UserIntegration).where(
                UserIntegration.user_id == user_id,
                UserIntegration.provider == provider
            )
        )
        existing = result.scalar_one_or_none()
        if not existing:
            raise ValueError("Integration not found")
        await self.db.delete(existing)
        await self.db.commit()

    async def toggle(self, user_id: int, provider: str) -> bool:
        """Toggle integration active status."""
        result = await self.db.execute(
            select(UserIntegration).where(
                UserIntegration.user_id == user_id,
                UserIntegration.provider == provider
            )
        )
        existing = result.scalar_one_or_none()
        if not existing:
            raise ValueError("Integration not found")
        existing.is_active = not existing.is_active
        await self.db.commit()
        return existing.is_active

    async def get_user_integrations(self, user_id: int) -> List[Dict[str, Any]]:
        """Get status of all user integrations."""
        result = await self.db.execute(
            select(UserIntegration).where(
                UserIntegration.user_id == user_id
            )
        )
        integrations = result.scalars().all()
        return [
            {
                "provider": i.provider,
                "is_active": i.is_active,
                "connected_at": i.created_at.isoformat() if i.created_at else None,
                "email": i.integration_metadata.get("email") if i.integration_metadata else None
            }
            for i in integrations
        ]
