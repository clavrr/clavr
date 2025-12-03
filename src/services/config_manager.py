"""
Configuration Manager Service - Centralized configuration and environment management

Provides intelligent configuration management with:
- Environment-specific configurations
- Configuration validation
- Dynamic configuration updates
- Configuration caching
- Service-specific configuration sections
"""
import os
import yaml
from typing import Dict, Any, Optional, Union, List, List
from pathlib import Path
from dataclasses import dataclass, field

from ..utils.config import Config, load_config
from ..utils.logger import setup_logger

logger = setup_logger(__name__)


@dataclass
class ServiceConfig:
    """Service-specific configuration section"""
    enabled: bool = True
    timeout: int = 30
    retry_attempts: int = 3
    rate_limit: Optional[int] = None
    extra_params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EnvironmentConfig:
    """Environment-specific configuration"""
    name: str
    debug: bool = False
    log_level: str = "INFO"
    services: Dict[str, ServiceConfig] = field(default_factory=dict)
    databases: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    apis: Dict[str, Dict[str, Any]] = field(default_factory=dict)


class ConfigManager:
    """
    Centralized configuration manager for services
    
    Features:
    - Environment-specific configurations
    - Service configuration validation
    - Dynamic config reloading
    - Configuration inheritance and overrides
    - Integration with existing Config class
    
    Usage:
        config_manager = ConfigManager()
        email_config = config_manager.get_service_config('email')
        db_config = config_manager.get_database_config('primary')
    """
    
    def __init__(
        self,
        config_path: Optional[str] = None,
        environment: Optional[str] = None,
        base_config: Optional[Config] = None
    ):
        """
        Initialize configuration manager
        
        Args:
            config_path: Path to configuration file
            environment: Environment name (development/staging/production)
            base_config: Existing Config instance to extend
        """
        self.config_path = config_path or "config/config.yaml"
        self.environment = environment or os.getenv("ENVIRONMENT", "development")
        
        # Load base configuration
        if base_config:
            self.base_config = base_config
        else:
            self.base_config = load_config(self.config_path)
        
        # Load environment-specific configurations
        self.env_configs: Dict[str, EnvironmentConfig] = {}
        self.service_configs: Dict[str, ServiceConfig] = {}
        
        self._load_configurations()
        self._validate_configuration()
    
    def _load_configurations(self):
        """Load environment and service configurations"""
        try:
            # Load environment-specific config
            env_config_path = Path(self.config_path).parent / f"config-{self.environment}.yaml"
            if env_config_path.exists():
                with open(env_config_path, 'r') as f:
                    env_data = yaml.safe_load(f)
                    
                self.env_configs[self.environment] = EnvironmentConfig(
                    name=self.environment,
                    **env_data.get('environment', {})
                )
            
            # Load service configurations
            services_config_path = Path(self.config_path).parent / "services.yaml"
            if services_config_path.exists():
                with open(services_config_path, 'r') as f:
                    services_data = yaml.safe_load(f)
                    
                for service_name, service_data in services_data.get('services', {}).items():
                    self.service_configs[service_name] = ServiceConfig(**service_data)
            
            logger.info(f"[CONFIG_MANAGER] Loaded configuration for environment: {self.environment}")
            
        except Exception as e:
            logger.warning(f"[CONFIG_MANAGER] Failed to load extended configurations: {e}")
            # Use default configurations
            self.env_configs[self.environment] = EnvironmentConfig(name=self.environment)
    
    def _validate_configuration(self):
        """Validate configuration completeness and consistency"""
        issues = []
        
        # Check required base configuration
        if not hasattr(self.base_config, 'database_url'):
            issues.append("Missing database_url in base configuration")
        
        # Check service configurations
        required_services = ['email', 'calendar', 'task']
        for service in required_services:
            if service not in self.service_configs:
                # Create default service config
                self.service_configs[service] = ServiceConfig()
                logger.info(f"[CONFIG_MANAGER] Created default config for service: {service}")
        
        if issues:
            logger.warning(f"[CONFIG_MANAGER] Configuration issues: {issues}")
    
    def get_service_config(self, service_name: str) -> ServiceConfig:
        """
        Get configuration for a specific service
        
        Args:
            service_name: Name of the service (email, calendar, task, etc.)
            
        Returns:
            ServiceConfig instance with service-specific settings
        """
        return self.service_configs.get(service_name, ServiceConfig())
    
    def get_database_config(self, db_name: str = "primary") -> Dict[str, Any]:
        """
        Get database configuration
        
        Args:
            db_name: Database name (primary, cache, etc.)
            
        Returns:
            Database configuration dictionary
        """
        env_config = self.env_configs.get(self.environment, EnvironmentConfig(name=self.environment))
        db_config = env_config.databases.get(db_name, {})
        
        # Fallback to base config
        if not db_config and hasattr(self.base_config, 'database_url'):
            db_config = {
                'url': self.base_config.database_url,
                'pool_size': getattr(self.base_config, 'db_pool_size', 5),
                'max_overflow': getattr(self.base_config, 'db_max_overflow', 10),
            }
        
        return db_config
    
    def get_api_config(self, api_name: str) -> Dict[str, Any]:
        """
        Get API configuration
        
        Args:
            api_name: API name (gmail, calendar, openai, etc.)
            
        Returns:
            API configuration dictionary
        """
        env_config = self.env_configs.get(self.environment, EnvironmentConfig(name=self.environment))
        return env_config.apis.get(api_name, {})
    
    def is_service_enabled(self, service_name: str) -> bool:
        """Check if a service is enabled"""
        service_config = self.get_service_config(service_name)
        return service_config.enabled
    
    def get_service_timeout(self, service_name: str) -> int:
        """Get timeout for a service"""
        service_config = self.get_service_config(service_name)
        return service_config.timeout
    
    def get_service_retry_attempts(self, service_name: str) -> int:
        """Get retry attempts for a service"""
        service_config = self.get_service_config(service_name)
        return service_config.retry_attempts
    
    def update_service_config(
        self,
        service_name: str,
        updates: Dict[str, Any]
    ):
        """
        Update service configuration dynamically
        
        Args:
            service_name: Service name
            updates: Configuration updates
        """
        if service_name not in self.service_configs:
            self.service_configs[service_name] = ServiceConfig()
        
        service_config = self.service_configs[service_name]
        
        for key, value in updates.items():
            if hasattr(service_config, key):
                setattr(service_config, key, value)
            else:
                service_config.extra_params[key] = value
        
        logger.info(f"[CONFIG_MANAGER] Updated configuration for service: {service_name}")
    
    def reload_configuration(self):
        """Reload configuration from files"""
        logger.info("[CONFIG_MANAGER] Reloading configuration")
        self.base_config = load_config(self.config_path)
        self._load_configurations()
        self._validate_configuration()
    
    def get_environment_info(self) -> Dict[str, Any]:
        """Get current environment information"""
        env_config = self.env_configs.get(self.environment, EnvironmentConfig(name=self.environment))
        return {
            'name': env_config.name,
            'debug': env_config.debug,
            'log_level': env_config.log_level,
            'services_count': len(self.service_configs),
            'enabled_services': [
                name for name, config in self.service_configs.items()
                if config.enabled
            ]
        }
    
    def validate_service_dependencies(self, service_name: str) -> List[str]:
        """
        Validate service dependencies
        
        Args:
            service_name: Service to validate
            
        Returns:
            List of missing dependencies
        """
        dependencies = {
            'email': ['gmail_credentials'],
            'calendar': ['calendar_credentials'],
            'task': ['task_credentials'],
            'rag': ['openai_api_key', 'pinecone_api_key']
        }
        
        missing = []
        required_deps = dependencies.get(service_name, [])
        
        for dep in required_deps:
            if not getattr(self.base_config, dep, None) and not os.getenv(dep.upper()):
                missing.append(dep)
        
        return missing


