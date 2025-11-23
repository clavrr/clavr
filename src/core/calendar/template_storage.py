"""
Meeting Template Storage - File-based template storage for meeting templates

Templates are stored as JSON files in a templates directory and cached in memory
for fast access. In production, this could be replaced with database storage.
"""
import json
from typing import Dict, Any, Optional, List
from pathlib import Path

from ...utils.logger import setup_logger

logger = setup_logger(__name__)


class TemplateStorage:
    """
    Simple file-based template storage for meeting templates
    
    Templates are stored as JSON files in a templates directory
    """
    
    def __init__(self, storage_dir: Optional[str] = None):
        """
        Initialize template storage
        
        Args:
            storage_dir: Directory to store templates (defaults to ~/.notely/templates)
        """
        if storage_dir:
            self.storage_dir = Path(storage_dir)
        else:
            # Default to user's home directory
            home = Path.home()
            self.storage_dir = home / '.notely' / 'templates'
        
        # Create directory if it doesn't exist
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        
        # In-memory cache
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._load_templates()
    
    def _load_templates(self):
        """Load all templates from disk"""
        try:
            template_files = list(self.storage_dir.glob('*.json'))
            for template_file in template_files:
                try:
                    with open(template_file, 'r') as f:
                        template_data = json.load(f)
                        template_name = template_file.stem
                        self._cache[template_name] = template_data
                except Exception as e:
                    if logger:
                        logger.warning(f"Failed to load template {template_file}: {e}")
        except Exception as e:
            if logger:
                logger.warning(f"Failed to load templates: {e}")
    
    def _save_template(self, name: str, template: Dict[str, Any]):
        """Save template to disk"""
        try:
            template_file = self.storage_dir / f"{name}.json"
            with open(template_file, 'w') as f:
                json.dump(template, f, indent=2)
        except Exception as e:
            if logger:
                logger.error(f"Failed to save template {name}: {e}")
            raise
    
    def create_template(
        self,
        name: str,
        title: Optional[str] = None,
        duration_minutes: int = 60,
        description: Optional[str] = None,
        location: Optional[str] = None,
        default_attendees: Optional[List[str]] = None,
        recurrence: Optional[str] = None
    ) -> bool:
        """
        Create a new meeting template
        
        Args:
            name: Template name
            title: Default title
            duration_minutes: Default duration
            description: Default description
            location: Default location
            default_attendees: Default attendees
            recurrence: Default recurrence pattern
            
        Returns:
            True if created successfully
        """
        template = {
            'name': name,
            'title': title,
            'duration_minutes': duration_minutes,
            'description': description or '',
            'location': location or '',
            'default_attendees': default_attendees or [],
            'recurrence': recurrence
        }
        
        self._cache[name] = template
        self._save_template(name, template)
        
        if logger:
            logger.info(f"Created template: {name}")
        return True
    
    def get_template(self, name: str) -> Optional[Dict[str, Any]]:
        """Get a template by name"""
        return self._cache.get(name)
    
    def list_templates(self) -> List[str]:
        """List all template names"""
        return list(self._cache.keys())
    
    def delete_template(self, name: str) -> bool:
        """Delete a template"""
        if name not in self._cache:
            return False
        
        try:
            template_file = self.storage_dir / f"{name}.json"
            if template_file.exists():
                template_file.unlink()
            del self._cache[name]
            
            if logger:
                logger.info(f"Deleted template: {name}")
            return True
        except Exception as e:
            if logger:
                logger.error(f"Failed to delete template {name}: {e}")
            return False
    
    def update_template(
        self,
        name: str,
        title: Optional[str] = None,
        duration_minutes: Optional[int] = None,
        description: Optional[str] = None,
        location: Optional[str] = None,
        default_attendees: Optional[List[str]] = None,
        recurrence: Optional[str] = None
    ) -> bool:
        """Update an existing template"""
        if name not in self._cache:
            return False
        
        template = self._cache[name]
        
        if title is not None:
            template['title'] = title
        if duration_minutes is not None:
            template['duration_minutes'] = duration_minutes
        if description is not None:
            template['description'] = description
        if location is not None:
            template['location'] = location
        if default_attendees is not None:
            template['default_attendees'] = default_attendees
        if recurrence is not None:
            template['recurrence'] = recurrence
        
        self._save_template(name, template)
        
        if logger:
            logger.info(f"Updated template: {name}")
        return True
