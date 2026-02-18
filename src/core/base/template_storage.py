"""
Base Template Storage
Provides common functionality for template storage implementations
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
from pathlib import Path
import json

from ...utils.logger import setup_logger
from ...utils.file_encryption import load_encrypted_json, save_encrypted_json

logger = setup_logger(__name__)


class BaseTemplateStorage(ABC):
    """
    Abstract base class for template storage
    
    Provides common functionality for storing and retrieving templates.
    Subclasses can implement different storage strategies (file-based, database, etc.)
    """
    
    def __init__(self, storage_path: Optional[str] = None):
        """
        Initialize template storage
        
        Args:
            storage_path: Path to storage location (file, directory, or database connection)
        """
        self.storage_path = Path(storage_path) if storage_path else self._get_default_storage_path()
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._initialize_storage()
    
    @abstractmethod
    def _get_default_storage_path(self) -> Path:
        """
        Get default storage path for templates
        
        Returns:
            Path object for default storage location
        """
        pass
    
    def _initialize_storage(self):
        """Initialize storage (create directories, load cache, etc.)"""
        try:
            # Create storage directory if it doesn't exist
            if self.storage_path.suffix:
                # File path - create parent directory
                self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            else:
                # Directory path - create directory
                self.storage_path.mkdir(parents=True, exist_ok=True)
            
            # Load templates into cache
            self._load_templates()
            
        except Exception as e:
            logger.error(f"Failed to initialize template storage: {e}")
            raise
    
    @abstractmethod
    def _load_templates(self):
        """Load templates from storage into cache"""
        pass
    
    @abstractmethod
    def _save_template_to_storage(self, name: str, template: Dict[str, Any]):
        """
        Save template to persistent storage
        
        Args:
            name: Template name
            template: Template data
        """
        pass
    
    @abstractmethod
    def _delete_template_from_storage(self, name: str):
        """
        Delete template from persistent storage
        
        Args:
            name: Template name
        """
        pass
    
    def template_exists(self, name: str) -> bool:
        """
        Check if template exists
        
        Args:
            name: Template name
            
        Returns:
            True if template exists
        """
        return name in self._cache
    
    def get_template(self, name: str) -> Optional[Dict[str, Any]]:
        """
        Get a template by name
        
        Args:
            name: Template name
            
        Returns:
            Template data or None if not found
        """
        return self._cache.get(name)
    
    def list_templates(self) -> List[str]:
        """
        List all template names
        
        Returns:
            List of template names
        """
        return list(self._cache.keys())
    
    def get_all_templates(self) -> Dict[str, Dict[str, Any]]:
        """
        Get all templates
        
        Returns:
            Dictionary of all templates
        """
        return self._cache.copy()
    
    def create_template(self, name: str, template_data: Dict[str, Any]) -> bool:
        """
        Create a new template
        
        Args:
            name: Template name
            template_data: Template configuration
            
        Returns:
            True if created successfully
        """
        try:
            if name in self._cache:
                logger.warning(f"Template '{name}' already exists")
                return False
            
            # Add to cache
            self._cache[name] = template_data
            
            # Save to storage
            self._save_template_to_storage(name, template_data)
            
            logger.info(f"Created template: {name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to create template '{name}': {e}")
            # Rollback cache
            if name in self._cache:
                del self._cache[name]
            return False
    
    def update_template(self, name: str, template_data: Dict[str, Any]) -> bool:
        """
        Update an existing template
        
        Args:
            name: Template name
            template_data: New template configuration
            
        Returns:
            True if updated successfully
        """
        try:
            if name not in self._cache:
                logger.warning(f"Template '{name}' not found")
                return False
            
            # Backup old template
            old_template = self._cache[name].copy()
            
            # Update cache
            self._cache[name] = template_data
            
            # Save to storage
            try:
                self._save_template_to_storage(name, template_data)
                logger.info(f"Updated template: {name}")
                return True
            except Exception as e:
                # Rollback cache on storage failure
                self._cache[name] = old_template
                raise e
            
        except Exception as e:
            logger.error(f"Failed to update template '{name}': {e}")
            return False
    
    def delete_template(self, name: str) -> bool:
        """
        Delete a template
        
        Args:
            name: Template name
            
        Returns:
            True if deleted successfully
        """
        try:
            if name not in self._cache:
                logger.warning(f"Template '{name}' not found")
                return False
            
            # Backup template
            old_template = self._cache[name].copy()
            
            # Remove from cache
            del self._cache[name]
            
            # Delete from storage
            try:
                self._delete_template_from_storage(name)
                logger.info(f"Deleted template: {name}")
                return True
            except Exception as e:
                # Rollback cache on storage failure
                self._cache[name] = old_template
                raise e
            
        except Exception as e:
            logger.error(f"Failed to delete template '{name}': {e}")
            return False
    
    def _load_json_file(self, file_path: Path, default_value: Any = None) -> Any:
        """
        Utility method to load JSON file
        
        Args:
            file_path: Path to JSON file
            default_value: Default value if file doesn't exist
            
        Returns:
            Loaded data or default value
        """
        return load_encrypted_json(file_path, default=default_value)
    
    def _save_json_file(self, file_path: Path, data: Any, indent: int = 2):
        """
        Utility method to save JSON file
        
        Args:
            file_path: Path to JSON file
            data: Data to save
            indent: JSON indentation
        """
        try:
            save_encrypted_json(file_path, data)
        except Exception as e:
            logger.error(f"Failed to save JSON file {file_path}: {e}")
            raise
