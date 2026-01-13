"""
IntegrationService - Manages third-party integrations and OAuth flows.
"""
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import httpx
from urllib.parse import urlencode, quote

import os
from src.database.models import User, UserIntegration
from src.utils.logger import setup_logger
from src.utils.config import Config
from src.utils.encryption import encrypt_token
from src.auth.oauth import GMAIL_SCOPES, CALENDAR_SCOPES, TASKS_SCOPES, DRIVE_SCOPES

logger = setup_logger(__name__)

class IntegrationService:
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
        
        state = f"user_{user_id}_{provider}"
        
        if redirect_to:
            import base64
            # We use | as a separator because state already uses _ for parts
            b64_redirect = base64.urlsafe_b64encode(redirect_to.encode()).decode()
            state = f"{state}|{b64_redirect}"
        
        if provider == "notion":
            url = (
                f"{config['auth_url']}?"
                f"owner=user&"
                f"client_id={config['client_id']}&"
                f"redirect_uri={quote(config['redirect_uri'], safe='')}&"
                f"response_type=code&"
                f"state={state}"
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
        
        if provider.startswith("google") or provider == "gmail":
            params["access_type"] = "offline"
            params["prompt"] = "consent"
            if user_email:
                params["login_hint"] = user_email
                
        return f"{config['auth_url']}?{urlencode(params)}"

    async def handle_callback(self, provider: str, code: str, state: str) -> str:
        """Process OAuth callback and store tokens."""
        config = self.oauth_configs.get(provider)
        if not config:
            raise ValueError("Invalid provider")
            
        # Verify state
        real_provider = provider
        try:
            parts = state.split("_")
            user_id = int(parts[1])
            if len(parts) > 2:
                real_provider = "_".join(parts[2:])
        except (IndexError, ValueError):
            raise ValueError("Invalid state")
            
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
        if provider == "notion":
            auth = (config["client_id"], config["client_secret"])
            del data["client_id"]
            del data["client_secret"]
            
        async with httpx.AsyncClient() as client:
            response = await client.post(config["token_url"], data=data, headers=headers, auth=auth)
            if response.status_code != 200:
                logger.error(f"Failed to exchange token for {provider}: {response.text}")
                raise Exception("Token exchange failed")
                
            token_data = response.json()
            await self._save_integration(user_id, real_provider, token_data, client)
            
        return real_provider, token_data

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
            existing.access_token = encrypt_token(access_token)
            if refresh_token:
                existing.refresh_token = encrypt_token(refresh_token)
            existing.expires_at = expires_at
            existing.integration_metadata = metadata
            existing.is_active = True  # Always reactivate upon successful reconnection
            existing.updated_at = datetime.utcnow()
        else:
            new_integration = UserIntegration(
                user_id=user_id,
                provider=provider,
                access_token=encrypt_token(access_token),
                refresh_token=encrypt_token(refresh_token) if refresh_token else None,
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
