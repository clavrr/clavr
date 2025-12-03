"""
Task Template Storage - Reusable task templates
"""
from typing import Optional, List, Dict, Any
from pathlib import Path
from datetime import datetime

from ...utils.logger import setup_logger
from .utils import load_json_file, save_json_file

logger = setup_logger(__name__)


class TaskTemplateStorage:
    """
    Store and retrieve task templates
    
    Templates support variables like {project_name}, {date}, {person_name}
    """
    
    def __init__(self, storage_path: str = "./data/task_templates.json"):
        """
        Initialize template storage
        
        Args:
            storage_path: Path to JSON file for storing templates
        """
        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        
        if not self.storage_path.exists():
            self._save_templates(self._get_default_templates())
        
        logger.info(f"[OK] Task template storage initialized (storage: {storage_path})")
    
    def _get_default_templates(self) -> List[Dict[str, Any]]:
        """Get default task templates"""
        return [
            {
                'name': 'weekly_review',
                'description': 'Weekly Review',
                'task_description': 'Weekly review and planning',
                'priority': 'high',
                'category': 'work',
                'tags': ['review', 'planning'],
                'recurrence': 'weekly'
            },
            {
                'name': 'daily_standup',
                'description': 'Daily Standup',
                'task_description': 'Daily standup meeting',
                'priority': 'medium',
                'category': 'work',
                'tags': ['meeting', 'standup'],
                'recurrence': 'daily'
            },
            {
                'name': 'project_kickoff',
                'description': 'Project Kickoff',
                'task_description': 'Kickoff meeting for {project_name}',
                'priority': 'high',
                'category': 'work',
                'tags': ['meeting', 'project'],
                'subtasks': [
                    'Prepare agenda',
                    'Invite stakeholders',
                    'Review project brief'
                ]
            },
            {
                'name': 'client_meeting_prep',
                'description': 'Client Meeting Preparation',
                'task_description': 'Prepare for meeting with {client_name}',
                'priority': 'high',
                'category': 'work',
                'tags': ['meeting', 'client'],
                'subtasks': [
                    'Review previous notes',
                    'Prepare agenda',
                    'Gather materials'
                ]
            }
        ]
    
    def _load_templates(self) -> List[Dict[str, Any]]:
        """Load templates from storage"""
        templates = load_json_file(self.storage_path, default_value=None)
        if templates is None:
            return self._get_default_templates()
        return templates
    
    def _save_templates(self, templates: List[Dict[str, Any]]):
        """Save templates to storage"""
        save_json_file(self.storage_path, templates)
    
    def create_template(
        self,
        name: str,
        description: str,
        task_description: str,
        priority: str = "medium",
        category: Optional[str] = None,
        tags: Optional[List[str]] = None,
        subtasks: Optional[List[str]] = None,
        recurrence: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create a new task template
        
        Args:
            name: Template name (unique identifier)
            description: Template display name
            task_description: Task description (supports {variables})
            priority: Default priority
            category: Default category
            tags: Default tags
            subtasks: List of subtask descriptions
            recurrence: Recurrence pattern (if applicable)
            
        Returns:
            Created template dictionary
        """
        templates = self._load_templates()
        
        # Check if template already exists
        for template in templates:
            if template.get('name') == name:
                raise ValueError(f"Template '{name}' already exists")
        
        template = {
            'name': name,
            'description': description,
            'task_description': task_description,
            'priority': priority,
            'category': category,
            'tags': tags or [],
            'subtasks': subtasks or [],
            'recurrence': recurrence,
            'created_at': datetime.now().isoformat()
        }
        
        templates.append(template)
        self._save_templates(templates)
        
        logger.info(f"Created template: {name}")
        return template
    
    def get_template(self, name: str) -> Optional[Dict[str, Any]]:
        """Get template by name"""
        templates = self._load_templates()
        for template in templates:
            if template.get('name') == name:
                return template
        return None
    
    def list_templates(self) -> List[Dict[str, Any]]:
        """List all templates"""
        return self._load_templates()
    
    def update_template(self, name: str, **updates) -> Dict[str, Any]:
        """Update an existing template"""
        templates = self._load_templates()
        
        for template in templates:
            if template.get('name') == name:
                template.update(updates)
                self._save_templates(templates)
                logger.info(f"Updated template: {name}")
                return template
        
        raise ValueError(f"Template '{name}' not found")
    
    def delete_template(self, name: str) -> bool:
        """Delete a template"""
        templates = self._load_templates()
        original_count = len(templates)
        
        templates = [t for t in templates if t.get('name') != name]
        
        if len(templates) == original_count:
            return False
        
        self._save_templates(templates)
        logger.info(f"Deleted template: {name}")
        return True
    
    def expand_template(
        self,
        template_name: str,
        variables: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        Expand a template with variables
        
        Args:
            template_name: Template name
            variables: Dictionary of variable values (e.g., {'project_name': 'Website Redesign'})
            
        Returns:
            Expanded task dictionary ready for creation
        """
        template = self.get_template(template_name)
        if not template:
            raise ValueError(f"Template '{template_name}' not found")
        
        variables = variables or {}
        
        # Expand task description with variables
        task_description = template.get('task_description', '')
        for key, value in variables.items():
            task_description = task_description.replace(f'{{{key}}}', value)
        
        result = {
            'description': task_description,
            'priority': template.get('priority', 'medium'),
            'category': template.get('category'),
            'tags': template.get('tags', []).copy(),
            'subtasks': template.get('subtasks', []).copy(),
            'recurrence': template.get('recurrence')
        }
        
        # Expand subtasks with variables
        if result['subtasks']:
            expanded_subtasks = []
            for subtask in result['subtasks']:
                expanded_subtask = subtask
                for key, value in variables.items():
                    expanded_subtask = expanded_subtask.replace(f'{{{key}}}', value)
                expanded_subtasks.append(expanded_subtask)
            result['subtasks'] = expanded_subtasks
        
        return result