# Global configuration manager instance
_config_manager: Optional[ConfigManager] = None


def get_config_manager(
    config_path: Optional[str] = None,
    environment: Optional[str] = None,
    force_reload: bool = False
) -> ConfigManager:
    """
    Get global configuration manager instance
    
    Args:
        config_path: Path to configuration file
        environment: Environment name
        force_reload: Force reload configuration
        
    Returns:
        ConfigManager instance
    """
    global _config_manager
    
    if _config_manager is None or force_reload:
        _config_manager = ConfigManager(
            config_path=config_path,
            environment=environment
        )
    
    return _config_manager


def configure_service_from_manager(
    service_name: str,
    config_manager: Optional[ConfigManager] = None
) -> Dict[str, Any]:
    """
    Helper function to get service configuration from config manager
    
    Args:
        service_name: Name of the service
        config_manager: Optional config manager instance
        
    Returns:
        Service configuration dictionary
    """
    if config_manager is None:
        config_manager = get_config_manager()
    
    service_config = config_manager.get_service_config(service_name)
    base_config = config_manager.base_config
    
    return {
        'base_config': base_config,
        'enabled': service_config.enabled,
        'timeout': service_config.timeout,
        'retry_attempts': service_config.retry_attempts,
        'rate_limit': service_config.rate_limit,
        'extra_params': service_config.extra_params,
        'missing_deps': config_manager.validate_service_dependencies(service_name)
    }