"""
Task Presets - PostgreSQL-backed storage

Stores task presets in PostgreSQL with user-specific isolation,
ACID transactions, and full database integration. Supports variable
substitution in preset descriptions.
"""
from typing import Dict, Any, Optional, List
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from ...utils.logger import setup_logger
from ...database.models import TaskTemplate

logger = setup_logger(__name__)


class TaskTemplateStorage:
    """
    PostgreSQL-backed storage for task presets
    
    Presets support variables like {project_name}, {date}, {person_name}
    and are stored in PostgreSQL with user-specific isolation
    """
    
    def __init__(self, db_session: Session, user_id: int):
        """
        Initialize task template storage
        
        Args:
            db_session: SQLAlchemy database session
            user_id: User ID for template isolation
        """
        self.db = db_session
        self.user_id = user_id
        logger.debug(f"Initialized TaskTemplateStorage for user {user_id}")
    
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
            name: Template name (unique identifier, must be unique per user)
            description: Template display name
            task_description: Task description (supports {variables})
            priority: Default priority ('low', 'medium', 'high')
            category: Default category
            tags: Default tags
            subtasks: List of subtask descriptions
            recurrence: Recurrence pattern (if applicable)
            
        Returns:
            Created template dictionary
            
        Raises:
            ValueError: If template name already exists for this user
        """
        try:
            template = TaskTemplate(
                user_id=self.user_id,
                name=name,
                description=description,
                task_description=task_description,
                priority=priority,
                category=category,
                tags=tags or [],
                subtasks=subtasks or [],
                recurrence=recurrence,
                is_active=True
            )
            
            self.db.add(template)
            self.db.commit()
            
            logger.info(f"Created task template '{name}' for user {self.user_id}")
            return template.to_dict()
            
        except IntegrityError as e:
            self.db.rollback()
            logger.warning(f"Task template '{name}' already exists for user {self.user_id}")
            raise ValueError(f"Template '{name}' already exists") from e
        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to create task template '{name}': {e}")
            raise
    
    def get_template(self, name: str) -> Optional[Dict[str, Any]]:
        """
        Get template by name
        
        Args:
            name: Template name
            
        Returns:
            Template dictionary or None if not found
        """
        template = self.db.query(TaskTemplate).filter(
            TaskTemplate.user_id == self.user_id,
            TaskTemplate.name == name,
            TaskTemplate.is_active == True
        ).first()
        
        if template:
            return template.to_dict()
        return None
    
    def list_templates(self) -> List[Dict[str, Any]]:
        """
        List all templates for the user
        
        Returns:
            List of template dictionaries
        """
        templates = self.db.query(TaskTemplate).filter(
            TaskTemplate.user_id == self.user_id,
            TaskTemplate.is_active == True
        ).all()
        
        return [t.to_dict() for t in templates]
    
    def update_template(self, name: str, **updates) -> Dict[str, Any]:
        """
        Update an existing template
        
        Args:
            name: Template name
            **updates: Fields to update (description, task_description, priority, etc.)
            
        Returns:
            Updated template dictionary
            
        Raises:
            ValueError: If template not found
        """
        template = self.db.query(TaskTemplate).filter(
            TaskTemplate.user_id == self.user_id,
            TaskTemplate.name == name,
            TaskTemplate.is_active == True
        ).first()
        
        if not template:
            raise ValueError(f"Template '{name}' not found")
        
        # Update allowed fields
        allowed_fields = ['description', 'task_description', 'priority', 'category', 'tags', 'subtasks', 'recurrence']
        for field, value in updates.items():
            if field in allowed_fields and hasattr(template, field):
                setattr(template, field, value)
        
        self.db.commit()
        
        logger.info(f"Updated task template '{name}' for user {self.user_id}")
        return template.to_dict()
    
    def delete_template(self, name: str) -> bool:
        """
        Delete a template (soft delete by setting is_active=False)
        
        Args:
            name: Template name
            
        Returns:
            True if deleted, False if not found
        """
        template = self.db.query(TaskTemplate).filter(
            TaskTemplate.user_id == self.user_id,
            TaskTemplate.name == name,
            TaskTemplate.is_active == True
        ).first()
        
        if not template:
            return False
        
        template.is_active = False
        self.db.commit()
        
        logger.info(f"Deleted task template '{name}' for user {self.user_id}")
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
            
        Raises:
            ValueError: If template not found
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
    
    def get_default_templates(self) -> List[Dict[str, Any]]:
        """
        Get default task templates (for seeding new users)
        
        Returns:
            List of default template dictionaries
        """
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

