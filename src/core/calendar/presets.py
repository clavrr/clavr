"""
Meeting Presets - PostgreSQL-backed storage

Stores meeting presets in PostgreSQL with user-specific isolation,
ACID transactions, and full database integration.
"""
from typing import Dict, Any, Optional, List
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from ...utils.logger import setup_logger
from ...database.models import MeetingTemplate

logger = setup_logger(__name__)


class TemplateStorage:
    """
    PostgreSQL-backed storage for meeting presets
    
    Presets are stored in PostgreSQL with user-specific isolation
    """
    
    def __init__(self, db_session: Session, user_id: int):
        """
        Initialize template storage
        
        Args:
            db_session: SQLAlchemy database session
            user_id: User ID for template isolation
        """
        self.db = db_session
        self.user_id = user_id
        logger.debug(f"Initialized TemplateStorage for user {user_id}")
    
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
            name: Template name (must be unique per user)
            title: Default title
            duration_minutes: Default duration
            description: Default description
            location: Default location
            default_attendees: Default attendees (list of email addresses)
            recurrence: Default recurrence pattern
            
        Returns:
            True if created successfully
            
        Raises:
            ValueError: If template name already exists for this user
        """
        try:
            template = MeetingTemplate(
                user_id=self.user_id,
                name=name,
                title=title,
                duration_minutes=duration_minutes,
                description=description or '',
                location=location or '',
                default_attendees=default_attendees or [],
                recurrence=recurrence,
                is_active=True
            )
            
            self.db.add(template)
            self.db.commit()
            
            logger.info(f"Created template '{name}' for user {self.user_id}")
            return True
            
        except IntegrityError as e:
            self.db.rollback()
            logger.debug(f"Template '{name}' already exists for user {self.user_id} (expected during cleanup)")
            raise ValueError(f"Template '{name}' already exists") from e
        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to create template '{name}': {e}")
            raise
    
    def get_template(self, name: str) -> Optional[Dict[str, Any]]:
        """
        Get a template by name
        
        Args:
            name: Template name
            
        Returns:
            Template dictionary or None if not found
        """
        template = self.db.query(MeetingTemplate).filter(
            MeetingTemplate.user_id == self.user_id,
            MeetingTemplate.name == name,
            MeetingTemplate.is_active == True
        ).first()
        
        if template:
            return template.to_dict()
        return None
    
    def list_templates(self) -> List[str]:
        """
        List all template names for the user
        
        Returns:
            List of template names
        """
        templates = self.db.query(MeetingTemplate).filter(
            MeetingTemplate.user_id == self.user_id,
            MeetingTemplate.is_active == True
        ).all()
        
        return [t.name for t in templates]
    
    def list_templates_full(self) -> List[Dict[str, Any]]:
        """
        List all templates with full details
        
        Returns:
            List of template dictionaries
        """
        templates = self.db.query(MeetingTemplate).filter(
            MeetingTemplate.user_id == self.user_id,
            MeetingTemplate.is_active == True
        ).all()
        
        return [t.to_dict() for t in templates]
    
    def delete_template(self, name: str) -> bool:
        """
        Delete a template (soft delete by setting is_active=False)
        
        Args:
            name: Template name
            
        Returns:
            True if deleted, False if not found
        """
        template = self.db.query(MeetingTemplate).filter(
            MeetingTemplate.user_id == self.user_id,
            MeetingTemplate.name == name,
            MeetingTemplate.is_active == True
        ).first()
        
        if not template:
            return False
        
        template.is_active = False
        self.db.commit()
        
        logger.info(f"Deleted template '{name}' for user {self.user_id}")
        return True
    
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
        """
        Update an existing template
        
        Args:
            name: Template name
            title: New title (if provided)
            duration_minutes: New duration (if provided)
            description: New description (if provided)
            location: New location (if provided)
            default_attendees: New attendees (if provided)
            recurrence: New recurrence pattern (if provided)
            
        Returns:
            True if updated, False if not found
        """
        template = self.db.query(MeetingTemplate).filter(
            MeetingTemplate.user_id == self.user_id,
            MeetingTemplate.name == name,
            MeetingTemplate.is_active == True
        ).first()
        
        if not template:
            return False
        
        # Update only provided fields
        if title is not None:
            template.title = title
        if duration_minutes is not None:
            template.duration_minutes = duration_minutes
        if description is not None:
            template.description = description
        if location is not None:
            template.location = location
        if default_attendees is not None:
            template.default_attendees = default_attendees
        if recurrence is not None:
            template.recurrence = recurrence
        
        self.db.commit()
        
        logger.info(f"Updated template '{name}' for user {self.user_id}")
        return True

