"""
Secrets Manager Abstraction

Provides a unified interface for accessing secrets from various backends:
- Environment variables (development)
- HashiCorp Vault (production)
- AWS Secrets Manager (AWS deployments)
- Azure Key Vault (Azure deployments)

Falls back gracefully when backends are unavailable.
"""
import os
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from functools import lru_cache
from datetime import datetime, timedelta

from .logger import setup_logger

logger = setup_logger(__name__)


class SecretsBackend(ABC):
    """Abstract base class for secrets backends."""
    
    @abstractmethod
    def get_secret(self, key: str) -> Optional[str]:
        """Get a secret value by key."""
        pass
    
    @abstractmethod
    def set_secret(self, key: str, value: str) -> bool:
        """Set a secret value (if supported)."""
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        """Check if this backend is available."""
        pass


class EnvironmentBackend(SecretsBackend):
    """
    Environment variable backend.
    
    Simple backend that reads secrets from environment variables.
    Good for development but not recommended for production.
    """
    
    def __init__(self, prefix: str = ""):
        self.prefix = prefix
    
    def get_secret(self, key: str) -> Optional[str]:
        env_key = f"{self.prefix}{key}" if self.prefix else key
        return os.getenv(env_key)
    
    def set_secret(self, key: str, value: str) -> bool:
        """Environment variables are read-only in this context."""
        logger.warning("Cannot set secrets via environment backend")
        return False
    
    def is_available(self) -> bool:
        return True


class VaultBackend(SecretsBackend):
    """
    HashiCorp Vault backend.
    
    Requires:
    - VAULT_URL: Vault server URL
    - VAULT_TOKEN: Authentication token
    - VAULT_PATH_PREFIX: Path prefix for secrets (default: "secret/data/clavr")
    """
    
    def __init__(
        self,
        url: Optional[str] = None,
        token: Optional[str] = None,
        path_prefix: str = "secret/data/clavr"
    ):
        self.url = url or os.getenv("VAULT_URL")
        self.token = token or os.getenv("VAULT_TOKEN")
        self.path_prefix = path_prefix
        self._client = None
        self._cache: Dict[str, tuple] = {}  # (value, expiry)
        self._cache_ttl = 300  # 5 minutes
    
    def _get_client(self):
        """Lazy-load Vault client."""
        if self._client is None:
            try:
                import hvac
                self._client = hvac.Client(url=self.url, token=self.token)
                if not self._client.is_authenticated():
                    logger.warning("Vault client not authenticated")
                    self._client = None
            except ImportError:
                logger.debug("hvac package not installed")
            except Exception as e:
                logger.warning(f"Vault connection failed: {e}")
        return self._client
    
    def get_secret(self, key: str) -> Optional[str]:
        # Check cache first
        if key in self._cache:
            value, expiry = self._cache[key]
            if datetime.utcnow() < expiry:
                return value
            del self._cache[key]
        
        client = self._get_client()
        if not client:
            return None
        
        try:
            path = f"{self.path_prefix}/{key}"
            result = client.secrets.kv.v2.read_secret_version(path=path)
            value = result["data"]["data"].get("value")
            
            # Cache the result
            self._cache[key] = (value, datetime.utcnow() + timedelta(seconds=self._cache_ttl))
            
            return value
        except Exception as e:
            logger.debug(f"Vault read failed for {key}: {e}")
            return None
    
    def set_secret(self, key: str, value: str) -> bool:
        client = self._get_client()
        if not client:
            return False
        
        try:
            path = f"{self.path_prefix}/{key}"
            client.secrets.kv.v2.create_or_update_secret(
                path=path,
                secret={"value": value}
            )
            
            # Update cache
            self._cache[key] = (value, datetime.utcnow() + timedelta(seconds=self._cache_ttl))
            
            return True
        except Exception as e:
            logger.error(f"Vault write failed for {key}: {e}")
            return False
    
    def is_available(self) -> bool:
        client = self._get_client()
        return client is not None and client.is_authenticated()


class AWSSecretsBackend(SecretsBackend):
    """
    AWS Secrets Manager backend.
    
    Requires:
    - AWS credentials (via environment or IAM role)
    - AWS_REGION: AWS region
    - AWS_SECRET_PREFIX: Secret name prefix (default: "clavr/")
    """
    
    def __init__(
        self,
        region: Optional[str] = None,
        prefix: str = "clavr/"
    ):
        self.region = region or os.getenv("AWS_REGION", "us-east-1")
        self.prefix = prefix
        self._client = None
        self._cache: Dict[str, tuple] = {}
        self._cache_ttl = 300
    
    def _get_client(self):
        """Lazy-load AWS Secrets Manager client."""
        if self._client is None:
            try:
                import boto3
                self._client = boto3.client(
                    "secretsmanager",
                    region_name=self.region
                )
            except ImportError:
                logger.debug("boto3 package not installed")
            except Exception as e:
                logger.warning(f"AWS Secrets Manager connection failed: {e}")
        return self._client
    
    def get_secret(self, key: str) -> Optional[str]:
        # Check cache first
        if key in self._cache:
            value, expiry = self._cache[key]
            if datetime.utcnow() < expiry:
                return value
            del self._cache[key]
        
        client = self._get_client()
        if not client:
            return None
        
        try:
            secret_name = f"{self.prefix}{key}"
            response = client.get_secret_value(SecretId=secret_name)
            value = response.get("SecretString")
            
            # Cache the result
            self._cache[key] = (value, datetime.utcnow() + timedelta(seconds=self._cache_ttl))
            
            return value
        except Exception as e:
            logger.debug(f"AWS Secrets Manager read failed for {key}: {e}")
            return None
    
    def set_secret(self, key: str, value: str) -> bool:
        client = self._get_client()
        if not client:
            return False
        
        try:
            secret_name = f"{self.prefix}{key}"
            client.put_secret_value(SecretId=secret_name, SecretString=value)
            
            # Update cache
            self._cache[key] = (value, datetime.utcnow() + timedelta(seconds=self._cache_ttl))
            
            return True
        except Exception as e:
            logger.error(f"AWS Secrets Manager write failed for {key}: {e}")
            return False
    
    def is_available(self) -> bool:
        client = self._get_client()
        if not client:
            return False
        try:
            # Quick check - list secrets (won't fail on auth issues)
            client.list_secrets(MaxResults=1)
            return True
        except Exception:
            return False


class SecretsManager:
    """
    Unified secrets manager with fallback chain.
    
    Tries backends in order:
    1. Primary backend (Vault, AWS, etc.)
    2. Environment variables (fallback)
    
    Example:
        secrets = SecretsManager()
        encryption_key = secrets.get("ENCRYPTION_KEY")
        db_password = secrets.get("DATABASE_PASSWORD")
    """
    
    def __init__(
        self,
        primary_backend: Optional[SecretsBackend] = None,
        use_vault: bool = True,
        use_aws: bool = True,
        env_prefix: str = ""
    ):
        """
        Initialize secrets manager.
        
        Args:
            primary_backend: Primary backend to use
            use_vault: Whether to try Vault if primary not set
            use_aws: Whether to try AWS if Vault not available
            env_prefix: Prefix for environment variable names
        """
        self._backends: list[SecretsBackend] = []
        
        # Add primary backend if provided
        if primary_backend:
            self._backends.append(primary_backend)
        
        # Try Vault
        if use_vault and not primary_backend:
            vault = VaultBackend()
            if vault.is_available():
                self._backends.append(vault)
                logger.info("[OK] Secrets Manager: Using HashiCorp Vault")
        
        # Try AWS Secrets Manager
        if use_aws and not self._backends:
            aws = AWSSecretsBackend()
            if aws.is_available():
                self._backends.append(aws)
                logger.info("[OK] Secrets Manager: Using AWS Secrets Manager")
        
        # Always add environment as fallback
        self._backends.append(EnvironmentBackend(prefix=env_prefix))
        
        if len(self._backends) == 1:
            logger.warning(
                "Secrets Manager: Using environment variables only. "
                "Consider configuring Vault or AWS Secrets Manager for production."
            )
    
    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """
        Get a secret value.
        
        Tries each backend in order until one returns a value.
        
        Args:
            key: Secret key name
            default: Default value if not found
            
        Returns:
            Secret value or default
        """
        for backend in self._backends:
            value = backend.get_secret(key)
            if value is not None:
                return value
        
        return default
    
    def get_required(self, key: str) -> str:
        """
        Get a required secret value.
        
        Raises:
            ValueError: If secret not found in any backend
        """
        value = self.get(key)
        if value is None:
            raise ValueError(f"Required secret not found: {key}")
        return value
    
    def set(self, key: str, value: str) -> bool:
        """
        Set a secret value (in primary writable backend).
        
        Returns:
            True if successful, False otherwise
        """
        for backend in self._backends:
            if backend.set_secret(key, value):
                return True
        return False
    
    @property
    def primary_backend(self) -> str:
        """Get the name of the primary backend being used."""
        if self._backends:
            return self._backends[0].__class__.__name__
        return "None"


# Singleton instance
_secrets_manager: Optional[SecretsManager] = None


def get_secrets_manager() -> SecretsManager:
    """Get the singleton secrets manager instance."""
    global _secrets_manager
    
    if _secrets_manager is None:
        _secrets_manager = SecretsManager()
    
    return _secrets_manager


# Convenience functions
def get_secret(key: str, default: Optional[str] = None) -> Optional[str]:
    """Get a secret value."""
    return get_secrets_manager().get(key, default)


def get_required_secret(key: str) -> str:
    """Get a required secret value."""
    return get_secrets_manager().get_required(key)
